"""R3-07: ``POST``/``GET /v1/transformations/{run_id}/review-comments``.

Drives the new routes against the real ``create_app``, with the same
``FakeRepositorySource``/``FakeTransformationPort`` discipline
``test_transformations_validate_api.py`` already uses for 728/729's
routes -- no real subprocess, no real validator binary.
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
def client(source_port: FakeRepositorySource, transformation_port: FakeTransformationPort) -> TestClient:
    app = create_app(
        authenticator=_authenticator(),
        assertion_secret=b"test-assertion-secret",
        transformation_source_port=source_port,
        transformation_port=transformation_port,
        transformation_run_repository=FakeTransformationRunRepository(),
        transformation_validation_checks=(),
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


def test_a_plain_comment_is_recorded_and_never_blocks(client: TestClient) -> None:
    created = _create_transformation(client)

    response = client.post(
        f"/v1/transformations/{created['run_id']}/review-comments",
        json={"decision": "COMMENT", "body": "nit: rename the bucket"},
        headers=_auth(_token()),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["blocked"] is False
    assert body["reviewed"] is False
    assert len(body["comments"]) == 1
    assert body["comments"][0]["body"] == "nit: rename the bucket"
    assert body["comments"][0]["decision"] == "COMMENT"
    assert body["comments"][0]["reviewer_actor_id"] == "user-1"


def test_request_changes_visibly_blocks_further_progress(client: TestClient) -> None:
    created = _create_transformation(client)

    response = client.post(
        f"/v1/transformations/{created['run_id']}/review-comments",
        json={"decision": "REQUEST_CHANGES", "body": "this breaks the dependency check"},
        headers=_auth(_token()),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["blocked"] is True
    assert body["reviewed"] is True


def test_approve_after_request_changes_clears_the_block(client: TestClient) -> None:
    created = _create_transformation(client)
    client.post(
        f"/v1/transformations/{created['run_id']}/review-comments",
        json={"decision": "REQUEST_CHANGES", "body": "fix this"},
        headers=_auth(_token()),
    )

    response = client.post(
        f"/v1/transformations/{created['run_id']}/review-comments",
        json={"decision": "APPROVE", "body": "looks good now"},
        headers=_auth(_token()),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["blocked"] is False
    assert [c["decision"] for c in body["comments"]] == ["REQUEST_CHANGES", "APPROVE"]


def test_get_review_comments_reflects_what_was_posted(client: TestClient) -> None:
    created = _create_transformation(client)
    client.post(
        f"/v1/transformations/{created['run_id']}/review-comments",
        json={"decision": "COMMENT", "body": "first pass looks fine"},
        headers=_auth(_token()),
    )

    response = client.get(
        f"/v1/transformations/{created['run_id']}/review-comments", headers=_auth(_token())
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["comments"]) == 1
    assert body["comments"][0]["body"] == "first pass looks fine"


def test_get_review_comments_before_any_review_is_an_empty_unblocked_thread(
    client: TestClient,
) -> None:
    created = _create_transformation(client)

    response = client.get(
        f"/v1/transformations/{created['run_id']}/review-comments", headers=_auth(_token())
    )

    assert response.status_code == 200
    body = response.json()
    assert body["comments"] == []
    assert body["blocked"] is False
    assert body["reviewed"] is False


def test_get_transformation_reflects_the_review_thread(client: TestClient) -> None:
    created = _create_transformation(client)
    client.post(
        f"/v1/transformations/{created['run_id']}/review-comments",
        json={"decision": "REQUEST_CHANGES", "body": "please fix"},
        headers=_auth(_token()),
    )

    response = client.get(f"/v1/transformations/{created['run_id']}", headers=_auth(_token()))

    assert response.status_code == 200
    assert response.json()["review"]["blocked"] is True


def test_posting_a_review_comment_requires_engineer_reviewer_or_above(client: TestClient) -> None:
    created = _create_transformation(client)

    response = client.post(
        f"/v1/transformations/{created['run_id']}/review-comments",
        json={"decision": "COMMENT", "body": "hello"},
        headers=_auth(_token(roles=["VIEWER"])),
    )

    assert response.status_code == 403


def test_a_reviewer_role_can_request_changes(client: TestClient) -> None:
    """Spec §12.1's own REVIEWER capability row ("Approve/reject, accept
    exceptions") is this exact action -- confirmed live, not just
    documented in the module's own docstring."""

    created = _create_transformation(client)

    response = client.post(
        f"/v1/transformations/{created['run_id']}/review-comments",
        json={"decision": "REQUEST_CHANGES", "body": "no"},
        headers=_auth(_token(roles=["REVIEWER"])),
    )

    assert response.status_code == 200, response.text
    assert response.json()["blocked"] is True


def test_review_comments_for_another_tenant_run_are_not_found(client: TestClient) -> None:
    created = _create_transformation(client)

    response = client.post(
        f"/v1/transformations/{created['run_id']}/review-comments",
        json={"decision": "COMMENT", "body": "hello"},
        headers=_auth(_token(tenant_id=TENANT_B)),
    )

    assert response.status_code == 404


def test_review_comments_for_an_unknown_run_are_not_found(client: TestClient) -> None:
    response = client.post(
        "/v1/transformations/does-not-exist/review-comments",
        json={"decision": "COMMENT", "body": "hello"},
        headers=_auth(_token()),
    )
    assert response.status_code == 404


def test_an_empty_body_is_rejected(client: TestClient) -> None:
    created = _create_transformation(client)

    response = client.post(
        f"/v1/transformations/{created['run_id']}/review-comments",
        json={"decision": "COMMENT", "body": "   "},
        headers=_auth(_token()),
    )

    assert response.status_code == 422
