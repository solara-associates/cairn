"""R2-09: the design-generation HTTP routes a console drives (pattern
select -> parameterize -> generate -> regenerate -> inspect caveats ->
export).

Unlike ``test_design_api.py`` (R2-08's pure-export tests, which seed a
``DesignRegistry`` directly with an already-generated design), this file
drives the *write* path this story adds: ``POST /v1/projects/{project_id}
/designs`` and ``POST /v1/designs/{design_id}/regenerate``, plus the new
read routes (``/v1/patterns``, ``/v1/designs/{design_id}/revisions``,
``/v1/designs/{design_id}/revisions/{revision_number}``,
``/v1/designs/{design_id}/iac``) and the extended ``/diagram`` shape --
all against the real ``create_app`` default pattern catalogue and
mapping release (``patterns/`` and ``mappings/service-map.yaml`` at the
repo root), the same fixtures a real console would see.
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
PROJECT_ID = "22222222-2222-2222-2222-222222222222"


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
            "roles": ["ARCHITECT"],
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


def _create_design_payload() -> dict:
    return {
        "pattern_id": "web-app",
        "target_provider": "gcp",
        "parameters": {"compute_platform": "cloud_run", "database_engine": "cloud_sql_postgres"},
        "resources": [
            {
                "resource_id": "res-exact",
                "provider": "aws",
                "service": "secrets-manager",
                "region": "europe-west2",
            },
            {
                "resource_id": "res-approximate",
                "provider": "aws",
                "service": "s3",
                "region": "europe-west2",
            },
            {
                "resource_id": "res-unavailable",
                "provider": "aws",
                "service": "secrets-manager",
                "region": "ap-southeast-1",
            },
            {
                "resource_id": "res-unresolved",
                "provider": "aws",
                "service": "no-such-service",
                "region": "europe-west2",
            },
        ],
        "workloads": [
            {
                "workload_id": "wl-1",
                "name": "checkout",
                "resource_ids": [
                    "res-exact",
                    "res-approximate",
                    "res-unavailable",
                    "res-unresolved",
                ],
            }
        ],
        "decisions": [{"workload_id": "wl-1", "disposition": "REHOST"}],
    }


def test_list_patterns_returns_the_seed_catalogue(client: TestClient) -> None:
    response = client.get("/v1/patterns", headers=_auth(_token()))
    assert response.status_code == 200
    body = response.json()
    ids = {pattern["id"] for pattern in body}
    assert "web-app" in ids
    web_app = next(p for p in body if p["id"] == "web-app")
    param_names = {p["name"] for p in web_app["parameters"]}
    assert {"compute_platform", "database_engine"}.issubset(param_names)


def test_create_design_generates_a_full_revision_one_design(client: TestClient) -> None:
    response = client.post(
        f"/v1/projects/{PROJECT_ID}/designs",
        json=_create_design_payload(),
        headers=_auth(_token()),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["revision_number"] == 1
    assert body["pattern_id"] == "web-app"
    assert body["wave_count"] == 1

    markers = {r["shape_id"]: r["marker"] for r in body["resources"]}
    assert markers["res-exact"] == "EXACT"
    assert markers["res-approximate"] == "APPROXIMATE"
    assert markers["res-unavailable"] == "UNAVAILABLE"
    assert markers["res-unresolved"] == "UNRESOLVED"
    # every non-EXACT marker carries a human-readable explanation -- never
    # a bare status code with no context (demo-readiness discipline: a
    # caveat a non-engineer can read, not a silent difference).
    for shape in body["resources"]:
        if shape["marker"] != "EXACT":
            assert shape["detail"]


def test_regenerate_design_creates_a_new_revision_and_keeps_the_old_one(
    client: TestClient,
) -> None:
    create = client.post(
        f"/v1/projects/{PROJECT_ID}/designs",
        json=_create_design_payload(),
        headers=_auth(_token()),
    )
    design_id = create.json()["design_id"]
    original_hash = create.json()["content_hash"]

    regenerate = client.post(
        f"/v1/designs/{design_id}/regenerate",
        json={"parameters": {"compute_platform": "gke", "database_engine": "alloydb"}},
        headers=_auth(_token()),
    )
    assert regenerate.status_code == 200
    body = regenerate.json()
    assert body["revision_number"] == 2
    assert body["content_hash"] != original_hash
    assert dict(body["parameters"])["compute_platform"] == "gke"

    revisions = client.get(f"/v1/designs/{design_id}/revisions", headers=_auth(_token()))
    assert revisions.status_code == 200
    numbers = [r["revision_number"] for r in revisions.json()]
    assert numbers == [1, 2]

    revision_1 = client.get(f"/v1/designs/{design_id}/revisions/1", headers=_auth(_token()))
    assert revision_1.status_code == 200
    assert dict(revision_1.json()["design"]["parameters"])["compute_platform"] == "cloud_run"

    revision_2 = client.get(f"/v1/designs/{design_id}/revisions/2", headers=_auth(_token()))
    assert revision_2.status_code == 200
    assert dict(revision_2.json()["design"]["parameters"])["compute_platform"] == "gke"
    # old and new revision are each independently comparable, and the
    # export route itself now serves the *latest* revision.
    export = client.get(f"/v1/designs/{design_id}", headers=_auth(_token()))
    assert export.json()["design"]["revision_number"] == 2
    # ``version_stamps_consistent`` is a ``@property`` on the domain
    # dataclass, not a field -- a plain ``jsonable_encoder`` drops it
    # silently, so this route must put it back on the wire explicitly.
    assert export.json()["version_stamps_consistent"] is True
    assert revision_1.json()["version_stamps_consistent"] is True
    assert revision_2.json()["version_stamps_consistent"] is True


def test_create_design_unknown_pattern_is_not_found(client: TestClient) -> None:
    payload = _create_design_payload()
    payload["pattern_id"] = "does-not-exist"
    response = client.post(
        f"/v1/projects/{PROJECT_ID}/designs", json=payload, headers=_auth(_token())
    )
    assert response.status_code == 404


def test_get_design_diagram_shapes_are_visibly_distinguished(client: TestClient) -> None:
    create = client.post(
        f"/v1/projects/{PROJECT_ID}/designs",
        json=_create_design_payload(),
        headers=_auth(_token()),
    )
    design_id = create.json()["design_id"]
    response = client.get(f"/v1/designs/{design_id}/diagram", headers=_auth(_token()))
    assert response.status_code == 200
    markers = {shape["shape_id"]: shape["marker"] for shape in response.json()["shapes"]}
    assert markers == {
        "res-exact": "EXACT",
        "res-approximate": "APPROXIMATE",
        "res-unavailable": "UNAVAILABLE",
        "res-unresolved": "UNRESOLVED",
    }


def test_get_design_iac_preview_has_a_plan_only_disclaimer_and_named_gaps(
    client: TestClient,
) -> None:
    create = client.post(
        f"/v1/projects/{PROJECT_ID}/designs",
        json=_create_design_payload(),
        headers=_auth(_token()),
    )
    design_id = create.json()["design_id"]
    response = client.get(f"/v1/designs/{design_id}/iac", headers=_auth(_token()))
    assert response.status_code == 200
    body = response.json()
    assert "PLAN ONLY" in body["disclaimer"]
    assert "not applied" in body["disclaimer"].lower()
    statuses = {r["resource_id"]: r["status"] for r in body["resources"]}
    assert statuses["res-unresolved"] == "GAP"
    assert statuses["res-unavailable"] == "GAP"
    assert "res-unresolved" in body["gap_resource_ids"]


# --- tenant isolation -------------------------------------------------------


def test_regenerate_another_tenant_design_is_not_found(client: TestClient) -> None:
    create = client.post(
        f"/v1/projects/{PROJECT_ID}/designs",
        json=_create_design_payload(),
        headers=_auth(_token()),
    )
    design_id = create.json()["design_id"]
    response = client.post(
        f"/v1/designs/{design_id}/regenerate",
        json={"parameters": {}},
        headers=_auth(_token(tenant_id=TENANT_B)),
    )
    assert response.status_code == 404


def test_design_revisions_another_tenant_is_not_found(client: TestClient) -> None:
    create = client.post(
        f"/v1/projects/{PROJECT_ID}/designs",
        json=_create_design_payload(),
        headers=_auth(_token()),
    )
    design_id = create.json()["design_id"]
    response = client.get(
        f"/v1/designs/{design_id}/revisions", headers=_auth(_token(tenant_id=TENANT_B))
    )
    assert response.status_code == 404


def test_design_iac_another_tenant_is_not_found(client: TestClient) -> None:
    create = client.post(
        f"/v1/projects/{PROJECT_ID}/designs",
        json=_create_design_payload(),
        headers=_auth(_token()),
    )
    design_id = create.json()["design_id"]
    response = client.get(
        f"/v1/designs/{design_id}/iac", headers=_auth(_token(tenant_id=TENANT_B))
    )
    assert response.status_code == 404
