"""792 (R4-05): the approval and execution console's HTTP routes.

Drives the new routes against the real ``create_app``, seeding a
``DesignRegistry`` directly with an already-generated design (same
discipline ``test_design_api.py`` already uses) and orchestrating 787's
Terraform plan revision against ``FakeProviderExecutionAdapter`` -- no
real Terraform binary, no real cloud call anywhere in this suite (this
unit is explicitly "no cloud").

Proves spec §2.4's own acceptance text: an approver can see the exact
revision (diff/mutation class), the recovery plan and the evidence that
will be captured before approving (``test_*_shows_the_approver_*``
below), and -- the deliberate-break test this unit's brief asks for --
that an incomplete recovery plan cannot be approved from this console,
mirroring 783's own kernel-level gate re-enforced here at the UI/API
layer (``test_an_incomplete_recovery_plan_cannot_be_approved_*``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cairn_adapters.auth_oidc import JwtAuthenticator, OidcSettings
from cairn_adapters.diagram_drawio import FakeDiagramRenderer
from cairn_adapters.iac_terraform import FakeIaCGenerator
from cairn_api import create_app
from cairn_api.routes_design import DesignRecord, DesignRegistry
from cairn_contracts.estate import Equivalence, FactStatus, Resource
from cairn_contracts.mapping import MappingEntry, MappingRelease, ReleaseStatus
from cairn_modules.approvals.model import RevisionRecord
from cairn_modules.design import compile_diagram, generate_target_model, load_pattern_catalogue
from cairn_modules.planning import generate_iac_plan
from fastapi.testclient import TestClient

SECRET = "test-secret-that-is-long-enough-for-hs256"
ISSUER = "https://issuer.example.test"
AUDIENCE = "cairn-api"
TENANT_A = "6f0f0f31-6d0c-4f25-9a45-1d0e1a0f1f6a"
TENANT_B = "1b1b1b1b-2c2c-4d4d-8e8e-3f3f3f3f3f3f"
PROJECT_ID = "22222222-2222-2222-2222-222222222222"
DESIGN_ID = "33333333-3333-3333-3333-333333333333"

REPO_ROOT = __import__("pathlib").Path(__file__).parents[3]
PATTERNS_DIR = REPO_ROOT / "patterns"

COMPLETE_ROLLBACK_PLAN = {
    "strategy": "ROLLBACK",
    "plan_ref": "tf-plan-ref-1",
    "preconditions": "rollback reference validated before authorization",
    "authority": "PROJECT_OWNER",
    "evidence": "before/during/after state snapshots captured to the evidence store",
    "failure_handling": "escalate to docs/runbooks/rollback-compensation-recovery.md",
}


def _authenticator() -> JwtAuthenticator:
    return JwtAuthenticator(
        OidcSettings(issuer=ISSUER, audience=AUDIENCE, algorithms=("HS256",), secret=SECRET)
    )


def _token(
    *, tenant_id: str = TENANT_A, subject: str = "user-1", roles: list[str] | None = None
) -> str:
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


def _seeded_design_registry() -> DesignRegistry:
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
    registry.put_design(
        DESIGN_ID,
        DesignRecord(
            tenant_id=TENANT_A,
            project_id=PROJECT_ID,
            plan_id="plan-1",
            target_model=target_model,
            revision=design_revision,
            diagram=diagram,
            iac=iac,
        ),
    )
    return registry


@pytest.fixture
def client() -> TestClient:
    app = create_app(
        authenticator=_authenticator(),
        assertion_secret=b"test-assertion-secret",
        design_registry=_seeded_design_registry(),
    )
    return TestClient(app)


def _propose(
    client: TestClient,
    *,
    mutation_class: str = "REVERSIBLE_EXTERNAL_MUTATION",
    compensation: dict | None = COMPLETE_ROLLBACK_PLAN,
    roles: list[str] | None = None,
) -> dict:
    body: dict = {"mutation_class": mutation_class}
    if compensation is not None:
        body["compensation"] = compensation
    response = client.post(
        f"/v1/designs/{DESIGN_ID}/approval",
        json=body,
        headers=_auth(_token(roles=roles)),
    )
    assert response.status_code == 200, response.text
    return response.json()


# -- §2.4: the approver sees the exact revision, mutation class, recovery
# plan and evidence that will be captured, before approving --


def test_creating_a_plan_approval_shows_the_exact_revision_and_diff(client: TestClient) -> None:
    view = _propose(client)

    revision = view["revision"]
    assert revision["design_id"] == DESIGN_ID
    assert revision["mutation_class"] == "REVERSIBLE_EXTERNAL_MUTATION"
    assert revision["content_hash"]
    assert len(revision["diff"]) == 1
    assert revision["diff"][0]["resource_id"] == "res-1"
    assert revision["diff"][0]["action"] == "CREATE"
    assert revision["resource_list"] == ["res-1"]
    assert revision["reversible"] is True


def test_creating_a_plan_approval_shows_the_recovery_plan_and_evidence(client: TestClient) -> None:
    view = _propose(client)

    assert view["recovery_plan"] == COMPLETE_ROLLBACK_PLAN
    assert view["evidence_to_capture"] == COMPLETE_ROLLBACK_PLAN["evidence"]
    assert view["risk_tier"] == "TIER_1"


def test_get_plan_approval_reflects_what_was_proposed(client: TestClient) -> None:
    created = _propose(client)
    revision_id = created["revision"]["revision_id"]

    response = client.get(f"/v1/plans/{revision_id}/approval", headers=_auth(_token()))

    assert response.status_code == 200, response.text
    assert response.json() == created


def test_proposing_the_same_design_twice_with_different_mutation_classes_yields_two_revisions(
    client: TestClient,
) -> None:
    first = _propose(client, mutation_class="REVERSIBLE_EXTERNAL_MUTATION")
    second = _propose(
        client,
        mutation_class="COMPENSATABLE_EXTERNAL_MUTATION",
        compensation={**COMPLETE_ROLLBACK_PLAN, "strategy": "COMPENSATE"},
    )
    # Same design revision identity underneath both proposals.
    assert first["revision"]["revision_id"] == second["revision"]["revision_id"]
    assert first["revision"]["mutation_class"] != second["revision"]["mutation_class"]
    assert first["risk_tier"] == "TIER_1"
    assert second["risk_tier"] == "TIER_2"


# -- approving with a complete, matching recovery plan --


def test_approving_with_a_complete_matching_recovery_plan_succeeds(client: TestClient) -> None:
    created = _propose(client)
    revision_id = created["revision"]["revision_id"]

    response = client.post(
        f"/v1/plans/{revision_id}/approval-comments",
        json={"decision": "APPROVE", "body": "revision, diff, recovery plan and evidence all checked"},
        headers=_auth(_token()),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["blocked"] is False
    assert body["reviewed"] is True
    assert body["comments"][0]["decision"] == "APPROVE"


def test_a_plain_comment_never_requires_a_recovery_plan(client: TestClient) -> None:
    created = _propose(client, compensation=None)
    revision_id = created["revision"]["revision_id"]

    response = client.post(
        f"/v1/plans/{revision_id}/approval-comments",
        json={"decision": "COMMENT", "body": "still waiting on a recovery plan"},
        headers=_auth(_token()),
    )

    assert response.status_code == 200, response.text
    assert response.json()["reviewed"] is False


def test_request_changes_visibly_blocks_further_progress(client: TestClient) -> None:
    created = _propose(client)
    revision_id = created["revision"]["revision_id"]

    response = client.post(
        f"/v1/plans/{revision_id}/approval-comments",
        json={"decision": "REQUEST_CHANGES", "body": "rollback plan_ref looks stale"},
        headers=_auth(_token()),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["blocked"] is True
    assert body["reviewed"] is True


# -- the deliberate-break test: an incomplete recovery plan cannot be
# approved from the console, mirroring 783's own gate --


def test_an_incomplete_recovery_plan_cannot_be_approved_no_recovery_plan_at_all(
    client: TestClient,
) -> None:
    created = _propose(client, compensation=None)
    revision_id = created["revision"]["revision_id"]
    assert created["recovery_plan"] is None
    assert "No recovery plan" in created["evidence_to_capture"]

    response = client.post(
        f"/v1/plans/{revision_id}/approval-comments",
        json={"decision": "APPROVE", "body": "looks fine to me"},
        headers=_auth(_token()),
    )

    assert response.status_code == 403, response.text

    # Fails closed: no partial state -- the thread is untouched, not
    # silently marked approved or even recorded as commented.
    thread = client.get(
        f"/v1/plans/{revision_id}/approval-comments", headers=_auth(_token())
    ).json()
    assert thread["comments"] == []
    assert thread["reviewed"] is False


def test_an_incomplete_recovery_plan_cannot_be_approved_mismatched_strategy(
    client: TestClient,
) -> None:
    created = _propose(
        client,
        mutation_class="REVERSIBLE_EXTERNAL_MUTATION",
        compensation={**COMPLETE_ROLLBACK_PLAN, "strategy": "COMPENSATE"},
    )
    revision_id = created["revision"]["revision_id"]
    # The console still shows the approver exactly what was proposed --
    # it does not hide a bad recovery plan, it just refuses to approve it.
    assert created["recovery_plan"]["strategy"] == "COMPENSATE"

    response = client.post(
        f"/v1/plans/{revision_id}/approval-comments",
        json={"decision": "APPROVE", "body": "approving anyway"},
        headers=_auth(_token()),
    )

    assert response.status_code == 403, response.text


def test_a_blank_recovery_plan_field_is_rejected_at_the_request_boundary(
    client: TestClient,
) -> None:
    response = client.post(
        f"/v1/designs/{DESIGN_ID}/approval",
        json={
            "mutation_class": "REVERSIBLE_EXTERNAL_MUTATION",
            "compensation": {**COMPLETE_ROLLBACK_PLAN, "evidence": "   "},
        },
        headers=_auth(_token()),
    )
    assert response.status_code == 422, response.text


# -- roles and tenant isolation --


def test_proposing_a_plan_for_approval_requires_engineer_or_above(client: TestClient) -> None:
    response = client.post(
        f"/v1/designs/{DESIGN_ID}/approval",
        json={"mutation_class": "REVERSIBLE_EXTERNAL_MUTATION", "compensation": COMPLETE_ROLLBACK_PLAN},
        headers=_auth(_token(roles=["VIEWER"])),
    )
    assert response.status_code == 403


def test_approving_requires_engineer_reviewer_or_above(client: TestClient) -> None:
    created = _propose(client)
    revision_id = created["revision"]["revision_id"]

    response = client.post(
        f"/v1/plans/{revision_id}/approval-comments",
        json={"decision": "APPROVE", "body": "lgtm"},
        headers=_auth(_token(roles=["VIEWER"])),
    )
    assert response.status_code == 403


def test_a_reviewer_role_can_approve(client: TestClient) -> None:
    created = _propose(client)
    revision_id = created["revision"]["revision_id"]

    response = client.post(
        f"/v1/plans/{revision_id}/approval-comments",
        json={"decision": "APPROVE", "body": "lgtm"},
        headers=_auth(_token(roles=["REVIEWER"])),
    )
    assert response.status_code == 200, response.text
    assert response.json()["reviewed"] is True


def test_a_plan_approval_for_another_tenant_is_not_found(client: TestClient) -> None:
    created = _propose(client)
    revision_id = created["revision"]["revision_id"]

    response = client.get(
        f"/v1/plans/{revision_id}/approval", headers=_auth(_token(tenant_id=TENANT_B))
    )
    assert response.status_code == 404


def test_proposing_a_plan_for_an_unknown_design_is_not_found(client: TestClient) -> None:
    response = client.post(
        "/v1/designs/does-not-exist/approval",
        json={"mutation_class": "REVERSIBLE_EXTERNAL_MUTATION", "compensation": COMPLETE_ROLLBACK_PLAN},
        headers=_auth(_token()),
    )
    assert response.status_code == 404


def test_reading_an_unknown_plan_revision_is_not_found(client: TestClient) -> None:
    response = client.get("/v1/plans/does-not-exist/approval", headers=_auth(_token()))
    assert response.status_code == 404
