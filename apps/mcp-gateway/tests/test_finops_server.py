"""R6-10 acceptance: the ``finops`` MCP server, instantiated and called
against one real assessment run's own cost artifacts and the real
price-list seed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from cairn_adapters.auth_oidc import JwtAuthenticator, OidcSettings
from cairn_kernel.errors import ForbiddenError, TenantScopeViolationError, ValidationError
from cairn_kernel.outbox import InMemoryOutboxStore
from cairn_kernel.security import Role
from cairn_kits.mcp import McpRegistry
from cairn_mcp_gateway.finops_server import (
    TOOL_GET_BASELINE,
    TOOL_GET_TCO,
    TOOL_LIST_PRICE_RELEASES,
    build_finops_server,
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
OTHER_TENANT = "tenant-2"
PROJECT = "project-1"
RUN_ID = "assessment-run-finops-test"

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
            TOOL_GET_BASELINE: Role.VIEWER,
            TOOL_GET_TCO: Role.VIEWER,
            TOOL_LIST_PRICE_RELEASES: Role.VIEWER,
        },
    )


def test_get_baseline_and_get_tco_return_real_data() -> None:
    server = build_finops_server(_real_assessment_service())

    baseline = server.handle(TOOL_GET_BASELINE, {"tenant_id": TENANT, "assessment_run_id": RUN_ID})
    assert baseline.total_amount_minor == 200_000

    tco = server.handle(TOOL_GET_TCO, {"tenant_id": TENANT, "assessment_run_id": RUN_ID})
    assert tco.price_list_version == "2026.11.1"


def test_list_price_releases_returns_the_real_seed() -> None:
    server = build_finops_server(_real_assessment_service())

    releases = server.handle(TOOL_LIST_PRICE_RELEASES, {})

    assert releases
    assert releases[0].version == "2026.11.1"


def test_reading_another_tenants_run_raises_tenant_scope_violation() -> None:
    server = build_finops_server(_real_assessment_service())

    with pytest.raises(TenantScopeViolationError):
        server.handle(TOOL_GET_BASELINE, {"tenant_id": OTHER_TENANT, "assessment_run_id": RUN_ID})


def test_unknown_tool_name_raises() -> None:
    server = build_finops_server(_real_assessment_service())

    with pytest.raises(ValidationError):
        server.handle("finops.delete_everything", {})


def test_unknown_argument_key_is_rejected() -> None:
    server = build_finops_server(_real_assessment_service())

    with pytest.raises(ValidationError):
        server.handle(TOOL_LIST_PRICE_RELEASES, {"extra": "nope"})


def test_caller_below_declared_role_gets_forbidden_before_the_handle_runs() -> None:
    server = build_finops_server(_real_assessment_service())
    gateway = _gateway(server)
    token = _token(roles=())

    with pytest.raises(ForbiddenError):
        gateway.call_tool(TOOL_LIST_PRICE_RELEASES, token, {})
