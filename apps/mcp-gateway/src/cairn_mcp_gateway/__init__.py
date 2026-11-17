"""CAIRN cairn-mcp-gateway: R5-04a's MCP gateway (ADR-011).

One registry (``cairn_kits.mcp``) resolving a tool name to its
bounded-context server, behind OAuth-based client authentication that
reuses R0-13's existing OIDC adapter (``cairn_adapters.auth_oidc``).
Internal-only for this unit -- no real network server, no external agent
host wired up (that's R5-04b/819's A2A bridge).
"""

from cairn_mcp_gateway.gateway import McpGateway
from cairn_mcp_gateway.posture_server import TOOL_GET_CONTROL, build_posture_server
from cairn_mcp_gateway.registry_factory import REQUIRED_ROLES, build_default_registry

__all__ = [
    "REQUIRED_ROLES",
    "TOOL_GET_CONTROL",
    "McpGateway",
    "build_default_registry",
    "build_posture_server",
]
