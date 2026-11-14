"""R1-18 console wiring: assessment-run results, report, 6R review and
evidence-package HTTP routes, beyond R1-15's own queue/poll routes.

Same authenticate-through-``AuthMiddleware`` discipline as
``test_assessment_api.py``: every request is a real JWT, not a bypassed
``principal`` fixture.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

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

REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_CSV = (REPO_ROOT / "tests" / "fixtures" / "ingestion" / "golden.csv").read_text()


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


def _completed_run(client: TestClient, token: str) -> str:
    queued = client.post(
        "/v1/projects/project-1/assessment-runs",
        json={"files": [{"source_format": "csv", "content": GOLDEN_CSV}]},
        headers=_auth(token),
    )
    assert queued.status_code == 202
    return queued.json()["run_id"]


def test_results_exposes_every_stage_artifact(client: TestClient) -> None:
    token = _token()
    run_id = _completed_run(client, token)

    response = client.get(
        f"/v1/projects/project-1/assessment-runs/{run_id}/results", headers=_auth(token)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run_id
    assert len(body["workloads"]) >= 1
    assert body["posture_assessment"] is not None
    assert body["cost_baseline"] is not None
    assert body["tco_result"] is not None
    assert len(body["disposition_decisions"]) == len(body["workloads"])


def test_results_for_another_tenants_run_is_not_found(client: TestClient) -> None:
    run_id = _completed_run(client, _token(tenant_id=TENANT_A))
    response = client.get(
        f"/v1/projects/project-1/assessment-runs/{run_id}/results",
        headers=_auth(_token(tenant_id=TENANT_B)),
    )
    assert response.status_code == 404


def test_report_renders_coverage_and_versions(client: TestClient) -> None:
    token = _token()
    run_id = _completed_run(client, token)

    response = client.get(
        f"/v1/projects/project-1/assessment-runs/{run_id}/report", headers=_auth(token)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run_id
    assert body["run_coverage"]["state"] == "COMPLETED"
    assert "Evidence package hash: PENDING" in body["rendered_text"]


def _first_decision_id(client: TestClient, run_id: str, token: str) -> str:
    results = client.get(
        f"/v1/projects/project-1/assessment-runs/{run_id}/results", headers=_auth(token)
    ).json()
    return results["disposition_decisions"][0]["decision_id"]


def test_accept_decision_marks_it_accepted(client: TestClient) -> None:
    token = _token()
    run_id = _completed_run(client, token)
    decision_id = _first_decision_id(client, run_id, token)

    response = client.post(
        f"/v1/projects/project-1/assessment-runs/{run_id}/decisions/{decision_id}/accept",
        headers=_auth(token),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ACCEPTED"
    assert body["decided_by"] == "user-1"

    results = client.get(
        f"/v1/projects/project-1/assessment-runs/{run_id}/results", headers=_auth(token)
    ).json()
    decided = next(
        d for d in results["disposition_decisions"] if d["decision_id"] == decision_id
    )
    assert decided["status"] == "ACCEPTED"


def test_reject_decision_requires_a_reason(client: TestClient) -> None:
    token = _token()
    run_id = _completed_run(client, token)
    decision_id = _first_decision_id(client, run_id, token)

    response = client.post(
        f"/v1/projects/project-1/assessment-runs/{run_id}/decisions/{decision_id}/reject",
        json={},
        headers=_auth(token),
    )
    assert response.status_code == 422

    response = client.post(
        f"/v1/projects/project-1/assessment-runs/{run_id}/decisions/{decision_id}/reject",
        json={"reason": "workload already retired"},
        headers=_auth(token),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"


def test_amend_decision_replaces_disposition_and_rationale(client: TestClient) -> None:
    token = _token()
    run_id = _completed_run(client, token)
    decision_id = _first_decision_id(client, run_id, token)

    response = client.post(
        f"/v1/projects/project-1/assessment-runs/{run_id}/decisions/{decision_id}/amend",
        json={
            "disposition": "RETIRE",
            "rationale": "workload is being decommissioned next quarter",
            "confidence": 0.9,
        },
        headers=_auth(token),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["disposition"] == "RETIRE"
    assert body["status"] == "AMENDED"


def test_unknown_decision_is_not_found(client: TestClient) -> None:
    token = _token()
    run_id = _completed_run(client, token)

    response = client.post(
        f"/v1/projects/project-1/assessment-runs/{run_id}/decisions/does-not-exist/accept",
        headers=_auth(token),
    )
    assert response.status_code == 404


def test_build_evidence_package_fills_in_the_report_placeholder(client: TestClient) -> None:
    token = _token()
    run_id = _completed_run(client, token)

    response = client.post(
        f"/v1/projects/project-1/assessment-runs/{run_id}/evidence-package", headers=_auth(token)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["envelope"]["payload_hash"]
    assert body["envelope"]["signature"]["key_id"]
    assert body["report"]["evidence_package_hash"] == body["envelope"]["payload_hash"]
    assert "Evidence package hash: PENDING" not in body["report"]["rendered_text"]


def test_a_second_evidence_package_for_the_same_project_chains_to_the_first(
    client: TestClient,
) -> None:
    token = _token()
    run_id_1 = _completed_run(client, token)
    first = client.post(
        f"/v1/projects/project-1/assessment-runs/{run_id_1}/evidence-package",
        headers=_auth(token),
    ).json()

    run_id_2 = _completed_run(client, token)
    second = client.post(
        f"/v1/projects/project-1/assessment-runs/{run_id_2}/evidence-package",
        headers=_auth(token),
    ).json()

    assert second["envelope"]["previous_hash"] == first["envelope"]["payload_hash"]


# --- R1-19: cross-tenant adversarial coverage for every R1-18 route -----------
# (test_results_for_another_tenants_run_is_not_found above already covers
# /results; these close the gap on /report, the decision actions and
# /evidence-package, which R1-18's own session did not test this way.)


def test_report_for_another_tenants_run_is_not_found(client: TestClient) -> None:
    run_id = _completed_run(client, _token(tenant_id=TENANT_A))
    response = client.get(
        f"/v1/projects/project-1/assessment-runs/{run_id}/report",
        headers=_auth(_token(tenant_id=TENANT_B)),
    )
    assert response.status_code == 404


def test_decision_actions_on_another_tenants_run_are_not_found(client: TestClient) -> None:
    token_a = _token(tenant_id=TENANT_A)
    run_id = _completed_run(client, token_a)
    decision_id = _first_decision_id(client, run_id, token_a)
    other_tenant = _auth(_token(tenant_id=TENANT_B))

    assert (
        client.post(
            f"/v1/projects/project-1/assessment-runs/{run_id}/decisions/{decision_id}/accept",
            headers=other_tenant,
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/v1/projects/project-1/assessment-runs/{run_id}/decisions/{decision_id}/reject",
            json={"reason": "x"},
            headers=other_tenant,
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/v1/projects/project-1/assessment-runs/{run_id}/decisions/{decision_id}/amend",
            json={"disposition": "RETAIN", "rationale": "x", "confidence": 0.5},
            headers=other_tenant,
        ).status_code
        == 404
    )


def test_evidence_package_for_another_tenants_run_is_not_found(client: TestClient) -> None:
    run_id = _completed_run(client, _token(tenant_id=TENANT_A))
    response = client.post(
        f"/v1/projects/project-1/assessment-runs/{run_id}/evidence-package",
        headers=_auth(_token(tenant_id=TENANT_B)),
    )
    assert response.status_code == 404


def test_evidence_chains_do_not_cross_tenants_sharing_the_same_project_id(
    client: TestClient,
) -> None:
    """Regression test for a real cross-tenant leak found in this session's
    own earlier PR (#46): the evidence chain was keyed by ``project_id``
    alone. ``project_id`` is a client-supplied path segment this route
    never validates against real project ownership, so two different
    tenants naming the same ``project_id`` (exactly what every other test
    in this file does, with ``project-1``) must never chain their
    evidence packages together -- that would leak one tenant's
    ``payload_hash`` into another tenant's signed envelope.
    """
    token_a = _token(tenant_id=TENANT_A)
    token_b = _token(tenant_id=TENANT_B)

    run_a = _completed_run(client, token_a)
    package_a = client.post(
        f"/v1/projects/project-1/assessment-runs/{run_a}/evidence-package", headers=_auth(token_a)
    ).json()
    assert package_a["envelope"]["previous_hash"] is None

    run_b = _completed_run(client, token_b)
    package_b = client.post(
        f"/v1/projects/project-1/assessment-runs/{run_b}/evidence-package", headers=_auth(token_b)
    ).json()
    assert package_b["envelope"]["previous_hash"] is None
    assert package_b["envelope"]["previous_hash"] != package_a["envelope"]["payload_hash"]

    # A second package for tenant A still chains to tenant A's own first
    # package, proving the fix didn't also break same-tenant chaining.
    run_a_2 = _completed_run(client, token_a)
    package_a_2 = client.post(
        f"/v1/projects/project-1/assessment-runs/{run_a_2}/evidence-package",
        headers=_auth(token_a),
    ).json()
    assert package_a_2["envelope"]["previous_hash"] == package_a["envelope"]["payload_hash"]
