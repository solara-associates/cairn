"""R1-15: assessment-run async operation API -- HTTP layer.

Authenticates real requests through ``AuthMiddleware`` end to end
through ``create_app()``, same as ``test_projects_api.py``.
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


def test_queue_assessment_run_requires_authentication(client: TestClient) -> None:
    response = client.post("/v1/projects/project-1/assessment-runs", json={})
    assert response.status_code == 401


def test_queue_then_poll_an_assessment_run_to_completion(client: TestClient) -> None:
    token = _token()

    queued = client.post(
        "/v1/projects/project-1/assessment-runs", json={"files": []}, headers=_auth(token)
    )
    assert queued.status_code == 202
    run_id = queued.json()["run_id"]

    # BackgroundTasks run to completion before TestClient.post() returns
    # control, so the run is already COMPLETED by the time we poll it.
    polled = client.get(
        f"/v1/projects/project-1/assessment-runs/{run_id}", headers=_auth(token)
    )
    assert polled.status_code == 200
    body = polled.json()
    assert body["run_id"] == run_id
    assert body["state"] == "COMPLETED"
    assert body["coverage"] == 1.0
    assert body["failures"] == []


def test_a_different_tenants_run_is_not_found() -> None:
    app = create_app(authenticator=_authenticator(), assertion_secret=b"test-assertion-secret")
    client = TestClient(app)

    queued = client.post(
        "/v1/projects/project-1/assessment-runs",
        json={"files": []},
        headers=_auth(_token(tenant_id=TENANT_A)),
    )
    run_id = queued.json()["run_id"]

    response = client.get(
        f"/v1/projects/project-1/assessment-runs/{run_id}",
        headers=_auth(_token(tenant_id=TENANT_B)),
    )
    assert response.status_code == 404


def test_unknown_run_id_is_not_found(client: TestClient) -> None:
    token = _token()
    response = client.get(
        "/v1/projects/project-1/assessment-runs/does-not-exist", headers=_auth(token)
    )
    assert response.status_code == 404
