"""R5-04b: conformance tests proving every registered ``BoundedContextServer``
is reachable through both 818's MCP gateway path and this unit's A2A bridge
path, with identical results -- and that an unregistered tool/agent is
unreachable through *either* path, with the same failure semantics.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cairn_adapters.auth_oidc import JwtAuthenticator, OidcSettings
from cairn_kernel.security import Role
from cairn_kits.mcp import BoundedContextServer, McpRegistry, ToolNotRegisteredError
from cairn_mcp_gateway import (
    TOOL_GET_CONTROL,
    A2ABridge,
    McpGateway,
    build_default_registry,
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


@pytest.fixture
def default_gateway_and_bridge() -> tuple[McpGateway, A2ABridge]:
    """818's real registration (``posture.get_control``) wired through
    both paths, sharing the same registry/authenticator -- exactly as
    they would be in the deployed gateway."""
    registry = build_default_registry()
    authenticator = JwtAuthenticator(_settings())
    gateway = McpGateway(
        authenticator=authenticator, registry=registry, required_roles=REQUIRED_ROLES
    )
    bridge = A2ABridge(gateway=gateway)
    return gateway, bridge


def test_every_registered_server_is_reachable_through_both_paths_identically(
    default_gateway_and_bridge: tuple[McpGateway, A2ABridge],
) -> None:
    """The conformance proof: for every bounded-context server currently
    registered, calling its tool through the MCP gateway and through the
    A2A bridge (agent card -> translated task) produces an identical
    result -- exercised here against the one real proof registration,
    ``posture.get_control``, and written to generalise over whatever is
    registered rather than hardcoding a server count."""
    gateway, bridge = default_gateway_and_bridge
    token = _token(roles=(Role.AUDITOR.value,))
    arguments = {"version": "2026.11.1", "control_id": "gcp-cis-5.1"}

    checked_any = False
    for card in bridge.agent_cards():
        for tool_name in card.skills:
            mcp_result = gateway.call_tool(tool_name, token, arguments)
            a2a_result = bridge.send_task(
                agent_id=card.agent_id, skill=tool_name, token=token, input=arguments
            )

            assert a2a_result.output == mcp_result
            checked_any = True

    assert checked_any, "expected at least one registered server to exercise"


def test_posture_get_control_matches_exactly_between_mcp_and_a2a_paths(
    default_gateway_and_bridge: tuple[McpGateway, A2ABridge],
) -> None:
    """Belt-and-suspenders: the specific proof registration named in the
    brief, asserted explicitly rather than only via the generalised loop
    above."""
    gateway, bridge = default_gateway_and_bridge
    token = _token(roles=(Role.AUDITOR.value,))
    arguments = {"version": "2026.11.1", "control_id": "gcp-cis-5.1"}

    mcp_control = gateway.call_tool(TOOL_GET_CONTROL, token, arguments)
    a2a_result = bridge.send_task(
        agent_id="posture", skill=TOOL_GET_CONTROL, token=token, input=arguments
    )

    assert a2a_result.output == mcp_control
    assert a2a_result.output.title.startswith("Ensure that Cloud Storage buckets")


def test_a2a_bridge_still_enforces_the_gateways_scope_check(
    default_gateway_and_bridge: tuple[McpGateway, A2ABridge],
) -> None:
    """The A2A path must not become a side door around 818's
    authorization: a wrongly-scoped token is rejected on the A2A path
    exactly as it is on the MCP path (same ``ForbiddenError``, raised by
    the shared ``McpGateway.call_tool`` underneath both)."""
    from cairn_kernel.errors import ForbiddenError

    _gateway, bridge = default_gateway_and_bridge
    token = _token(roles=(Role.VIEWER.value,))

    with pytest.raises(ForbiddenError):
        bridge.send_task(
            agent_id="posture",
            skill=TOOL_GET_CONTROL,
            token=token,
            input={"version": "2026.11.1", "control_id": "gcp-cis-5.1"},
        )


def test_unregistered_tool_is_unreachable_through_the_mcp_path(
    default_gateway_and_bridge: tuple[McpGateway, A2ABridge],
) -> None:
    gateway, _bridge = default_gateway_and_bridge
    token = _token(roles=(Role.AUDITOR.value,))

    with pytest.raises(ToolNotRegisteredError):
        gateway.call_tool("does.not.exist", token)


def test_unregistered_tool_is_unreachable_through_the_a2a_path_same_error(
    default_gateway_and_bridge: tuple[McpGateway, A2ABridge],
) -> None:
    """Deliberate-break test: an unregistered tool/agent must fail on the
    A2A path too, with the *same* ``ToolNotRegisteredError`` the MCP
    gateway raises -- not a silent default, not a different error type
    that would let a caller branch on protocol instead of on "is this
    actually registered"."""
    _gateway, bridge = default_gateway_and_bridge
    token = _token(roles=(Role.AUDITOR.value,))

    with pytest.raises(ToolNotRegisteredError):
        bridge.send_task(agent_id="does-not-exist", skill="does.not.exist", token=token, input={})


def test_unregistered_agent_with_a_real_skill_name_is_still_unreachable_via_a2a(
    default_gateway_and_bridge: tuple[McpGateway, A2ABridge],
) -> None:
    """A caller cannot sidestep agent-card identity by naming a real
    skill but claiming the wrong agent -- the bridge must check both,
    not just whether *some* agent happens to expose the skill."""
    _gateway, bridge = default_gateway_and_bridge
    token = _token(roles=(Role.AUDITOR.value,))

    with pytest.raises(ToolNotRegisteredError):
        bridge.send_task(
            agent_id="not-the-posture-context",
            skill=TOOL_GET_CONTROL,
            token=token,
            input={"version": "2026.11.1", "control_id": "gcp-cis-5.1"},
        )


def test_unregistered_server_is_unreachable_through_either_path_fresh_registry() -> None:
    """Belt-and-suspenders at the registry level, independent of the
    default registration: build a registry with exactly one server, then
    prove a *different*, never-registered tool/agent is rejected with
    the same error through both the MCP gateway and the A2A bridge built
    on top of it."""
    registry = McpRegistry()

    def handle(tool_name: str, arguments: dict) -> object:
        return {"tool": tool_name, "arguments": arguments}

    registry.register(
        BoundedContextServer(
            context_id="fixture", name="fixture", tools=("fixture.read_only_thing",), handle=handle
        )
    )
    authenticator = JwtAuthenticator(_settings())
    gateway = McpGateway(
        authenticator=authenticator,
        registry=registry,
        required_roles={"fixture.read_only_thing": Role.AUDITOR},
    )
    bridge = A2ABridge(gateway=gateway)
    token = _token(roles=(Role.AUDITOR.value,))

    with pytest.raises(ToolNotRegisteredError):
        gateway.call_tool("fixture.never_registered", token)

    with pytest.raises(ToolNotRegisteredError):
        bridge.send_task(
            agent_id="fixture", skill="fixture.never_registered", token=token, input={}
        )

    with pytest.raises(ToolNotRegisteredError):
        bridge.send_task(
            agent_id="never-registered-agent",
            skill="fixture.read_only_thing",
            token=token,
            input={},
        )
