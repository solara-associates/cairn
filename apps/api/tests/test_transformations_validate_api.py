"""R3-05: ``POST /v1/transformations/{run_id}:validate``.

Drives the new route against the real ``create_app``, with a
``FakeRepositorySource``/``FakeTransformationPort`` pair (same discipline
``test_transformations_api.py`` already uses for 728's routes) plus a
single stub ``ValidationPort`` check wired in via ``create_app``'s new
``transformation_validation_checks`` parameter -- no real subprocess, no
real validator binary.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cairn_adapters.auth_oidc import JwtAuthenticator, OidcSettings
from cairn_adapters.source_git.fake import FakeRepositorySource
from cairn_adapters.transform_core.fake import FakeTransformationPort
from cairn_adapters.validation_static.fake import FakeStaticValidationAdapter
from cairn_api import create_app
from cairn_contracts.transformation import GitRepositoryRef, SourceFile, SourceLanguage
from cairn_modules.transformation.runs import FakeTransformationRunRepository
from cairn_modules.transformation.validation import ValidationResult
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
                    "span": {"start_byte": 33, "end_byte": 52, "start_line": 2, "end_line": 2},
                    "confidence": "HIGH",
                    "detector_version": DETECTOR_VERSION,
                    "message": "deprecated inline acl",
                },
                "outcome": "APPLIED",
                "edits": [
                    {
                        "span": {"start_byte": 33, "end_byte": 52, "start_line": 2, "end_line": 2},
                        "replacement": 'acl = "private"',
                    }
                ],
                "reason": None,
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
def static_check() -> FakeStaticValidationAdapter:
    return FakeStaticValidationAdapter()


@pytest.fixture
def client(
    source_port: FakeRepositorySource,
    transformation_port: FakeTransformationPort,
    static_check: FakeStaticValidationAdapter,
) -> TestClient:
    app = create_app(
        authenticator=_authenticator(),
        assertion_secret=b"test-assertion-secret",
        transformation_source_port=source_port,
        transformation_port=transformation_port,
        transformation_run_repository=FakeTransformationRunRepository(),
        transformation_validation_checks=(static_check,),
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


def test_validate_transformation_reports_a_passing_check_as_approved(
    client: TestClient, static_check: FakeStaticValidationAdapter
) -> None:
    created = _create_transformation(client)
    static_check.register(
        created["run_id"], (ValidationResult(check_id="s3.tf:static-reparse", passed=True),)
    )

    response = client.post(
        f"/v1/transformations/{created['run_id']}:validate", headers=_auth(_token())
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run_id"] == created["run_id"]
    assert body["approved"] is True
    assert body["results"] == [
        {"check_id": "s3.tf:static-reparse", "passed": True, "reason": None}
    ]


def test_validate_transformation_reports_a_failing_check_as_not_approved(
    client: TestClient, static_check: FakeStaticValidationAdapter
) -> None:
    created = _create_transformation(client)
    static_check.register(
        created["run_id"],
        (ValidationResult(check_id="tests", passed=False, reason="pytest exited 1"),),
    )

    response = client.post(
        f"/v1/transformations/{created['run_id']}:validate", headers=_auth(_token())
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["approved"] is False
    assert body["results"][0]["reason"] == "pytest exited 1"


def test_validate_transformation_requires_engineer_or_above(
    client: TestClient, static_check: FakeStaticValidationAdapter
) -> None:
    created = _create_transformation(client)
    static_check.register(created["run_id"], ())

    response = client.post(
        f"/v1/transformations/{created['run_id']}:validate",
        headers=_auth(_token(roles=["VIEWER"])),
    )

    assert response.status_code == 403


def test_validate_transformation_another_tenant_is_not_found(
    client: TestClient, static_check: FakeStaticValidationAdapter
) -> None:
    created = _create_transformation(client)
    static_check.register(created["run_id"], ())

    response = client.post(
        f"/v1/transformations/{created['run_id']}:validate",
        headers=_auth(_token(tenant_id=TENANT_B)),
    )

    assert response.status_code == 404


def test_validate_transformation_unknown_run_is_not_found(client: TestClient) -> None:
    response = client.post(
        "/v1/transformations/does-not-exist:validate", headers=_auth(_token())
    )
    assert response.status_code == 404


def test_get_transformation_before_validation_has_no_validation_recorded(
    client: TestClient,
) -> None:
    created = _create_transformation(client)
    response = client.get(f"/v1/transformations/{created['run_id']}", headers=_auth(_token()))
    assert response.json()["validation"] is None


def test_get_transformation_after_validation_reflects_the_recorded_outcome(
    client: TestClient, static_check: FakeStaticValidationAdapter
) -> None:
    created = _create_transformation(client)
    static_check.register(
        created["run_id"],
        (ValidationResult(check_id="static-reparse", passed=False, reason="nope"),),
    )
    client.post(f"/v1/transformations/{created['run_id']}:validate", headers=_auth(_token()))

    response = client.get(f"/v1/transformations/{created['run_id']}", headers=_auth(_token()))

    assert response.status_code == 200
    body = response.json()
    assert body["validation"]["approved"] is False
    assert body["validation"]["results"][0]["reason"] == "nope"
