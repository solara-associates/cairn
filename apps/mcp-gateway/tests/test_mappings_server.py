"""R6-08 acceptance: the ``mappings`` MCP server, instantiated and
called against the real seed release (``mappings/service-map.yaml``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cairn_adapters.auth_oidc import JwtAuthenticator, OidcSettings
from cairn_contracts.estate import Equivalence
from cairn_kernel.errors import ForbiddenError, MappingUnavailableError, ValidationError
from cairn_kernel.hex import TenantId
from cairn_kernel.security import Principal, Role
from cairn_kits.mcp import McpRegistry
from cairn_mcp_gateway.gateway import McpGateway
from cairn_mcp_gateway.mappings_server import (
    TOOL_GET_RELEASE,
    TOOL_LIST_RELEASES,
    TOOL_RESOLVE,
    build_mappings_server,
)

ISSUER = "https://auth.example.cairn/"
AUDIENCE = "cairn-mcp-gateway"
SECRET = "unit-test-secret-does-not-leave-this-process"


def _principal() -> Principal:
    return Principal(subject="user-1", tenant_id=TenantId("tenant-1"), roles=(Role.VIEWER,))


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


def _gateway() -> McpGateway:
    registry = McpRegistry()
    registry.register(build_mappings_server())
    return McpGateway(
        authenticator=JwtAuthenticator(_settings()),
        registry=registry,
        required_roles={
            TOOL_RESOLVE: Role.VIEWER,
            TOOL_GET_RELEASE: Role.VIEWER,
            TOOL_LIST_RELEASES: Role.VIEWER,
        },
    )


def test_resolve_an_approximate_mapping_carries_its_caveat() -> None:
    server = build_mappings_server()

    resolved = server.handle(
        TOOL_RESOLVE,
        {
            "mapping_version": "2026.11.2",
            "source_provider": "aws",
            "source_service": "s3",
            "target_provider": "gcp",
        },
        _principal(),
    )

    assert resolved.equivalence is Equivalence.APPROXIMATE
    assert resolved.caveat


def test_list_releases_and_get_release_return_real_data() -> None:
    server = build_mappings_server()

    releases = server.handle(TOOL_LIST_RELEASES, {}, _principal())
    assert releases
    one = releases[0]

    fetched = server.handle(TOOL_GET_RELEASE, {"version": one.version}, _principal())
    assert fetched.version == one.version


def test_resolve_an_unregistered_version_raises_mapping_unavailable() -> None:
    server = build_mappings_server()

    with pytest.raises(MappingUnavailableError):
        server.handle(
            TOOL_RESOLVE,
            {
                "mapping_version": "1999.01.1",
                "source_provider": "aws",
                "source_service": "s3",
                "target_provider": "gcp",
            },
            _principal(),
        )


def test_unknown_tool_name_raises() -> None:
    server = build_mappings_server()

    with pytest.raises(ValidationError):
        server.handle("mappings.publish", {}, _principal())


def test_unknown_argument_key_is_rejected() -> None:
    server = build_mappings_server()

    with pytest.raises(ValidationError):
        server.handle(TOOL_GET_RELEASE, {"version": "2026.11.2", "extra": "nope"}, _principal())


def test_caller_below_declared_role_gets_forbidden_before_the_handle_runs() -> None:
    gateway = _gateway()
    token = _token(roles=())

    with pytest.raises(ForbiddenError):
        gateway.call_tool(TOOL_LIST_RELEASES, token, {})
