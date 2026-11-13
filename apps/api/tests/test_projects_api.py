"""R1-01: project, membership and settings APIs — HTTP layer.

These tests authenticate real requests through ``AuthMiddleware`` (the same
JWT path proven in ``test_auth_middleware.py``) end to end through
``create_app()``, so RBAC and cross-tenant denial are proven exactly as a
client would see them, not just at the service layer
(``packages/modules/tests/test_projects.py`` covers that layer).
"""

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


def _token(*, roles: list[str], tenant_id: str = TENANT_A, subject: str = "user-1") -> str:
    issued = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": int(issued.timestamp()),
            "exp": int((issued + timedelta(minutes=5)).timestamp()),
            "tenant_id": tenant_id,
            "roles": roles,
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


# --- unauthenticated ----------------------------------------------------------


def test_create_project_requires_authentication(client: TestClient) -> None:
    response = client.post("/v1/projects", json={"name": "Migration Alpha"})
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


# --- create: happy path, RBAC denial, validation -------------------------------


def test_tenant_admin_can_create_a_project(client: TestClient) -> None:
    token = _token(roles=["TENANT_ADMIN"])
    response = client.post(
        "/v1/projects",
        json={"name": "Migration Alpha", "customer_name": "Acme"},
        headers=_auth(token),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Migration Alpha"
    assert body["tenant_id"] == TENANT_A
    assert body["project_id"]


def test_viewer_cannot_create_a_project(client: TestClient) -> None:
    token = _token(roles=["VIEWER"])
    response = client.post("/v1/projects", json={"name": "Migration Alpha"}, headers=_auth(token))
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_create_project_rejects_a_blank_name(client: TestClient) -> None:
    token = _token(roles=["TENANT_ADMIN"])
    response = client.post("/v1/projects", json={"name": "   "}, headers=_auth(token))
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"


# --- read / update / list ------------------------------------------------------


def _create_project(client: TestClient, *, tenant_id: str = TENANT_A) -> dict:
    token = _token(roles=["TENANT_ADMIN"], tenant_id=tenant_id)
    response = client.post(
        "/v1/projects", json={"name": "Migration Alpha"}, headers=_auth(token)
    )
    assert response.status_code == 201
    return response.json()


def test_get_and_list_projects(client: TestClient) -> None:
    project = _create_project(client)
    token = _token(roles=["VIEWER"])

    get_response = client.get(f"/v1/projects/{project['project_id']}", headers=_auth(token))
    assert get_response.status_code == 200
    assert get_response.json()["project_id"] == project["project_id"]

    list_response = client.get("/v1/projects", headers=_auth(token))
    assert list_response.status_code == 200
    assert [p["project_id"] for p in list_response.json()] == [project["project_id"]]


def test_get_unknown_project_is_404(client: TestClient) -> None:
    token = _token(roles=["VIEWER"])
    response = client.get("/v1/projects/does-not-exist", headers=_auth(token))
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_project_owner_can_update_a_project(client: TestClient) -> None:
    project = _create_project(client)
    token = _token(roles=["PROJECT_OWNER"])
    response = client.patch(
        f"/v1/projects/{project['project_id']}",
        json={"name": "Migration Beta"},
        headers=_auth(token),
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Migration Beta"


def test_viewer_cannot_update_a_project(client: TestClient) -> None:
    project = _create_project(client)
    token = _token(roles=["VIEWER"])
    response = client.patch(
        f"/v1/projects/{project['project_id']}",
        json={"name": "Migration Beta"},
        headers=_auth(token),
    )
    assert response.status_code == 403


# --- cross-tenant adversarial tests --------------------------------------------


def test_cross_tenant_get_is_denied(client: TestClient) -> None:
    project = _create_project(client, tenant_id=TENANT_A)
    intruder_token = _token(roles=["TENANT_ADMIN"], tenant_id=TENANT_B)
    response = client.get(
        f"/v1/projects/{project['project_id']}", headers=_auth(intruder_token)
    )
    assert response.status_code == 403
    assert response.json()["code"] == "TENANT_SCOPE_VIOLATION"


def test_cross_tenant_update_is_denied(client: TestClient) -> None:
    project = _create_project(client, tenant_id=TENANT_A)
    intruder_token = _token(roles=["TENANT_ADMIN"], tenant_id=TENANT_B)
    response = client.patch(
        f"/v1/projects/{project['project_id']}",
        json={"name": "Hijacked"},
        headers=_auth(intruder_token),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "TENANT_SCOPE_VIOLATION"


def test_cross_tenant_members_are_isolated(client: TestClient) -> None:
    project = _create_project(client, tenant_id=TENANT_A)
    owner_token = _token(roles=["PROJECT_OWNER"], tenant_id=TENANT_A)
    client.post(
        f"/v1/projects/{project['project_id']}/members",
        json={"user_id": "alice", "role": "ENGINEER"},
        headers=_auth(owner_token),
    )

    intruder_token = _token(roles=["TENANT_ADMIN"], tenant_id=TENANT_B)
    response = client.get(
        f"/v1/projects/{project['project_id']}/members", headers=_auth(intruder_token)
    )
    assert response.status_code == 403
    assert response.json()["code"] == "TENANT_SCOPE_VIOLATION"


def test_cross_tenant_list_projects_does_not_leak(client: TestClient) -> None:
    _create_project(client, tenant_id=TENANT_A)
    other_token = _token(roles=["TENANT_ADMIN"], tenant_id=TENANT_B)
    response = client.get("/v1/projects", headers=_auth(other_token))
    assert response.status_code == 200
    assert response.json() == []


# --- membership -----------------------------------------------------------------


def test_project_owner_can_add_list_and_remove_a_member(client: TestClient) -> None:
    project = _create_project(client)
    owner_token = _token(roles=["PROJECT_OWNER"])

    add_response = client.post(
        f"/v1/projects/{project['project_id']}/members",
        json={"user_id": "alice", "role": "ENGINEER"},
        headers=_auth(owner_token),
    )
    assert add_response.status_code == 201
    assert add_response.json()["role"] == "ENGINEER"

    list_response = client.get(
        f"/v1/projects/{project['project_id']}/members", headers=_auth(owner_token)
    )
    assert [m["user_id"] for m in list_response.json()] == ["alice"]

    remove_response = client.delete(
        f"/v1/projects/{project['project_id']}/members/alice", headers=_auth(owner_token)
    )
    assert remove_response.status_code == 204

    list_after = client.get(
        f"/v1/projects/{project['project_id']}/members", headers=_auth(owner_token)
    )
    assert list_after.json() == []


def test_viewer_cannot_add_a_member(client: TestClient) -> None:
    project = _create_project(client)
    token = _token(roles=["VIEWER"])
    response = client.post(
        f"/v1/projects/{project['project_id']}/members",
        json={"user_id": "alice", "role": "ENGINEER"},
        headers=_auth(token),
    )
    assert response.status_code == 403


def test_removing_an_unknown_member_is_404(client: TestClient) -> None:
    project = _create_project(client)
    owner_token = _token(roles=["PROJECT_OWNER"])
    response = client.delete(
        f"/v1/projects/{project['project_id']}/members/ghost", headers=_auth(owner_token)
    )
    assert response.status_code == 404


# --- settings ---------------------------------------------------------------------


def test_default_settings_are_empty(client: TestClient) -> None:
    project = _create_project(client)
    token = _token(roles=["VIEWER"])
    response = client.get(
        f"/v1/projects/{project['project_id']}/settings", headers=_auth(token)
    )
    assert response.status_code == 200
    assert response.json()["values"] == {}


def test_project_owner_can_set_and_read_settings(client: TestClient) -> None:
    project = _create_project(client)
    owner_token = _token(roles=["PROJECT_OWNER"])
    put_response = client.put(
        f"/v1/projects/{project['project_id']}/settings",
        json={"notify": True, "region": "us"},
        headers=_auth(owner_token),
    )
    assert put_response.status_code == 200
    assert put_response.json()["values"] == {"notify": True, "region": "us"}

    get_response = client.get(
        f"/v1/projects/{project['project_id']}/settings", headers=_auth(owner_token)
    )
    assert get_response.json()["values"] == {"notify": True, "region": "us"}


def test_viewer_cannot_set_settings(client: TestClient) -> None:
    project = _create_project(client)
    token = _token(roles=["VIEWER"])
    response = client.put(
        f"/v1/projects/{project['project_id']}/settings",
        json={"notify": True},
        headers=_auth(token),
    )
    assert response.status_code == 403


def test_cross_tenant_settings_are_isolated(client: TestClient) -> None:
    project = _create_project(client, tenant_id=TENANT_A)
    intruder_token = _token(roles=["TENANT_ADMIN"], tenant_id=TENANT_B)
    response = client.get(
        f"/v1/projects/{project['project_id']}/settings", headers=_auth(intruder_token)
    )
    assert response.status_code == 403
    assert response.json()["code"] == "TENANT_SCOPE_VIOLATION"
