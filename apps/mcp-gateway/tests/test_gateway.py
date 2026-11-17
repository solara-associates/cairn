"""R5-04a: the MCP gateway's OAuth-based client authentication in front of
the registry.

Reuses R0-13's existing OIDC adapter (``cairn_adapters.auth_oidc``) for
token verification -- these tests build real signed JWTs with ``pyjwt``
the same way ``apps/api``'s own OIDC tests do, rather than faking out the
verifier.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cairn_adapters.auth_oidc import JwtAuthenticator, OidcSettings
from cairn_kernel.errors import ControlUnavailableError, ForbiddenError, UnauthenticatedError
from cairn_kernel.security import Role
from cairn_kits.mcp import BoundedContextServer, McpRegistry, ToolNotRegisteredError
from cairn_mcp_gateway import (
    TOOL_GET_CONTROL,
    McpGateway,
    build_default_registry,
    build_posture_server,
)
from cairn_mcp_gateway.registry_factory import REQUIRED_ROLES

ISSUER = "https://auth.example.cairn/"
AUDIENCE = "cairn-mcp-gateway"
SECRET = "unit-test-secret-does-not-leave-this-process"
TENANT_ID = str(uuid.uuid4())


def _settings() -> OidcSettings:
    return OidcSettings(
        issuer=ISSUER,
        audience=AUDIENCE,
        algorithms=("HS256",),
        secret=SECRET,
    )


def _token(*, roles: tuple[str, ...] = (), subject: str = "user-1") -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "tenant_id": TENANT_ID,
        "roles": list(roles),
    }
    return jwt.encode(claims, SECRET, algorithm="HS256")


def _counting_server(tool_name: str) -> tuple[BoundedContextServer, list[tuple[str, dict]]]:
    calls: list[tuple[str, dict]] = []

    def handle(name: str, arguments: dict) -> object:
        calls.append((name, dict(arguments)))
        return {"ok": True}

    server = BoundedContextServer(
        context_id="fixture", name="fixture", tools=(tool_name,), handle=handle
    )
    return server, calls


@pytest.fixture
def gateway_and_calls() -> tuple[McpGateway, list[tuple[str, dict]]]:
    registry = McpRegistry()
    server, calls = _counting_server("fixture.read_only_thing")
    registry.register(server)
    authenticator = JwtAuthenticator(_settings())
    gateway = McpGateway(
        authenticator=authenticator,
        registry=registry,
        required_roles={"fixture.read_only_thing": Role.AUDITOR},
    )
    return gateway, calls


def test_missing_token_is_rejected_before_any_registered_tool_executes(
    gateway_and_calls: tuple[McpGateway, list[tuple[str, dict]]],
) -> None:
    gateway, calls = gateway_and_calls

    with pytest.raises(UnauthenticatedError):
        gateway.call_tool("fixture.read_only_thing", "")

    assert calls == []


def test_garbage_token_is_rejected_before_any_registered_tool_executes(
    gateway_and_calls: tuple[McpGateway, list[tuple[str, dict]]],
) -> None:
    gateway, calls = gateway_and_calls

    with pytest.raises(UnauthenticatedError):
        gateway.call_tool("fixture.read_only_thing", "not-a-real-jwt")

    assert calls == []


def test_wrongly_scoped_token_is_rejected_before_any_registered_tool_executes(
    gateway_and_calls: tuple[McpGateway, list[tuple[str, dict]]],
) -> None:
    gateway, calls = gateway_and_calls
    token = _token(roles=(Role.VIEWER.value,))

    with pytest.raises(ForbiddenError):
        gateway.call_tool("fixture.read_only_thing", token)

    assert calls == []


def test_correctly_scoped_token_reaches_the_registered_tool(
    gateway_and_calls: tuple[McpGateway, list[tuple[str, dict]]],
) -> None:
    gateway, calls = gateway_and_calls
    token = _token(roles=(Role.AUDITOR.value,))

    result = gateway.call_tool("fixture.read_only_thing", token, {"x": 1})

    assert result == {"ok": True}
    assert calls == [("fixture.read_only_thing", {"x": 1})]


def test_unregistered_tool_fails_cleanly_even_with_a_valid_token(
    gateway_and_calls: tuple[McpGateway, list[tuple[str, dict]]],
) -> None:
    gateway, calls = gateway_and_calls
    token = _token(roles=(Role.AUDITOR.value,))

    with pytest.raises(ToolNotRegisteredError):
        gateway.call_tool("does.not.exist", token)

    assert calls == []


def test_posture_get_control_is_a_real_registered_capability_not_a_fixture() -> None:
    """The unit's own proof: the posture module's real control catalogue,
    resolved end to end through authentication, authorization and the
    registry -- no fake/mock bounded-context server involved."""
    registry = build_default_registry()
    authenticator = JwtAuthenticator(_settings())
    gateway = McpGateway(
        authenticator=authenticator, registry=registry, required_roles=REQUIRED_ROLES
    )
    token = _token(roles=(Role.AUDITOR.value,))

    control = gateway.call_tool(
        TOOL_GET_CONTROL,
        token,
        {"version": "2026.11.1", "control_id": "gcp-cis-5.1"},
    )

    assert control.title.startswith("Ensure that Cloud Storage buckets")


def test_posture_get_control_still_requires_its_scope() -> None:
    registry = build_default_registry()
    authenticator = JwtAuthenticator(_settings())
    gateway = McpGateway(
        authenticator=authenticator, registry=registry, required_roles=REQUIRED_ROLES
    )
    token = _token(roles=(Role.VIEWER.value,))

    with pytest.raises(ForbiddenError):
        gateway.call_tool(
            TOOL_GET_CONTROL, token, {"version": "2026.11.1", "control_id": "gcp-cis-5.1"}
        )


def test_build_posture_server_rejects_an_unknown_control_cleanly() -> None:
    server = build_posture_server()

    with pytest.raises(ControlUnavailableError):
        server.handle(TOOL_GET_CONTROL, {"version": "2026.11.1", "control_id": "does-not-exist"})
