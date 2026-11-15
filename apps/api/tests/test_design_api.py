"""R2-08: the design/plan export HTTP routes.

Same authenticate-through-``AuthMiddleware`` discipline as
``test_connections_api.py``/``test_mappings_api.py``. Seeds a
``DesignRegistry`` directly with an already-generated design/plan chain
(this story adds no write route -- 703-706's generation machinery is
exercised at the module level in ``packages/modules/tests/
test_design_export.py``) and proves:

- the export round-trip over HTTP: ``GET /v1/designs/{id}`` returns the
  full bundle with every field present and version stamps consistent;
- the diagram and report routes return their own shape;
- the plan-list and plan-revision routes return their own shape;
- every one of those five routes enforces tenant isolation -- a
  cross-tenant read is a 404, never leaked data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import jwt
import pytest
from cairn_adapters.auth_oidc import JwtAuthenticator, OidcSettings
from cairn_adapters.diagram_drawio import FakeDiagramRenderer
from cairn_adapters.iac_terraform import FakeIaCGenerator
from cairn_api import create_app
from cairn_api.routes_design import DesignRecord, DesignRegistry, PlanRecord
from cairn_contracts.estate import (
    DecisionStatus,
    Disposition,
    DispositionDecision,
    Equivalence,
    FactStatus,
    Resource,
    Workload,
)
from cairn_contracts.mapping import MappingEntry, MappingRelease, ReleaseStatus
from cairn_modules.approvals.model import RevisionRecord
from cairn_modules.design import compile_diagram, generate_target_model, load_pattern_catalogue
from cairn_modules.planning import generate_iac_plan, generate_roadmap
from fastapi.testclient import TestClient

SECRET = "test-secret-that-is-long-enough-for-hs256"
ISSUER = "https://issuer.example.test"
AUDIENCE = "cairn-api"
TENANT_A = "6f0f0f31-6d0c-4f25-9a45-1d0e1a0f1f6a"
TENANT_B = "1b1b1b1b-2c2c-4d4d-8e8e-3f3f3f3f3f3f"
PROJECT_ID = "22222222-2222-2222-2222-222222222222"
DESIGN_ID = "33333333-3333-3333-3333-333333333333"
PLAN_ID = "44444444-4444-4444-4444-444444444444"

REPO_ROOT = Path(__file__).parents[3]
PATTERNS_DIR = REPO_ROOT / "patterns"


def _authenticator() -> JwtAuthenticator:
    return JwtAuthenticator(
        OidcSettings(issuer=ISSUER, audience=AUDIENCE, algorithms=("HS256",), secret=SECRET)
    )


def _token(*, tenant_id: str = TENANT_A, subject: str = "user-1") -> str:
    from datetime import timedelta

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


def _resource() -> Resource:
    return Resource(
        resource_id="res-1",
        tenant_id=TENANT_A,
        project_id=PROJECT_ID,
        provider="aws",
        account_id="111111111111",
        region="eu-west-2",
        service="s3",
        resource_type="bucket",
        native_id="arn:aws:s3:::my-bucket",
        name="my-bucket",
        tags={},
        facts={},
        provenance=(),
        status=FactStatus.OBSERVED,
    )


def _release() -> MappingRelease:
    return MappingRelease(
        version="2026.11.1",
        released_at=datetime(2026, 11, 9, tzinfo=UTC),
        status=ReleaseStatus.DRAFT,
        entries=(
            MappingEntry(
                id="s3-to-gcs",
                source_provider="aws",
                source_service="s3",
                target_provider="gcp",
                target_service="cloud-storage",
                equivalence=Equivalence.EXACT,
                caveat=None,
                regions=(),
                evidence="public documentation",
            ),
        ),
    )


def _pattern():
    catalogue = load_pattern_catalogue(
        PATTERNS_DIR, version="2026.11.1", released_at=datetime(2026, 11, 15, tzinfo=UTC)
    )
    for pattern in catalogue.patterns:
        if pattern.id == "web-app":
            return pattern
    raise AssertionError("web-app seed pattern is missing")


def _workload() -> Workload:
    return Workload(
        workload_id="wl-1",
        tenant_id=TENANT_A,
        project_id=PROJECT_ID,
        name="wl-1",
        environment="UNVERIFIED",
        owner=None,
        business_context=None,
        resource_ids=("res-1",),
        dependency_ids=(),
        facts={},
        disposition=None,
        disposition_confidence=None,
        model_version="r1-07-grouping-v1",
        mapping_version="r1-07-grouping-v1",
    )


def _decision() -> DispositionDecision:
    return DispositionDecision(
        decision_id="decision-wl-1",
        tenant_id=TENANT_A,
        project_id=PROJECT_ID,
        workload_id="wl-1",
        disposition=Disposition.REHOST,
        rationale="lift and shift",
        confidence=0.9,
        status=DecisionStatus.ACCEPTED,
        decided_by="alice",
        decided_at=datetime(2026, 11, 15, tzinfo=UTC),
        model_version="r1-14-classifier-v1",
        mapping_version="r1-14-classifier-v1",
    )


def _seeded_registry() -> DesignRegistry:
    registry = DesignRegistry()
    target_model = generate_target_model(
        tenant_id=TENANT_A,
        project_id=PROJECT_ID,
        design_id=DESIGN_ID,
        estate=(_resource(),),
        pattern=_pattern(),
        pattern_catalogue_version="2026.11.1",
        mapping_release=_release(),
        target_provider="gcp",
        parameters={"compute_platform": "cloud_run", "database_engine": "cloud_sql_postgres"},
    )
    design_revision = RevisionRecord(
        revision_id="design-revision-1",
        tenant_id=TENANT_A,
        project_id=PROJECT_ID,
        subject_kind="design",
        subject_id=DESIGN_ID,
        revision_number=1,
        content_hash=target_model.content_hash,
        input_versions=(("pattern_id", target_model.pattern_id),),
        created_by="alice",
        created_at=datetime(2026, 11, 15, tzinfo=UTC),
    )
    diagram = compile_diagram(
        target_model=target_model, revision=design_revision, renderer=FakeDiagramRenderer()
    )
    iac = generate_iac_plan(
        target_model=target_model, revision=design_revision, generator=FakeIaCGenerator()
    )
    roadmap = generate_roadmap(
        tenant_id=TENANT_A,
        project_id=PROJECT_ID,
        plan_id=PLAN_ID,
        workloads=(_workload(),),
        dispositions={"wl-1": _decision()},
        target_model=target_model,
    )
    plan_revision = RevisionRecord(
        revision_id="plan-revision-1",
        tenant_id=TENANT_A,
        project_id=PROJECT_ID,
        subject_kind="plan",
        subject_id=PLAN_ID,
        revision_number=1,
        content_hash=roadmap.content_hash,
        input_versions=(("wave_count", str(len(roadmap.waves))),),
        created_by="alice",
        created_at=datetime(2026, 11, 15, tzinfo=UTC),
    )

    registry.put_design(
        DESIGN_ID,
        DesignRecord(
            tenant_id=TENANT_A,
            project_id=PROJECT_ID,
            plan_id=PLAN_ID,
            target_model=target_model,
            revision=design_revision,
            diagram=diagram,
            iac=iac,
        ),
    )
    registry.add_plan_revision(
        PLAN_ID,
        PlanRecord(
            tenant_id=TENANT_A,
            project_id=PROJECT_ID,
            plan_id=PLAN_ID,
            roadmap=roadmap,
            revision=plan_revision,
        ),
    )
    return registry


@pytest.fixture
def client() -> TestClient:
    app = create_app(
        authenticator=_authenticator(),
        assertion_secret=b"test-assertion-secret",
        design_registry=_seeded_registry(),
    )
    return TestClient(app)


def test_get_design_returns_the_full_export_bundle_with_consistent_versions(
    client: TestClient,
) -> None:
    response = client.get(f"/v1/designs/{DESIGN_ID}", headers=_auth(_token()))
    assert response.status_code == 200
    body = response.json()
    assert body["design_id"] == DESIGN_ID
    assert body["tenant_id"] == TENANT_A
    assert body["project_id"] == PROJECT_ID

    for section in ("design", "diagram", "plan", "iac"):
        assert section in body
        versions = body[section]["versions"]
        assert versions == {
            "pattern_catalogue_version": "2026.11.1",
            "mapping_release_version": "2026.11.1",
            "target_provider": "gcp",
        }
    assert body["plan"]["plan_id"] == PLAN_ID
    # R2-09 fix: ``version_stamps_consistent`` is a ``@property`` on the
    # domain dataclass, not a field, so a plain ``jsonable_encoder``
    # drops it silently -- this route puts it back on the wire.
    assert body["version_stamps_consistent"] is True


def test_get_design_diagram_returns_the_rendered_diagram(client: TestClient) -> None:
    response = client.get(f"/v1/designs/{DESIGN_ID}/diagram", headers=_auth(_token()))
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "DIAGRAM"
    assert body.get("rendered_content")


def test_get_design_report_shows_coverage_assumptions_and_versions(client: TestClient) -> None:
    response = client.get(f"/v1/designs/{DESIGN_ID}/report", headers=_auth(_token()))
    assert response.status_code == 200
    body = response.json()
    assert body["coverage"]["resource_count"] == 1
    assert body["versions"]["pattern_catalogue_version"] == "2026.11.1"
    assert "Design export report" in body["rendered_text"]


def test_list_plans_for_project_returns_the_seeded_plan(client: TestClient) -> None:
    response = client.get(f"/v1/projects/{PROJECT_ID}/plans", headers=_auth(_token()))
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["plan_id"] == PLAN_ID
    assert body[0]["revision_number"] == 1


def test_get_plan_revision_returns_the_seeded_revision(client: TestClient) -> None:
    response = client.get(f"/v1/plans/{PLAN_ID}/revisions/1", headers=_auth(_token()))
    assert response.status_code == 200
    body = response.json()
    assert body["plan_id"] == PLAN_ID
    assert body["revision_number"] == 1


def test_get_plan_revision_unknown_revision_number_is_not_found(client: TestClient) -> None:
    response = client.get(f"/v1/plans/{PLAN_ID}/revisions/99", headers=_auth(_token()))
    assert response.status_code == 404


# --- tenant isolation: every new route is a 404 for another tenant, never data ---


def test_get_design_another_tenant_is_not_found(client: TestClient) -> None:
    response = client.get(
        f"/v1/designs/{DESIGN_ID}", headers=_auth(_token(tenant_id=TENANT_B))
    )
    assert response.status_code == 404


def test_get_design_diagram_another_tenant_is_not_found(client: TestClient) -> None:
    response = client.get(
        f"/v1/designs/{DESIGN_ID}/diagram", headers=_auth(_token(tenant_id=TENANT_B))
    )
    assert response.status_code == 404


def test_get_design_report_another_tenant_is_not_found(client: TestClient) -> None:
    response = client.get(
        f"/v1/designs/{DESIGN_ID}/report", headers=_auth(_token(tenant_id=TENANT_B))
    )
    assert response.status_code == 404


def test_list_plans_another_tenant_sees_no_plans(client: TestClient) -> None:
    response = client.get(
        f"/v1/projects/{PROJECT_ID}/plans", headers=_auth(_token(tenant_id=TENANT_B))
    )
    assert response.status_code == 200
    assert response.json() == []


def test_get_plan_revision_another_tenant_is_not_found(client: TestClient) -> None:
    response = client.get(
        f"/v1/plans/{PLAN_ID}/revisions/1", headers=_auth(_token(tenant_id=TENANT_B))
    )
    assert response.status_code == 404


def test_unknown_design_is_not_found(client: TestClient) -> None:
    response = client.get("/v1/designs/does-not-exist", headers=_auth(_token()))
    assert response.status_code == 404


def test_unknown_plan_is_not_found(client: TestClient) -> None:
    response = client.get("/v1/plans/does-not-exist/revisions/1", headers=_auth(_token()))
    assert response.status_code == 404
