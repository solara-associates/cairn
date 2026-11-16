"""R3-07: ``POST /v1/transformations/{run_id}/evidence-package``.

Seals 730's ``build_transformation_evidence_package`` for a recorded run
through the real ``create_app`` -- same discipline
``test_transformations_validate_api.py``/``test_transformations_review_
api.py`` already use (``FakeRepositorySource``/``FakeTransformationPort``,
no real subprocess), plus ``cairn_kernel.testing.FakeEvidenceSigner`` so
no real KMS call is made.
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
from cairn_kernel.testing import FakeEvidenceSigner
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
def signer() -> FakeEvidenceSigner:
    return FakeEvidenceSigner()


@pytest.fixture
def client(
    source_port: FakeRepositorySource,
    transformation_port: FakeTransformationPort,
    static_check: FakeStaticValidationAdapter,
    signer: FakeEvidenceSigner,
) -> TestClient:
    app = create_app(
        authenticator=_authenticator(),
        assertion_secret=b"test-assertion-secret",
        evidence_signer=signer,
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


def test_evidence_package_seals_an_envelope_referencing_the_manifest_and_diff(
    client: TestClient,
) -> None:
    created = _create_transformation(client)

    response = client.post(
        f"/v1/transformations/{created['run_id']}/evidence-package", headers=_auth(_token())
    )

    assert response.status_code == 200, response.text
    body = response.json()
    envelope = body["envelope"]
    assert envelope["payload_hash"]
    assert envelope["previous_hash"] is None
    assert envelope["signature"]["key_id"]
    output_kinds = {output["kind"] for output in envelope["outputs"]}
    assert "transformation_manifest" in output_kinds
    assert "transformation_diff" in output_kinds
    assert body["report"]["run_id"] == created["run_id"]


def test_evidence_package_outcome_reflects_validation(
    client: TestClient, static_check: FakeStaticValidationAdapter
) -> None:
    created = _create_transformation(client)
    static_check.register(
        created["run_id"],
        (ValidationResult(check_id="static-reparse", passed=False, reason="nope"),),
    )
    client.post(f"/v1/transformations/{created['run_id']}:validate", headers=_auth(_token()))

    response = client.post(
        f"/v1/transformations/{created['run_id']}/evidence-package", headers=_auth(_token())
    )

    assert response.status_code == 200, response.text
    assert response.json()["envelope"]["outcome"] == "FAIL"


def test_evidence_package_chains_to_the_previous_package_for_the_same_project(
    client: TestClient,
) -> None:
    created = _create_transformation(client)

    first = client.post(
        f"/v1/transformations/{created['run_id']}/evidence-package", headers=_auth(_token())
    ).json()

    second_run = _create_transformation(client)
    second = client.post(
        f"/v1/transformations/{second_run['run_id']}/evidence-package", headers=_auth(_token())
    ).json()

    assert second["envelope"]["previous_hash"] == first["envelope"]["payload_hash"]


def test_evidence_package_signer_is_the_apps_own_configured_signer(
    client: TestClient, signer: FakeEvidenceSigner
) -> None:
    """Confirms the route uses whichever ``EvidenceSigner`` the caller's
    composition root wires in (here, the test's own
    ``FakeEvidenceSigner`` fixture), never constructing one of its own
    -- independent verification of the envelope this exact signer
    produces is already proven once, at the module level, by 730's own
    ``test_package_verifies_independently_offline``; this route is a
    thin wire-up over that already-proven machinery, not a second place
    reimplementing it."""

    created = _create_transformation(client)

    response = client.post(
        f"/v1/transformations/{created['run_id']}/evidence-package", headers=_auth(_token())
    )

    assert response.status_code == 200, response.text
    envelope = response.json()["envelope"]
    assert envelope["signature"]["key_id"] == signer.key_id
    assert envelope["signature"]["algorithm"] == signer.algorithm


def test_evidence_package_requires_engineer_or_above(client: TestClient) -> None:
    created = _create_transformation(client)

    response = client.post(
        f"/v1/transformations/{created['run_id']}/evidence-package",
        headers=_auth(_token(roles=["VIEWER"])),
    )

    assert response.status_code == 403


def test_evidence_package_for_another_tenant_run_is_not_found(client: TestClient) -> None:
    created = _create_transformation(client)

    response = client.post(
        f"/v1/transformations/{created['run_id']}/evidence-package",
        headers=_auth(_token(tenant_id=TENANT_B)),
    )

    assert response.status_code == 404


def test_evidence_package_for_an_unknown_run_is_not_found(client: TestClient) -> None:
    response = client.post(
        "/v1/transformations/does-not-exist/evidence-package", headers=_auth(_token())
    )
    assert response.status_code == 404
