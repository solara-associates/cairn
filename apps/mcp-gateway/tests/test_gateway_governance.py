"""ADR-020 §4: the MCP gateway consults the governance port, and the
default adapter changes nothing.

The two claims, at this seam:

1. With :class:`NoOpGovernance` bound -- the default, and what every
   other gateway test runs against -- behaviour is unchanged.
2. A test adapter can deny a call, and the denial lands *before the
   registry invokes anything*, so no handle runs for a denied caller.

And one ordering claim worth its own test: governance is asked **after**
CAIRN's own authentication and role check, never instead of them. It is
an extra layer that can only subtract authority, so nothing bound there
can let through a call ``authorize`` would have refused.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cairn_adapters.auth_oidc import JwtAuthenticator, OidcSettings
from cairn_kernel.errors import ForbiddenError, UnauthenticatedError
from cairn_kernel.governance import (
    GovernanceCheck,
    GovernanceDecision,
    GovernanceDeniedError,
    GovernanceRequest,
    NoOpGovernance,
)
from cairn_kernel.security import Principal, Role
from cairn_kits.mcp import BoundedContextServer, McpRegistry, ToolNotRegisteredError
from cairn_kits.mcp.capability import ToolCapability
from cairn_mcp_gateway import McpGateway

ISSUER = "https://auth.example.cairn/"
AUDIENCE = "cairn-mcp-gateway"
SECRET = "unit-test-secret-does-not-leave-this-process"
TENANT = str(uuid.uuid4())
TOOL = "fixture.read_only_thing"


def _settings() -> OidcSettings:
    return OidcSettings(issuer=ISSUER, audience=AUDIENCE, algorithms=("HS256",), secret=SECRET)


def _token(*, roles: tuple[str, ...] = (Role.AUDITOR.value,)) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "user-1",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "tenant_id": TENANT,
            "roles": list(roles),
        },
        SECRET,
        algorithm="HS256",
    )


class SpyGovernance(NoOpGovernance):
    """Allows everything and records what it was asked, or denies the
    named check."""

    def __init__(self, *, deny: GovernanceCheck | None = None) -> None:
        self.requests: list[GovernanceRequest] = []
        self.recorded: list[GovernanceDecision] = []
        self._deny = deny

    def check_revocation(self, request: GovernanceRequest) -> GovernanceDecision:
        return self._answer(GovernanceCheck.REVOCATION, request)

    def check_policy(self, request: GovernanceRequest) -> GovernanceDecision:
        return self._answer(GovernanceCheck.POLICY, request)

    def check_budget(self, request: GovernanceRequest) -> GovernanceDecision:
        return self._answer(GovernanceCheck.BUDGET, request)

    def record(self, request: GovernanceRequest, decision: GovernanceDecision) -> None:
        del request
        self.recorded.append(decision)

    def _answer(
        self, check: GovernanceCheck, request: GovernanceRequest
    ) -> GovernanceDecision:
        self.requests.append(request)
        if self._deny is check:
            return GovernanceDecision.deny(check, reason="over the tenant's ceiling")
        return GovernanceDecision.allow(check)


def _gateway(governance: object | None = None) -> tuple[McpGateway, list[str]]:
    calls: list[str] = []

    def handle(name: str, arguments: dict, principal: Principal) -> object:
        del arguments, principal
        calls.append(name)
        return {"ok": True}

    registry = McpRegistry()
    registry.register(
        BoundedContextServer(
            context_id="fixture",
            name="fixture",
            tools=(TOOL,),
            capabilities={TOOL: ToolCapability.READ},
            handle=handle,
        )
    )
    kwargs = {} if governance is None else {"governance": governance}
    gateway = McpGateway(
        authenticator=JwtAuthenticator(_settings()),
        registry=registry,
        required_roles={TOOL: Role.AUDITOR},
        **kwargs,  # type: ignore[arg-type]
    )
    return gateway, calls


# -- the default changes nothing --------------------------------------


def test_the_default_governance_is_the_no_op_adapter() -> None:
    gateway, _ = _gateway()

    assert isinstance(gateway.governance, NoOpGovernance)


def test_an_authorized_call_succeeds_unchanged_with_the_default() -> None:
    gateway, calls = _gateway()

    assert gateway.call_tool(TOOL, _token(), {"x": 1}) == {"ok": True}
    assert calls == [TOOL]


def test_an_authorized_call_succeeds_unchanged_with_an_allowing_adapter() -> None:
    governance = SpyGovernance()
    gateway, calls = _gateway(governance)

    assert gateway.call_tool(TOOL, _token()) == {"ok": True}
    assert calls == [TOOL]
    assert len(governance.recorded) == 1
    assert governance.recorded[0].allowed


# -- a test adapter can deny ------------------------------------------


@pytest.mark.parametrize(
    "denied_check",
    [GovernanceCheck.REVOCATION, GovernanceCheck.POLICY, GovernanceCheck.BUDGET],
)
def test_a_denied_call_never_reaches_the_tools_handle(
    denied_check: GovernanceCheck,
) -> None:
    governance = SpyGovernance(deny=denied_check)
    gateway, calls = _gateway(governance)

    with pytest.raises(GovernanceDeniedError) as exc_info:
        gateway.call_tool(TOOL, _token())

    assert "over the tenant's ceiling" in str(exc_info.value)
    assert denied_check.value in str(exc_info.value)
    assert calls == []


# -- governance is asked after CAIRN's own checks, never instead ------


def test_governance_is_not_consulted_for_an_unauthenticated_caller() -> None:
    """Authentication runs first, so a caller with no valid credential
    is refused without an external system ever being told about it."""

    governance = SpyGovernance()
    gateway, calls = _gateway(governance)

    with pytest.raises(UnauthenticatedError):
        gateway.call_tool(TOOL, "not-a-real-jwt")

    assert governance.requests == []
    assert calls == []


def test_governance_is_not_consulted_for_a_wrongly_scoped_caller() -> None:
    governance = SpyGovernance()
    gateway, calls = _gateway(governance)

    with pytest.raises(ForbiddenError):
        gateway.call_tool(TOOL, _token(roles=(Role.VIEWER.value,)))

    assert governance.requests == []
    assert calls == []


def test_an_allowing_adapter_cannot_rescue_a_wrongly_scoped_caller() -> None:
    """The port can only ever subtract authority. An adapter that allows
    everything still cannot get a caller past ``authorize``."""

    gateway, calls = _gateway(NoOpGovernance())

    with pytest.raises(ForbiddenError):
        gateway.call_tool(TOOL, _token(roles=(Role.VIEWER.value,)))

    assert calls == []


def test_an_unregistered_tool_still_fails_cleanly_before_governance() -> None:
    governance = SpyGovernance()
    gateway, calls = _gateway(governance)

    with pytest.raises(ToolNotRegisteredError):
        gateway.call_tool("does.not.exist", _token())

    assert governance.requests == []
    assert calls == []


# -- what the port is actually told ------------------------------------


def test_the_request_carries_the_authenticated_principal_and_the_tools_capability() -> None:
    """The capability is why ``lookup`` runs before the governance call:
    ``READ`` versus ``PROPOSE`` is the single most useful thing a policy
    substrate can be told about a tool call, and the registry is the
    only place that knows it."""

    governance = SpyGovernance()
    gateway, _ = _gateway(governance)

    gateway.call_tool(TOOL, _token(), {"assessment_run_id": "run-1"})

    request = governance.requests[0]
    assert request.tenant_id == TENANT
    assert request.actor == "user-1"
    assert request.actor_roles == (Role.AUDITOR.value,)
    assert request.tool_name == TOOL
    assert request.capability == ToolCapability.READ.value
    assert request.arguments == {"assessment_run_id": "run-1"}
