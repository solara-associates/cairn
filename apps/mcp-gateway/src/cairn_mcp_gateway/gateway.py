"""The R5-04a MCP gateway: OAuth-based client authentication in front of
the shared ``cairn_kits.mcp`` registry (ADR-011: "the gateway handles
auth, per-tenant authorization, rate limits and audit").

This reuses R0-13's existing OIDC adapter (``cairn_adapters.auth_oidc``)
for token verification rather than reimplementing OAuth/JWT validation --
``JwtAuthenticator.verify`` already does the signature, issuer, audience
and claim-shape checks; this module only adds the gateway-specific
per-tool scope check on top.

Every call goes through ``McpGateway.call_tool``, which authenticates and
authorizes *before* ever touching the registry: an unauthenticated or
wrongly-scoped caller raises before ``McpRegistry.lookup``/``invoke`` is
reached, so a registered tool's handle never executes for a rejected
caller.

ADR-020 §3 adds a second way to authenticate at exactly that one step:
a caller may present a **VAID** (``cairn_kernel.vaid``), instead of or
in addition to a bearer token. It is a second implementation of the
same credential-in/``Principal``-out shape ``JwtAuthenticator`` already
fills -- not a parallel path -- so ``call_tool``'s ordering guarantee
(authenticate, then authorize, then and only then resolve/invoke) is
unchanged, and so is the behaviour of every caller that presents a
token and no VAID.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from cairn_adapters.auth_oidc import JwtAuthenticator
from cairn_kernel.errors import ForbiddenError, UnauthenticatedError
from cairn_kernel.governance import (
    GovernancePort,
    GovernanceRequest,
    NoOpGovernance,
    require_tool_call_allowed,
)
from cairn_kernel.security import Principal, Role
from cairn_kernel.vaid import VaidAuthenticator, VaidPresentation, VaidVerificationError
from cairn_kits.mcp import McpRegistry


@dataclass(frozen=True, slots=True)
class McpGateway:
    """Authenticates the caller's credential, checks the tool's required
    scope (expressed as a tenant ``Role``, same vocabulary R0-13's OIDC
    claims already carry), and only then resolves/invokes the tool
    through the registry.

    ``required_roles`` maps a tool name to the ``Role`` a principal must
    hold to call it. A tool with no entry requires only a valid,
    authenticated credential -- any principal may call it.

    ``vaid_authenticator`` is optional and defaults to ``None``: a
    deployment that accepts no VAID binds none, a caller presenting one
    is then refused for want of a pinned trust anchor, and callers
    presenting a bearer token are unaffected either way (ADR-020 §3).
    ``cairn_kernel.vaid.resolve_vaid_authenticator`` is what builds it
    where one is wanted.

    ``governance`` is the optional policy-substrate port (ADR-020 §4)
    and defaults to :class:`NoOpGovernance`, which allows every call and
    records nothing -- so the default path is byte-for-byte today's
    behaviour and CAIRN works fully with no governance adapter bound.
    """

    authenticator: JwtAuthenticator
    registry: McpRegistry
    required_roles: Mapping[str, Role] = field(default_factory=dict)
    vaid_authenticator: VaidAuthenticator | None = None
    governance: GovernancePort = field(default_factory=NoOpGovernance)

    def authenticate(
        self, token: str | None = None, *, vaid: VaidPresentation | None = None
    ) -> Principal:
        """Verify the presented credential(s) and return the calling
        ``Principal``.

        Three cases, and only three:

        - **token only** -- today's behaviour, byte for byte:
          ``JwtAuthenticator.verify``, raising
          ``cairn_kernel.errors.UnauthenticatedError`` for a missing,
          malformed, expired or otherwise invalid token.
        - **VAID only** -- ``VaidAuthenticator.verify``, returning the
          *narrowed* principal the credential itself carries.
        - **both** (ADR-020 §3's "in addition to") -- the token is
          verified first, and the VAID is then verified *against* the
          principal it proved: same tenant, and a subset of its roles.
          The narrowed VAID principal is what is returned. This is the
          case where "scope can only shrink" is checked against the
          authority backing the VAID, rather than only within the
          VAID's own chain.

        Either way the result is one ``Principal``, and nothing
        downstream can tell which credential produced it -- which is
        why a VAID cannot be a way around the role check below or the
        tenant checks in every bounded-context server (ADR-020 §2).
        """

        if vaid is None:
            if token is None:
                raise UnauthenticatedError("no credential was presented")
            return self.authenticator.verify(token)
        if self.vaid_authenticator is None:
            raise VaidVerificationError(
                "a VAID was presented but this deployment accepts none: no VAID trust anchor"
                " is configured, so there is nothing to verify it against"
            )
        backing_principal = self.authenticator.verify(token) if token else None
        return self.vaid_authenticator.verify(
            vaid, backing_principal=backing_principal
        ).principal

    def authorize(self, principal: Principal, tool_name: str) -> None:
        """Raise ``ForbiddenError`` if ``principal`` lacks the role
        ``tool_name`` requires. A tool with no declared requirement
        accepts any authenticated principal.
        """
        required_role = self.required_roles.get(tool_name)
        if required_role is not None and not principal.has_role(required_role):
            raise ForbiddenError(
                f"tool {tool_name!r} requires role {required_role.value!r}, principal"
                f" {principal.subject!r} holds {principal.role_values()!r}"
            )

    def call_tool(
        self,
        tool_name: str,
        token: str | None = None,
        arguments: Mapping[str, object] | None = None,
        *,
        vaid: VaidPresentation | None = None,
    ) -> object:
        """Authenticate, authorize, then resolve and invoke ``tool_name``.

        Order matters: authentication and the scope check both happen
        before ``McpRegistry.lookup``/``invoke`` is ever called, so a
        rejected caller's request never reaches a registered server's
        handle -- not even to discover whether the tool exists.

        ADR-020 §1/§2: the ``principal`` this method just authenticated is
        propagated into the handle itself via ``McpRegistry.invoke``,
        so every bounded-context server can enforce tenant scope
        against who the gateway actually authenticated, not a
        caller-supplied argument about itself.

        ADR-020 §3: ``vaid``, when given, is the credential that
        produces that principal (see :meth:`authenticate`). A refused
        VAID raises before ``authorize`` and therefore before the
        registry, exactly as a refused token already did.

        ADR-020 §4: the ``governance`` port is consulted after
        ``authorize`` and still before the registry. The order is not
        arbitrary -- governance is an *extra* layer that can only
        subtract authority, so CAIRN's own checks must have already
        passed before it is asked anything, and nothing it says can let
        a call through that ``authorize`` would have refused. With the
        default :class:`NoOpGovernance` bound this adds one allow and
        changes nothing.

        One consequence of needing the tool's declared capability to ask
        governance anything: ``lookup`` now runs before the governance
        call rather than inside ``invoke`` after it. The ordering
        guarantee that matters is intact -- an *unauthenticated or
        wrongly-scoped* caller still raises before the registry is
        touched at all. What changes is only that a caller who passed
        both of CAIRN's own checks and was then denied by an external
        policy substrate can tell the tool exists. No handle runs for
        them, and they were already authorized for that tool's required
        role, so there is nothing there they did not already know.
        """
        principal = self.authenticate(token, vaid=vaid)
        self.authorize(principal, tool_name)
        registration = self.registry.lookup(tool_name)
        require_tool_call_allowed(
            self.governance,
            GovernanceRequest.for_tool_call(
                principal=principal,
                tool_name=tool_name,
                capability=registration.capability.value,
                arguments=arguments,
            ),
        )
        return registration.invoke(principal, arguments)


__all__ = ["McpGateway"]
