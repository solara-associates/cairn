"""Wires this unit's real bounded-context registrations into one
``McpRegistry``, and the scope each tool requires through
``McpGateway``.

Internal-only per ADR-011: no real network MCP server runs, and no
external agent host is wired up in this unit (that's R5-04b/819's A2A
bridge).
"""

from __future__ import annotations

from cairn_kernel.security import Role
from cairn_kits.mcp import McpRegistry

from cairn_mcp_gateway.posture_server import TOOL_GET_CONTROL, build_posture_server

#: Scope required to call each registered tool, by tool name. A control
#: catalogue entry is read-only but still compliance-sensitive content,
#: so this unit requires at least AUDITOR (the lowest role R0's taxonomy
#: grants read access to control/compliance data under) rather than
#: leaving it open to any authenticated VIEWER -- a judgement call, not
#: a fact handed down by ADR-011, which only says the gateway "handles
#: auth, per-tenant authorization".
REQUIRED_ROLES: dict[str, Role] = {
    TOOL_GET_CONTROL: Role.AUDITOR,
}


def build_default_registry() -> McpRegistry:
    """Build the registry this unit proves: the posture bounded
    context's ``posture.get_control`` tool, and nothing else yet."""
    registry = McpRegistry()
    registry.register(build_posture_server())
    return registry


__all__ = ["REQUIRED_ROLES", "build_default_registry"]
