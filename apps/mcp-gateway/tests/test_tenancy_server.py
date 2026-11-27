"""R6-10 acceptance: the ``tenancy`` MCP server, instantiated and
called against a real ``InMemoryProjectRepository`` -- and proven to
expose no mutating tool at all (design §0 assumption 5).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cairn_adapters.auth_oidc import JwtAuthenticator, OidcSettings
from cairn_kernel.errors import ForbiddenError, TenantScopeViolationError, ValidationError
from cairn_kernel.hex import TenantId
from cairn_kernel.security import Role
from cairn_kernel.tenancy import TenantContext, tenant_scope
from cairn_kits.mcp import McpRegistry
from cairn_mcp_gateway.gateway import McpGateway
from cairn_mcp_gateway.tenancy_server import (
    TOOL_GET_PROJECT,
    TOOL_LIST_PROJECT_MEMBERS,
    build_tenancy_server,
)
from cairn_modules.projects.repository import InMemoryProjectRepository

TENANT = "tenant-1"
OTHER_TENANT = "tenant-2"

ISSUER = "https://auth.example.cairn/"
AUDIENCE = "cairn-mcp-gateway"
SECRET = "unit-test-secret-does-not-leave-this-process"


def _scope(tenant_id: str) -> TenantContext:
    return TenantContext(
        tenant_id=TenantId(tenant_id),
        project_id=None,
        actor_id="test-setup",
        actor_roles=(),
        correlation_id=f"setup-{tenant_id}",
    )


def _seeded_repository() -> tuple[InMemoryProjectRepository, str]:
    repository = InMemoryProjectRepository()
    with tenant_scope(_scope(TENANT)):
        project = repository.create_project(
            tenant_id=TenantId(TENANT), name="Pilot migration", customer_name="Acme"
        )
        repository.add_member(
            project.project_id, user_id="user-1", role=Role.ENGINEER, granted_by="user-0"
        )
    return repository, project.project_id.value


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
            TOOL_GET_PROJECT: Role.VIEWER,
            TOOL_LIST_PROJECT_MEMBERS: Role.TENANT_ADMIN,
        },
    )


def test_get_project_returns_real_data() -> None:
    repository, project_id = _seeded_repository()
    server = build_tenancy_server(repository)

    project = server.handle(TOOL_GET_PROJECT, {"tenant_id": TENANT, "project_id": project_id})

    assert project.name == "Pilot migration"


def test_list_project_members_returns_real_data() -> None:
    repository, project_id = _seeded_repository()
    server = build_tenancy_server(repository)

    members = server.handle(
        TOOL_LIST_PROJECT_MEMBERS, {"tenant_id": TENANT, "project_id": project_id}
    )

    assert [member.user_id for member in members] == ["user-1"]


def test_reading_another_tenants_project_raises_tenant_scope_violation() -> None:
    repository, project_id = _seeded_repository()
    server = build_tenancy_server(repository)

    with pytest.raises(TenantScopeViolationError):
        server.handle(TOOL_GET_PROJECT, {"tenant_id": OTHER_TENANT, "project_id": project_id})


def test_unknown_tool_name_raises() -> None:
    repository, _project_id = _seeded_repository()
    server = build_tenancy_server(repository)

    with pytest.raises(ValidationError):
        server.handle("tenancy.create_project", {"tenant_id": TENANT})


def test_unknown_argument_key_is_rejected() -> None:
    repository, project_id = _seeded_repository()
    server = build_tenancy_server(repository)

    with pytest.raises(ValidationError):
        server.handle(
            TOOL_GET_PROJECT, {"tenant_id": TENANT, "project_id": project_id, "extra": "nope"}
        )


def test_no_tool_creates_a_tenant_grants_a_membership_or_changes_a_setting() -> None:
    """Asserted on the registered tool list itself, not by inspection
    (design §0 assumption 5 / this unit's own acceptance criterion)."""

    repository, _project_id = _seeded_repository()
    server = build_tenancy_server(repository)

    forbidden_substrings = ("create", "add_member", "remove_member", "set_settings", "grant")
    for tool_name in server.tools:
        lowered = tool_name.lower()
        assert not any(substring in lowered for substring in forbidden_substrings)
    assert server.tools == (TOOL_GET_PROJECT, TOOL_LIST_PROJECT_MEMBERS)


def test_list_project_members_requires_tenant_admin() -> None:
    repository, project_id = _seeded_repository()
    server = build_tenancy_server(repository)
    gateway = _gateway(server)
    token = _token(roles=(Role.VIEWER.value,))

    with pytest.raises(ForbiddenError):
        gateway.call_tool(
            TOOL_LIST_PROJECT_MEMBERS, token, {"tenant_id": TENANT, "project_id": project_id}
        )
