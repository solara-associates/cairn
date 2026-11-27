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
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from cairn_adapters.auth_oidc import JwtAuthenticator
from cairn_kernel.errors import ForbiddenError
from cairn_kernel.security import Principal, Role
from cairn_kits.mcp import McpRegistry


@dataclass(frozen=True, slots=True)
class McpGateway:
    """Authenticates a bearer token, checks the tool's required scope
    (expressed as a tenant ``Role``, same vocabulary R0-13's OIDC claims
    already carry), and only then resolves/invokes the tool through the
    registry.

    ``required_roles`` maps a tool name to the ``Role`` a principal must
    hold to call it. A tool with no entry requires only a valid,
    authenticated token -- any principal may call it.
    """

    authenticator: JwtAuthenticator
    registry: McpRegistry
    required_roles: Mapping[str, Role] = field(default_factory=dict)

    def authenticate(self, token: str) -> Principal:
        """Verify ``token`` and return the calling ``Principal``.

        Raises ``cairn_kernel.errors.UnauthenticatedError`` (via
        ``JwtAuthenticator.verify``) for a missing, malformed, expired or
        otherwise invalid token -- before any registry lookup happens.
        """
        return self.authenticator.verify(token)

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
        token: str,
        arguments: Mapping[str, object] | None = None,
    ) -> object:
        """Authenticate, authorize, then resolve and invoke ``tool_name``.

        Order matters: authentication and the scope check both happen
        before ``McpRegistry.lookup``/``invoke`` is ever called, so a
        rejected caller's request never reaches a registered server's
        handle -- not even to discover whether the tool exists.

        ADR-020: the ``principal`` this method just authenticated is
        propagated into the handle itself via ``McpRegistry.invoke``,
        so every bounded-context server can enforce tenant scope
        against who the gateway actually authenticated, not a
        caller-supplied argument about itself.
        """
        principal = self.authenticate(token)
        self.authorize(principal, tool_name)
        return self.registry.invoke(tool_name, principal, arguments)


__all__ = ["McpGateway"]
