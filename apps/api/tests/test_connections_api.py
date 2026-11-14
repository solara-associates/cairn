"""R1-02: provider connection create/validate/revoke HTTP routes.

Same authenticate-through-``AuthMiddleware`` discipline as
``test_projects_api.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cairn_adapters.auth_oidc import JwtAuthenticator, OidcSettings
from cairn_api import create_app
from fastapi.testclient import TestClient

SECRET = "test-secret-that-is-long-enough-for-hs256"
ISSUER = "https://issuer.example.test"
AUDIENCE = "cairn-api"
TENANT_A = "6f0f0f31-6d0c-4f25-9a45-1d0e1a0f1f6a"
TENANT_B = "1b1b1b1b-2c2c-4d4d-8e8e-3f3f3f3f3f3f"


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
            "roles": ["TENANT_ADMIN"],
        },
        SECRET,
        algorithm="HS256",
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client() -> TestClient:
    app = create_app(authenticator=_authenticator(), assertion_secret=b"test-assertion-secret")
    return TestClient(app)


def _create(client: TestClient, token: str) -> dict:
    response = client.post(
        "/v1/projects/project-1/connections",
        json={"provider": "gcp", "account_id": "gcp-acct-1", "secret": "super-secret-value"},
        headers=_auth(token),
    )
    assert response.status_code == 201
    return response.json()


def test_create_connection_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/v1/projects/project-1/connections",
        json={"provider": "gcp", "account_id": "gcp-acct-1", "secret": "x"},
    )
    assert response.status_code == 401


def test_create_connection_never_returns_the_secret(client: TestClient) -> None:
    body = _create(client, _token())
    assert "secret" not in body
    assert "super-secret-value" not in str(body)
    assert body["scope"] == "READ_ONLY"
    assert body["status"] == "ACTIVE"


def test_validate_connection_confirms_read_only_scope(client: TestClient) -> None:
    token = _token()
    created = _create(client, token)

    response = client.post(
        f"/v1/projects/project-1/connections/{created['connection_id']}/validate",
        headers=_auth(token),
    )
    assert response.status_code == 200
    assert response.json()["last_validated_at"] is not None


def test_revoke_connection_marks_it_revoked(client: TestClient) -> None:
    token = _token()
    created = _create(client, token)

    response = client.post(
        f"/v1/projects/project-1/connections/{created['connection_id']}/revoke",
        headers=_auth(token),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "REVOKED"
    assert response.json()["revoked_at"] is not None


def test_another_tenants_connection_is_not_found(client: TestClient) -> None:
    created = _create(client, _token(tenant_id=TENANT_A))

    response = client.get(
        f"/v1/projects/project-1/connections/{created['connection_id']}",
        headers=_auth(_token(tenant_id=TENANT_B)),
    )
    assert response.status_code == 404


def test_unknown_connection_is_not_found(client: TestClient) -> None:
    response = client.get(
        "/v1/projects/project-1/connections/does-not-exist", headers=_auth(_token())
    )
    assert response.status_code == 404
