"""R5-04a: the MCP gateway's registry (ADR-011).

ADR-011 puts one MCP server per bounded context behind a single gateway
registry rather than one mega-server. This module is that registry: a
shared kit any bounded context can register a server into, and the
gateway (``apps/mcp-gateway``) resolves tool lookups against.

Deliberately thin for this unit: a ``BoundedContextServer`` carries the
bounded-context id/name, the tool names it exposes, and a ``handle`` --
an in-process callable for now (ADR-011: internal-only until the A2A
bridge lands in R5-04b/819). No real network server is required for this
unit's tests; a later unit can swap the handle for a real transport
without changing this registry's shape. R6-05 adds ``capabilities``:
every tool's declared :class:`~cairn_kits.mcp.capability.ToolCapability`,
carried through ``McpRegistry.lookup``/``capability_of`` so
``AgentSpec.build()`` (``cairn_kits.loop``) can enforce the propose-only
boundary without this registry knowing anything about agents.

``cairn_kits`` may not import ``cairn_adapters`` or ``cairn_modules``
(see ``.importlinter``'s ``kits-purity`` contract), so authentication and
any real bounded-context wiring live in ``apps/mcp-gateway`` instead --
this module only knows how to register and resolve, never how to
authenticate a caller or what a specific tool actually does.

ADR-020 adds the authenticated :class:`~cairn_kernel.security.Principal`
as a required third argument to every ``ToolHandle``, propagated from
``McpGateway.call_tool`` (which already authenticates before this
registry is ever reached) through ``McpRegistry.invoke``/
``ToolRegistration.invoke``. A handler needs this to enforce tenant
scope against who the gateway actually authenticated, rather than a
caller-supplied argument about itself -- see that ADR for the gap this
closes. ``cairn_kits`` may import ``cairn_kernel`` freely
(``kits-purity`` only forbids ``cairn_adapters``/``cairn_modules``), so
this is not a purity violation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from cairn_kernel.errors import NotFoundError
from cairn_kernel.security import Principal

from cairn_kits.mcp.capability import ToolCapability

#: A bounded-context server's handle: given the tool name being invoked,
#: its arguments, and the gateway's authenticated caller, produce the
#: result. One handle may serve several tool names (one MCP server,
#: several tools), matching ADR-011's "one server per bounded context"
#: shape.
ToolHandle = Callable[[str, Mapping[str, object], Principal], object]


class ToolNotRegisteredError(NotFoundError):
    """Raised when a lookup names a tool no bounded-context server exposes.

    A named, specific error rather than a silent ``None`` -- the registry
    must fail cleanly for an unregistered tool, not pretend one exists.
    """

    title = "MCP tool not registered"


class DuplicateToolRegistrationError(ValueError):
    """Raised when two different bounded contexts claim the same tool name."""


@dataclass(frozen=True, slots=True)
class BoundedContextServer:
    """One MCP server per bounded context (ADR-011).

    ``capabilities`` (R6-05) declares every tool's :class:`ToolCapability`
    -- exactly the tools in ``tools``, no more, no fewer, so a tool
    cannot be registered with no declared capability (a silent default
    would be exactly the hole R-AGENT-03 exists to close).
    """

    context_id: str
    name: str
    tools: tuple[str, ...]
    capabilities: Mapping[str, ToolCapability]
    handle: ToolHandle

    def __post_init__(self) -> None:
        if not self.context_id.strip():
            raise ValueError("context_id is required")
        if not self.name.strip():
            raise ValueError("name is required")
        if not self.tools:
            raise ValueError(
                f"bounded-context server {self.context_id!r} must expose at least one tool"
            )
        if len(set(self.tools)) != len(self.tools):
            raise ValueError(
                f"bounded-context server {self.context_id!r} lists a duplicate tool name"
            )
        missing = set(self.tools) - set(self.capabilities)
        if missing:
            raise ValueError(
                f"bounded-context server {self.context_id!r} has no declared capability for: "
                f"{sorted(missing)}"
            )
        extra = set(self.capabilities) - set(self.tools)
        if extra:
            raise ValueError(
                f"bounded-context server {self.context_id!r} declares a capability for a tool "
                f"it does not expose: {sorted(extra)}"
            )


@dataclass(frozen=True, slots=True)
class ToolRegistration:
    """A resolved registry entry: which server a tool name belongs to,
    and that tool's declared capability (carried through from
    ``BoundedContextServer.capabilities``)."""

    tool_name: str
    server: BoundedContextServer

    @property
    def capability(self) -> ToolCapability:
        return self.server.capabilities[self.tool_name]

    def invoke(self, principal: Principal, arguments: Mapping[str, object] | None = None) -> object:
        return self.server.handle(self.tool_name, dict(arguments or {}), principal)


@dataclass(slots=True)
class McpRegistry:
    """Resolves a tool name to the bounded-context server that exposes it."""

    _servers: dict[str, BoundedContextServer] = field(default_factory=dict)
    _tool_index: dict[str, str] = field(default_factory=dict)

    def register(self, server: BoundedContextServer) -> None:
        for tool_name in server.tools:
            owner = self._tool_index.get(tool_name)
            if owner is not None and owner != server.context_id:
                raise DuplicateToolRegistrationError(
                    f"tool {tool_name!r} is already registered to bounded context {owner!r},"
                    f" cannot also register it to {server.context_id!r}"
                )
        self._servers[server.context_id] = server
        for tool_name in server.tools:
            self._tool_index[tool_name] = server.context_id

    def lookup(self, tool_name: str) -> ToolRegistration:
        context_id = self._tool_index.get(tool_name)
        if context_id is None:
            raise ToolNotRegisteredError(f"no bounded-context server exposes tool {tool_name!r}")
        return ToolRegistration(tool_name=tool_name, server=self._servers[context_id])

    def invoke(
        self,
        tool_name: str,
        principal: Principal,
        arguments: Mapping[str, object] | None = None,
    ) -> object:
        return self.lookup(tool_name).invoke(principal, arguments)

    def capability_of(self, tool_name: str) -> ToolCapability:
        return self.lookup(tool_name).capability

    def servers(self) -> tuple[BoundedContextServer, ...]:
        return tuple(self._servers.values())

    def tool_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tool_index))


__all__ = [
    "BoundedContextServer",
    "DuplicateToolRegistrationError",
    "McpRegistry",
    "ToolHandle",
    "ToolNotRegisteredError",
    "ToolRegistration",
]
