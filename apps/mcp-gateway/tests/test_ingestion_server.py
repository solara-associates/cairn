"""R6-09 acceptance: the ``ingestion`` MCP server (file-ingestion runs
plus the four tools folded in from what the design originally proposed
as a ninth ``assessment`` server), instantiated and called against one
real assessment run's own artifacts.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from cairn_adapters.auth_oidc import JwtAuthenticator, OidcSettings
from cairn_kernel.errors import ForbiddenError, TenantScopeViolationError, ValidationError
from cairn_kernel.hex import TenantId
from cairn_kernel.outbox import InMemoryOutboxStore
from cairn_kernel.security import Principal, Role
from cairn_kits.mcp import McpRegistry
from cairn_mcp_gateway.gateway import McpGateway
from cairn_mcp_gateway.ingestion_server import (
    TOOL_ASSESSMENT_COVERAGE_REPORT,
    TOOL_ASSESSMENT_GET_DECISION,
    TOOL_ASSESSMENT_GET_RESULTS,
    TOOL_ASSESSMENT_GET_RUN,
    TOOL_GET_COVERAGE,
    TOOL_GET_RUN,
    TOOL_LIST_RUNS,
    build_ingestion_server,
)
from cairn_modules.assessment import AssessmentService, InMemoryCheckpointStore, build_real_stages
from cairn_modules.finops import BillingLineItem, TcoAssumptions, load_price_list_release
from cairn_modules.ingestion.run import InMemoryCheckpointStore as IngestionCheckpointStore
from cairn_modules.ingestion.run import queue_run as queue_ingestion_run
from cairn_modules.posture import load_control_catalogue_release

REPO_ROOT = Path(__file__).resolve().parents[3]
INGESTION_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "ingestion"
CONTROL_SEED = REPO_ROOT / "controls" / "gcp-cis-seed.yaml"
PRICE_LIST_SEED = REPO_ROOT / "pricing" / "gcp-price-list-seed.yaml"

MOMENT = datetime(2026, 11, 14, 12, 0, 0, tzinfo=UTC)
TENANT = "tenant-1"
OTHER_TENANT = "tenant-2"
PROJECT = "project-1"
RUN_ID = "assessment-run-ingestion-test"

ISSUER = "https://auth.example.cairn/"
AUDIENCE = "cairn-mcp-gateway"
SECRET = "unit-test-secret-does-not-leave-this-process"


def _billing_item(source_id: str) -> BillingLineItem:
    return BillingLineItem(
        source_id=source_id,
        provider="gcp",
        tenant_id=TENANT,
        project_id=PROJECT,
        account_id="gcp-billing-acct-1",
        service="Compute Engine",
        region="europe-west2",
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 1, 1, tzinfo=UTC),
        currency="GBP",
        amount_minor=100_000,
        tags={"env": "prod"},
        raw_ref=f"gcp://acct/billing/{source_id}",
    )


def _real_assessment_service() -> AssessmentService:
    service = AssessmentService(
        checkpoint_store=InMemoryCheckpointStore(), outbox=InMemoryOutboxStore()
    )
    service.queue_run(run_id=RUN_ID, tenant_id=TENANT, project_id=PROJECT)
    stage_fns = build_real_stages(
        ingestion_files=[("csv", (INGESTION_FIXTURES / "golden.csv").read_text())],
        billing_items=[_billing_item("row-1"), _billing_item("row-2")],
        control_catalogue=load_control_catalogue_release(CONTROL_SEED),
        price_list=load_price_list_release(PRICE_LIST_SEED),
        tco_assumptions=TcoAssumptions(horizon_periods=3, growth_rate=0.02, discount_rate=0.1),
        ingest_run_id=RUN_ID,
        cost_currency="GBP",
        scenario_id="scenario-1",
        clock=lambda: MOMENT,
    )
    service.advance_run(RUN_ID, stage_fns=stage_fns)
    return service


def _real_ingestion_checkpoint_store() -> IngestionCheckpointStore:
    store = IngestionCheckpointStore()
    queue_ingestion_run(
        store, run_id="ingest-run-1", tenant_id=TENANT, project_id=PROJECT, file_ids=()
    )
    return store


def _principal(tenant_id: str = TENANT) -> Principal:
    return Principal(subject="user-1", tenant_id=TenantId(tenant_id), roles=(Role.VIEWER,))


def _settings() -> OidcSettings:
    return OidcSettings(issuer=ISSUER, audience=AUDIENCE, algorithms=("HS256",), secret=SECRET)


def _token(*, roles: tuple[str, ...]) -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "user-1",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "tenant_id": str(uuid.uuid4()),
        "roles": list(roles),
    }
    return jwt.encode(claims, SECRET, algorithm="HS256")


def _gateway(server) -> McpGateway:
    registry = McpRegistry()
    registry.register(server)
    return McpGateway(
        authenticator=JwtAuthenticator(_settings()),
        registry=registry,
        required_roles={
            TOOL_GET_RUN: Role.VIEWER,
            TOOL_LIST_RUNS: Role.VIEWER,
            TOOL_GET_COVERAGE: Role.VIEWER,
            TOOL_ASSESSMENT_GET_RUN: Role.VIEWER,
            TOOL_ASSESSMENT_GET_RESULTS: Role.VIEWER,
            TOOL_ASSESSMENT_COVERAGE_REPORT: Role.VIEWER,
            TOOL_ASSESSMENT_GET_DECISION: Role.VIEWER,
        },
    )


def test_assessment_get_run_and_get_results_return_real_data() -> None:
    assessment_service = _real_assessment_service()
    server = build_ingestion_server(_real_ingestion_checkpoint_store(), assessment_service)

    run = server.handle(
        TOOL_ASSESSMENT_GET_RUN, {"tenant_id": TENANT, "assessment_run_id": RUN_ID}, _principal()
    )
    assert run.run_id == RUN_ID

    results = server.handle(
        TOOL_ASSESSMENT_GET_RESULTS,
        {"tenant_id": TENANT, "assessment_run_id": RUN_ID},
        _principal(),
    )
    assert "workloads" in results
    assert "disposition_decisions" in results


def test_assessment_coverage_report_and_get_decision() -> None:
    assessment_service = _real_assessment_service()
    server = build_ingestion_server(_real_ingestion_checkpoint_store(), assessment_service)

    report = server.handle(
        TOOL_ASSESSMENT_COVERAGE_REPORT,
        {"tenant_id": TENANT, "assessment_run_id": RUN_ID},
        _principal(),
    )
    assert report["state"] == "COMPLETED"

    results = server.handle(
        TOOL_ASSESSMENT_GET_RESULTS,
        {"tenant_id": TENANT, "assessment_run_id": RUN_ID},
        _principal(),
    )
    decision_id = results["disposition_decisions"][0].decision_id

    decision = server.handle(
        TOOL_ASSESSMENT_GET_DECISION,
        {"tenant_id": TENANT, "assessment_run_id": RUN_ID, "decision_id": decision_id},
        _principal(),
    )
    assert decision.decision_id == decision_id


def test_ingestion_get_run_and_list_runs_return_real_data() -> None:
    store = _real_ingestion_checkpoint_store()
    server = build_ingestion_server(store, _real_assessment_service())

    run = server.handle(TOOL_GET_RUN, {"tenant_id": TENANT, "run_id": "ingest-run-1"}, _principal())
    assert run.run_id == "ingest-run-1"

    runs = server.handle(TOOL_LIST_RUNS, {"tenant_id": TENANT, "project_id": PROJECT}, _principal())
    assert [r.run_id for r in runs] == ["ingest-run-1"]

    coverage = server.handle(
        TOOL_GET_COVERAGE, {"tenant_id": TENANT, "run_id": "ingest-run-1"}, _principal()
    )
    assert "coverage" in coverage


def test_reading_another_tenants_run_raises_tenant_scope_violation() -> None:
    assessment_service = _real_assessment_service()
    server = build_ingestion_server(_real_ingestion_checkpoint_store(), assessment_service)

    with pytest.raises(TenantScopeViolationError):
        server.handle(
            TOOL_ASSESSMENT_GET_RUN,
            {"tenant_id": OTHER_TENANT, "assessment_run_id": RUN_ID},
            _principal(OTHER_TENANT),
        )


def test_reading_another_tenants_ingestion_run_raises_tenant_scope_violation() -> None:
    store = _real_ingestion_checkpoint_store()
    server = build_ingestion_server(store, _real_assessment_service())

    with pytest.raises(TenantScopeViolationError):
        server.handle(
            TOOL_GET_RUN,
            {"tenant_id": OTHER_TENANT, "run_id": "ingest-run-1"},
            _principal(OTHER_TENANT),
        )


def test_a_tenant_b_principal_cannot_claim_tenant_as_its_own_run() -> None:
    """ADR-020: the real gap this unit closes. A caller-supplied
    ``tenant_id`` naming the run's real tenant is not enough on its
    own -- the authenticated principal must actually be that tenant."""
    assessment_service = _real_assessment_service()
    server = build_ingestion_server(_real_ingestion_checkpoint_store(), assessment_service)

    with pytest.raises(TenantScopeViolationError):
        server.handle(
            TOOL_ASSESSMENT_GET_RUN,
            {"tenant_id": TENANT, "assessment_run_id": RUN_ID},
            _principal(OTHER_TENANT),
        )


def test_unknown_tool_name_raises() -> None:
    server = build_ingestion_server(_real_ingestion_checkpoint_store(), _real_assessment_service())

    with pytest.raises(ValidationError):
        server.handle("ingestion.delete_everything", {"tenant_id": TENANT}, _principal())


def test_unknown_argument_key_is_rejected() -> None:
    server = build_ingestion_server(_real_ingestion_checkpoint_store(), _real_assessment_service())

    with pytest.raises(ValidationError):
        server.handle(
            TOOL_LIST_RUNS,
            {"tenant_id": TENANT, "project_id": PROJECT, "extra": "nope"},
            _principal(),
        )


def test_caller_below_declared_role_gets_forbidden_before_the_handle_runs() -> None:
    server = build_ingestion_server(_real_ingestion_checkpoint_store(), _real_assessment_service())
    gateway = _gateway(server)
    token = _token(roles=())

    with pytest.raises(ForbiddenError):
        gateway.call_tool(TOOL_LIST_RUNS, token, {"tenant_id": TENANT, "project_id": PROJECT})
