"""781/R4-02: wires 721's real upload adapter into 728's diff/preview
route (``POST /v1/projects/{id}/transformations`` /
``GET .../{run_id}/diff``), through ``cairn_api.app.create_app``'s own
default wiring -- not an injected fake source port.

``test_transformations_api.py`` already proves the route itself is
generic over ``RepositoryRef``'s tagged union (it injects a
``FakeRepositorySource``, which has always supported both ``GIT`` and
``UPLOAD`` keys). The actual gap this unit closes is one level lower:
``create_app``'s production default built only a bare
``GitSourceAdapter``, which has no ``archive_id`` to read off an
``UploadRepositoryRef`` and would fail on one. This file drives the
same route with ``create_app``'s *default* ``transformation_source_port``
(only ``transformation_archive_loader`` is supplied, the one piece 721's
real ``UploadSourceAdapter`` cannot invent for itself -- see its own
module docstring) for both a real local Git ref and a real uploaded zip
archive, built from the same fixture content, and asserts the two runs'
diff artefacts are identical except for their own run identity -- the
"round-trips exactly like a Git-source one" proof the unit's acceptance
text asks for.

No real network call anywhere: the Git half clones a local ``file://``
repo, the same technique ``packages/adapters/tests/test_source_git.py``
already uses; the upload half unpacks an in-memory zip via an injected
``archive_loader``, never reading or writing any real file."""

from __future__ import annotations

import os
import subprocess
import zipfile
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import jwt
from cairn_adapters.auth_oidc import JwtAuthenticator, OidcSettings
from cairn_adapters.transform_core.fake import FakeTransformationPort
from cairn_api import create_app
from cairn_contracts.transformation import SourceFile, SourceLanguage
from cairn_modules.transformation.runs import FakeTransformationRunRepository
from fastapi.testclient import TestClient

SECRET = "test-secret-that-is-long-enough-for-hs256"
ISSUER = "https://issuer.example.test"
AUDIENCE = "cairn-api"
TENANT_A = "6f0f0f31-6d0c-4f25-9a45-1d0e1a0f1f6a"
PROJECT_ID = "22222222-2222-2222-2222-222222222222"

DETECTOR_VERSION = "cairn-detector/0.1.0"
PATCHER_VERSION = "cairn-transform-patcher/0.1.0"
HCL_PARSER_VERSION = "cairn-hcl-parser/0.1.0"

SOURCE_PATH = "s3.tf"
SOURCE_CONTENT = 'resource "aws_s3_bucket" "b" {\n  acl = "public-read"\n}\n'

# Matches test_transformations_api.py's own fixture shape: one APPLIED
# entry rewriting the deprecated inline ACL, keyed by source_file_id so
# both the Git-sourced and upload-sourced runs produce the same change.
RAW_CLI_OUTPUT = {
    "parser_version": HCL_PARSER_VERSION,
    "detector_version": DETECTOR_VERSION,
    "patcher_version": PATCHER_VERSION,
    "change_set": {
        "source_file_id": SOURCE_PATH,
        "patcher_version": PATCHER_VERSION,
        "entries": [
            {
                "origin": {
                    "origin": "DETECTION",
                    "rule_id": "tf-s3-bucket-inline-acl-deprecated",
                    "source_file_id": SOURCE_PATH,
                    "span": {"start_byte": 33, "end_byte": 52, "start_line": 2, "end_line": 2},
                    "confidence": "HIGH",
                    "detector_version": DETECTOR_VERSION,
                    "message": "deprecated inline acl",
                },
                "outcome": "APPLIED",
                "edits": [
                    {
                        "span": {
                            "start_byte": 33,
                            "end_byte": 52,
                            "start_line": 2,
                            "end_line": 2,
                        },
                        "replacement": 'acl = "private"',
                    }
                ],
                "reason": None,
                "patcher_version": PATCHER_VERSION,
            }
        ],
    },
}

_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "CAIRN Test Fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "CAIRN Test Fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
}


def _git(*args: str, cwd: Path | None = None) -> None:
    result = subprocess.run(
        ["git", *args], cwd=cwd, env=_GIT_ENV, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def _make_local_git_repo(tmp_path: Path) -> str:
    """A real, local-only Git remote (never a live network remote) for
    the Git half of this round-trip comparison -- the same ``file://``
    technique ``test_source_git.py`` already uses."""
    repo_dir = tmp_path / "origin"
    repo_dir.mkdir()
    _git("init", "--initial-branch=main", str(repo_dir))
    (repo_dir / SOURCE_PATH).write_text(SOURCE_CONTENT, encoding="utf-8")
    _git("add", ".", cwd=repo_dir)
    _git("commit", "-m", "golden fixture", cwd=repo_dir)
    return f"file://{repo_dir}"


def _zip_bytes() -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(SOURCE_PATH, SOURCE_CONTENT)
    return buffer.getvalue()


def _authenticator() -> JwtAuthenticator:
    return JwtAuthenticator(
        OidcSettings(issuer=ISSUER, audience=AUDIENCE, algorithms=("HS256",), secret=SECRET)
    )


def _token(*, tenant_id: str = TENANT_A, subject: str = "user-1") -> str:
    issued = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": int(issued.timestamp()),
            "exp": int((issued + timedelta(minutes=5)).timestamp()),
            "tenant_id": tenant_id,
            "roles": ["ENGINEER"],
        },
        SECRET,
        algorithm="HS256",
    )


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token()}"}


def _client(archive_bytes: bytes) -> TestClient:
    transformation_port = FakeTransformationPort()
    # Registered by the file's content, not by any (source_file_id)
    # identity that could differ between the Git-sourced and the
    # upload-sourced fetch -- both reads yield a SourceFile with this
    # exact path and content, so one fixture registration serves both.
    transformation_port.register(
        SourceFile(path=SOURCE_PATH, content=SOURCE_CONTENT, language=SourceLanguage.TERRAFORM),
        RAW_CLI_OUTPUT,
    )
    app = create_app(
        authenticator=_authenticator(),
        assertion_secret=b"test-assertion-secret",
        # transformation_source_port deliberately NOT overridden here --
        # this test drives create_app's own default wiring (781/R4-02's
        # CompositeSourceAdapter), the exact thing this unit fixes.
        transformation_archive_loader=lambda archive_id: archive_bytes,
        transformation_port=transformation_port,
        transformation_run_repository=FakeTransformationRunRepository(),
    )
    return TestClient(app)


def _create_and_diff(client: TestClient, repository_ref: dict) -> dict:
    created = client.post(
        f"/v1/projects/{PROJECT_ID}/transformations",
        json={"repository_ref": repository_ref},
        headers=_auth(),
    )
    assert created.status_code == 200, created.text
    run_id = created.json()["run_id"]
    diff = client.get(f"/v1/transformations/{run_id}/diff", headers=_auth())
    assert diff.status_code == 200, diff.text
    return {"run_summary": created.json(), "diff": diff.json()}


def test_upload_sourced_diff_preview_round_trips_through_the_default_wiring(
    tmp_path: Path,
) -> None:
    """The acceptance proof: an uploaded-source diff preview, through
    this same route and ``create_app``'s real default wiring, matches a
    Git-sourced one byte for byte (run identity fields aside)."""
    git_url = _make_local_git_repo(tmp_path)
    archive_bytes = _zip_bytes()

    git_client = _client(archive_bytes)
    upload_client = _client(archive_bytes)

    git_result = _create_and_diff(
        git_client, {"kind": "GIT", "url": git_url, "ref": "main"}
    )
    upload_result = _create_and_diff(
        upload_client, {"kind": "UPLOAD", "archive_id": "archive-1"}
    )

    # Run identity (run_id, created_at) is expected to differ -- strip it
    # before comparing, same as any other "same shape, different run"
    # assertion in this suite.
    for result in (git_result, upload_result):
        result["run_summary"].pop("run_id")
        result["run_summary"].pop("created_at")
        result["diff"].pop("run_id")

    assert git_result == upload_result
    assert upload_result["run_summary"]["source_file_ids"] == [SOURCE_PATH]
    assert upload_result["run_summary"]["applied_count"] == 1
    file_diff = upload_result["diff"]["files"][0]
    assert file_diff["original_content"] == SOURCE_CONTENT
    assert 'acl = "private"' in file_diff["rendered_content"]
    assert "a/s3.tf" in file_diff["unified_diff"]
    assert "b/s3.tf" in file_diff["unified_diff"]


def test_upload_sourced_create_transformation_requires_engineer_or_above(
    tmp_path: Path,
) -> None:
    client = _client(_zip_bytes())
    issued = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "user-1",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": int(issued.timestamp()),
            "exp": int((issued + timedelta(minutes=5)).timestamp()),
            "tenant_id": TENANT_A,
            "roles": ["VIEWER"],
        },
        SECRET,
        algorithm="HS256",
    )
    response = client.post(
        f"/v1/projects/{PROJECT_ID}/transformations",
        json={"repository_ref": {"kind": "UPLOAD", "archive_id": "archive-1"}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
