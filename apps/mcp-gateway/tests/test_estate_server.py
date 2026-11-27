"""R6-08 acceptance: the ``estate`` MCP server, instantiated and called
against one real assessment run's own artifacts.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from cairn_adapters.auth_oidc import JwtAuthenticator, OidcSettings
from cairn_kernel.errors import (
    ForbiddenError,
    NotFoundError,
    TenantScopeViolationError,
    ValidationError,
)
from cairn_kernel.hex import TenantId
from cairn_kernel.outbox import InMemoryOutboxStore
from cairn_kernel.security import Principal, Role
from cairn_kits.mcp import McpRegistry
from cairn_mcp_gateway.estate_server import (
    TOOL_GET_DEPENDENCIES,
    TOOL_GET_WORKLOAD,
    TOOL_LIST_RESOURCES,
    TOOL_LIST_WORKLOADS,
    build_estate_server,
)
from cairn_mcp_gateway.gateway import McpGateway
from cairn_modules.assessment import AssessmentService, InMemoryCheckpointStore, build_real_stages
from cairn_modules.finops import BillingLineItem, TcoAssumptions, load_price_list_release
from cairn_modules.posture import load_control_catalogue_release

REPO_ROOT = Path(__file__).resolve().parents[3]
INGESTION_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "ingestion"
CONTROL_SEED = REPO_ROOT / "controls" / "gcp-cis-seed.yaml"
PRICE_LIST_SEED = REPO_ROOT / "pricing" / "gcp-price-list-seed.yaml"

MOMENT = datetime(2026, 11, 14, 12, 0, 0, tzinfo=UTC)
TENANT = "tenant-1"
PROJECT = "project-1"
RUN_ID = "assessment-run-estate-test"

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
    """A real ``AssessmentService``, with one real run already advanced
    past the estate stage -- the same fixture shape
    ``test_assessment_orchestration.py`` builds, scoped down to just
    enough stages for this server's own tools to have real data to
    return."""

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


def _gateway(service: AssessmentService) -> McpGateway:
    registry = McpRegistry()
    registry.register(build_estate_server(service))
    return McpGateway(
        authenticator=JwtAuthenticator(_settings()),
        registry=registry,
        required_roles={
            TOOL_LIST_WORKLOADS: Role.VIEWER,
            TOOL_GET_WORKLOAD: Role.VIEWER,
            TOOL_LIST_RESOURCES: Role.VIEWER,
            TOOL_GET_DEPENDENCIES: Role.VIEWER,
        },
    )


def test_list_workloads_returns_real_data_through_the_application_service() -> None:
    service = _real_assessment_service()
    server = build_estate_server(service)

    workloads = server.handle(TOOL_LIST_WORKLOADS, {"assessment_run_id": RUN_ID}, _principal())

    assert workloads
    assert all(hasattr(workload, "workload_id") for workload in workloads)


def test_get_workload_and_dependencies_round_trip() -> None:
    service = _real_assessment_service()
    server = build_estate_server(service)

    workloads = server.handle(TOOL_LIST_WORKLOADS, {"assessment_run_id": RUN_ID}, _principal())
    one = workloads[0]

    fetched = server.handle(
        TOOL_GET_WORKLOAD,
        {"assessment_run_id": RUN_ID, "workload_id": one.workload_id},
        _principal(),
    )
    assert fetched.workload_id == one.workload_id

    dependencies = server.handle(
        TOOL_GET_DEPENDENCIES,
        {"assessment_run_id": RUN_ID, "workload_id": one.workload_id},
        _principal(),
    )
    assert set(dependencies) == {"depends_on", "depended_on_by"}


def test_list_resources_returns_real_data() -> None:
    service = _real_assessment_service()
    server = build_estate_server(service)

    resources = server.handle(TOOL_LIST_RESOURCES, {"assessment_run_id": RUN_ID}, _principal())

    assert resources


def test_get_workload_not_found_raises() -> None:
    service = _real_assessment_service()
    server = build_estate_server(service)

    with pytest.raises(NotFoundError):
        server.handle(
            TOOL_GET_WORKLOAD,
            {"assessment_run_id": RUN_ID, "workload_id": "no-such-workload"},
            _principal(),
        )


def test_unknown_tool_name_raises() -> None:
    service = _real_assessment_service()
    server = build_estate_server(service)

    with pytest.raises(ValidationError):
        server.handle("estate.delete_everything", {"assessment_run_id": RUN_ID}, _principal())


def test_unknown_argument_key_is_rejected() -> None:
    service = _real_assessment_service()
    server = build_estate_server(service)

    with pytest.raises(ValidationError):
        server.handle(
            TOOL_LIST_WORKLOADS,
            {"assessment_run_id": RUN_ID, "unexpected_extra_key": "x"},
            _principal(),
        )


def test_reading_another_tenants_run_raises_tenant_scope_violation() -> None:
    """ADR-020: a principal authenticated for a different tenant cannot
    read this run's workloads, even though estate has no RLS layer of
    its own to fall back on (every store behind it is in-memory)."""
    service = _real_assessment_service()
    server = build_estate_server(service)

    with pytest.raises(TenantScopeViolationError):
        server.handle(
            TOOL_LIST_WORKLOADS, {"assessment_run_id": RUN_ID}, _principal("tenant-2-other")
        )


def test_caller_below_declared_role_gets_forbidden_before_the_handle_runs() -> None:
    service = _real_assessment_service()
    gateway = _gateway(service)
    token = _token(roles=())  # no roles at all -- below VIEWER

    with pytest.raises(ForbiddenError):
        gateway.call_tool(TOOL_LIST_WORKLOADS, token, {"assessment_run_id": RUN_ID})
