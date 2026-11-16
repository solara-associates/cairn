"""R3-04: the unified diff artefact and preview API.

Drives ``POST /v1/projects/{project_id}/transformations``,
``GET /v1/transformations/{run_id}`` and
``GET /v1/transformations/{run_id}/diff`` against the real
``create_app``, with a ``FakeRepositorySource``/``FakeTransformationPort``
pair wired in (no real git clone, no real subprocess -- the same
discipline every other write route's own API test suite in this app
uses, e.g. ``test_design_generation_api.py``'s in-process fixtures).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cairn_adapters.auth_oidc import JwtAuthenticator, OidcSettings
from cairn_adapters.source_git.fake import FakeRepositorySource
from cairn_adapters.transform_core.fake import FakeTransformationPort
from cairn_api import create_app
from cairn_contracts.transformation import GitRepositoryRef, SourceFile, SourceLanguage
from cairn_modules.transformation.runs import FakeTransformationRunRepository
from fastapi.testclient import TestClient

SECRET = "test-secret-that-is-long-enough-for-hs256"
ISSUER = "https://issuer.example.test"
AUDIENCE = "cairn-api"
TENANT_A = "6f0f0f31-6d0c-4f25-9a45-1d0e1a0f1f6a"
TENANT_B = "1b1b1b1b-2c2c-4d4d-8e8e-3f3f3f3f3f3f"
PROJECT_ID = "22222222-2222-2222-2222-222222222222"

DETECTOR_VERSION = "cairn-detector/0.1.0"
PATCHER_VERSION = "cairn-transform-patcher/0.1.0"
HCL_PARSER_VERSION = "cairn-hcl-parser/0.1.0"

REF = GitRepositoryRef(url="https://example.test/repo.git", ref="main")

SOURCE_FILE = SourceFile(
    path="s3.tf",
    content='resource "aws_s3_bucket" "b" {\n  acl = "public-read"\n}\n',
    language=SourceLanguage.TERRAFORM,
)

# The exact raw CliOutput shape 726's fake/real adapters both read,
# matching packages/modules/tests/test_transformation_engine.py's own
# fixtures: one APPLIED entry rewriting the deprecated inline ACL.
RAW_CLI_OUTPUT = {
    "parser_version": HCL_PARSER_VERSION,
    "detector_version": DETECTOR_VERSION,
    "patcher_version": PATCHER_VERSION,
    "change_set": {
        "source_file_id": "s3.tf",
        "patcher_version": PATCHER_VERSION,
        "entries": [
            {
                "origin": {
                    "origin": "DETECTION",
                    "rule_id": "tf-s3-bucket-inline-acl-deprecated",
                    "source_file_id": "s3.tf",
                    "span": {
                        "start_byte": 33,
                        "end_byte": 52,
                        "start_line": 2,
                        "end_line": 2,
                    },
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
            },
            {
                "origin": {
                    "origin": "SKIPPED_CANDIDATE",
                    "rule_id": "tf-s3-bucket-inline-acl-deprecated",
                    "source_file_id": "s3.tf",
                    "span": {
                        "start_byte": 0,
                        "end_byte": 0,
                        "start_line": 1,
                        "end_line": 1,
                    },
                    "detector_version": DETECTOR_VERSION,
                    "reason": "candidate is inside a dynamic block",
                },
                "outcome": "SKIPPED",
                "edits": [],
                "reason": "candidate is inside a dynamic block",
                "patcher_version": PATCHER_VERSION,
            },
        ],
    },
}


def _authenticator() -> JwtAuthenticator:
    return JwtAuthenticator(
        OidcSettings(issuer=ISSUER, audience=AUDIENCE, algorithms=("HS256",), secret=SECRET)
    )


def _token(*, tenant_id: str = TENANT_A, subject: str = "user-1", roles: list[str] | None = None) -> str:
    issued = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": int(issued.timestamp()),
            "exp": int((issued + timedelta(minutes=5)).timestamp()),
            "tenant_id": tenant_id,
            "roles": roles if roles is not None else ["ENGINEER"],
        },
        SECRET,
        algorithm="HS256",
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def source_port() -> FakeRepositorySource:
    port = FakeRepositorySource()
    port.register(REF, [SOURCE_FILE])
    return port


@pytest.fixture
def transformation_port() -> FakeTransformationPort:
    port = FakeTransformationPort()
    port.register(SOURCE_FILE, RAW_CLI_OUTPUT)
    return port


@pytest.fixture
def client(
    source_port: FakeRepositorySource, transformation_port: FakeTransformationPort
) -> TestClient:
    app = create_app(
        authenticator=_authenticator(),
        assertion_secret=b"test-assertion-secret",
        transformation_source_port=source_port,
        transformation_port=transformation_port,
        transformation_run_repository=FakeTransformationRunRepository(),
    )
    return TestClient(app)


def _create_transformation(client: TestClient, *, roles: list[str] | None = None) -> dict:
    response = client.post(
        f"/v1/projects/{PROJECT_ID}/transformations",
        json={"repository_ref": {"kind": "GIT", "url": REF.url, "ref": REF.ref}},
        headers=_auth(_token(roles=roles)),
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_create_transformation_scans_and_produces_a_run_summary(
    client: TestClient, source_port: FakeRepositorySource
) -> None:
    body = _create_transformation(client)
    assert body["project_id"] == PROJECT_ID
    assert body["run_number"] == 1
    assert body["source_file_ids"] == ["s3.tf"]
    assert body["applied_count"] == 1
    assert body["skipped_count"] == 1
    assert body["unsupported_count"] == 0
    # 721's source port was actually invoked with this project's ref --
    # proof the route drives the fetch, not a shortcut around it.
    assert source_port.fetches == [REF]


def test_create_transformation_requires_engineer_or_above(client: TestClient) -> None:
    response = client.post(
        f"/v1/projects/{PROJECT_ID}/transformations",
        json={"repository_ref": {"kind": "GIT", "url": REF.url, "ref": REF.ref}},
        headers=_auth(_token(roles=["VIEWER"])),
    )
    assert response.status_code == 403


def test_get_transformation_returns_the_recorded_run(client: TestClient) -> None:
    created = _create_transformation(client)
    response = client.get(
        f"/v1/transformations/{created['run_id']}", headers=_auth(_token())
    )
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == created["run_id"]
    assert body["run_number"] == 1
    assert body["applied_count"] == 1


def test_get_transformation_another_tenant_is_not_found(client: TestClient) -> None:
    created = _create_transformation(client)
    response = client.get(
        f"/v1/transformations/{created['run_id']}",
        headers=_auth(_token(tenant_id=TENANT_B)),
    )
    assert response.status_code == 404


def test_get_transformation_unknown_run_is_not_found(client: TestClient) -> None:
    response = client.get("/v1/transformations/does-not-exist", headers=_auth(_token()))
    assert response.status_code == 404


def test_get_transformation_diff_renders_unified_diff_and_structured_entries(
    client: TestClient,
) -> None:
    created = _create_transformation(client)
    response = client.get(
        f"/v1/transformations/{created['run_id']}/diff", headers=_auth(_token())
    )
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == created["run_id"]
    assert body["source_file_ids"] == ["s3.tf"]
    assert body["applied_count"] == 1
    assert body["skipped_count"] == 1
    assert len(body["files"]) == 1
    file_diff = body["files"][0]
    assert file_diff["source_file_id"] == "s3.tf"
    assert file_diff["changed"] is True
    assert file_diff["original_content"] == SOURCE_FILE.content
    assert 'acl = "private"' in file_diff["rendered_content"]
    assert 'acl = "public-read"' not in file_diff["rendered_content"]
    assert "-  acl = \"public-read\"" in file_diff["unified_diff"]
    assert "+  acl = \"private\"" in file_diff["unified_diff"]
    assert "a/s3.tf" in file_diff["unified_diff"]
    assert "b/s3.tf" in file_diff["unified_diff"]
    outcomes = {entry["rule_id"]: entry["outcome"] for entry in file_diff["entries"]}
    assert outcomes["tf-s3-bucket-inline-acl-deprecated"] in {"APPLIED", "SKIPPED"}
    assert len(file_diff["entries"]) == 2
    # The original SourceFile content given to the port is never mutated.
    assert SOURCE_FILE.content == 'resource "aws_s3_bucket" "b" {\n  acl = "public-read"\n}\n'


def test_get_transformation_diff_another_tenant_is_not_found(client: TestClient) -> None:
    created = _create_transformation(client)
    response = client.get(
        f"/v1/transformations/{created['run_id']}/diff",
        headers=_auth(_token(tenant_id=TENANT_B)),
    )
    assert response.status_code == 404


def test_get_transformation_diff_requires_viewer_or_above_authentication(
    client: TestClient,
) -> None:
    created = _create_transformation(client)
    response = client.get(f"/v1/transformations/{created['run_id']}/diff")
    assert response.status_code == 401
