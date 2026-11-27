"""R6-11 acceptance: the ``design`` MCP server (including
``planning.generate_roadmap``, folded onto this same server), called
against the real pattern catalogue and mapping release seeds.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cairn_adapters.auth_oidc import JwtAuthenticator, OidcSettings
from cairn_kernel.errors import ForbiddenError, NotFoundError, ValidationError
from cairn_kernel.security import Role
from cairn_kits.mcp import McpRegistry, ToolCapability
from cairn_mcp_gateway.design_server import (
    TOOL_GENERATE_ROADMAP,
    TOOL_GENERATE_TARGET_MODEL,
    TOOL_GET_PATTERN,
    TOOL_GET_TARGET_MODEL,
    TOOL_LIST_PATTERNS,
    build_design_server,
)
from cairn_mcp_gateway.gateway import McpGateway

TENANT = "tenant-1"
PROJECT = "project-1"

ISSUER = "https://auth.example.cairn/"
AUDIENCE = "cairn-mcp-gateway"
SECRET = "unit-test-secret-does-not-leave-this-process"


def _resource(resource_id: str) -> dict:
    return {
        "resource_id": resource_id,
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "provider": "aws",
        "account_id": "acct-1",
        "region": "eu-west-1",
        "service": "s3",
        "resource_type": "bucket",
        "native_id": resource_id,
        "name": None,
        "tags": {},
        "facts": {},
        "provenance": [],
        "status": "OBSERVED",
    }


def _workload(workload_id: str) -> dict:
    return {
        "workload_id": workload_id,
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "name": workload_id,
        "environment": "prod",
        "owner": None,
        "business_context": None,
        "resource_ids": (),
        "dependency_ids": (),
        "facts": {},
        "disposition": None,
        "disposition_confidence": None,
        "model_version": "v1",
        "mapping_version": "2026.11.2",
    }


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
            TOOL_LIST_PATTERNS: Role.VIEWER,
            TOOL_GET_PATTERN: Role.VIEWER,
            TOOL_GET_TARGET_MODEL: Role.VIEWER,
            TOOL_GENERATE_TARGET_MODEL: Role.ARCHITECT,
            TOOL_GENERATE_ROADMAP: Role.ARCHITECT,
        },
    )


def test_list_patterns_and_get_pattern_return_real_data() -> None:
    server = build_design_server()

    patterns = server.handle(TOOL_LIST_PATTERNS, {})
    assert any(pattern.id == "web-app" for pattern in patterns)

    pattern = server.handle(TOOL_GET_PATTERN, {"pattern_id": "web-app"})
    assert pattern.id == "web-app"


def test_generate_target_model_is_declared_propose_and_produces_a_candidate() -> None:
    server = build_design_server()
    assert server.capabilities[TOOL_GENERATE_TARGET_MODEL] is ToolCapability.PROPOSE

    target_model = server.handle(
        TOOL_GENERATE_TARGET_MODEL,
        {
            "tenant_id": TENANT,
            "project_id": PROJECT,
            "design_id": "design-1",
            "pattern_id": "web-app",
            "mapping_version": "2026.11.2",
            "target_provider": "gcp",
            "resources": [_resource("r-1")],
            "parameters": {
                "compute_platform": "cloud_run",
                "database_engine": "cloud_sql_postgres",
            },
        },
    )

    assert target_model.design_id == "design-1"
    # no approval state set on a freshly generated candidate
    assert not hasattr(target_model, "approval_status")

    fetched = server.handle(TOOL_GET_TARGET_MODEL, {"design_id": "design-1"})
    assert fetched.design_id == "design-1"


def test_generate_roadmap_is_declared_propose_and_produces_a_candidate() -> None:
    server = build_design_server()
    assert server.capabilities[TOOL_GENERATE_ROADMAP] is ToolCapability.PROPOSE

    roadmap = server.handle(
        TOOL_GENERATE_ROADMAP,
        {
            "tenant_id": TENANT,
            "project_id": PROJECT,
            "plan_id": "plan-1",
            "design_id": "design-never-generated",
            "workloads": [_workload("w-1")],
        },
    )

    assert roadmap.plan_id == "plan-1"
    assert not hasattr(roadmap, "approval_status")


def test_get_target_model_before_generation_raises_not_found() -> None:
    server = build_design_server()

    with pytest.raises(NotFoundError):
        server.handle(TOOL_GET_TARGET_MODEL, {"design_id": "never-generated"})


def test_unknown_tool_name_raises() -> None:
    server = build_design_server()

    with pytest.raises(ValidationError):
        server.handle("design.publish_pattern", {})


def test_unknown_argument_key_is_rejected() -> None:
    server = build_design_server()

    with pytest.raises(ValidationError):
        server.handle(TOOL_GET_PATTERN, {"pattern_id": "web-app", "extra": "nope"})


def test_caller_below_declared_role_gets_forbidden_before_the_handle_runs() -> None:
    server = build_design_server()
    gateway = _gateway(server)
    token = _token(roles=(Role.VIEWER.value,))

    with pytest.raises(ForbiddenError):
        gateway.call_tool(
            TOOL_GENERATE_TARGET_MODEL,
            token,
            {
                "tenant_id": TENANT,
                "project_id": PROJECT,
                "design_id": "design-1",
                "pattern_id": "web-app",
                "mapping_version": "2026.11.2",
                "target_provider": "gcp",
            },
        )


def test_no_apply_publish_approve_or_execute_tool_is_registered() -> None:
    server = build_design_server()

    forbidden_substrings = ("apply", "publish", "approve", "execute")
    for tool_name in server.tools:
        lowered = tool_name.lower()
        assert not any(substring in lowered for substring in forbidden_substrings)
