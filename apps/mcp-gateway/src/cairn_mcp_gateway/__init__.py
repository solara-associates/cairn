"""CAIRN cairn-mcp-gateway: R5-04a/b's MCP gateway + A2A bridge (ADR-011).

One registry (``cairn_kits.mcp``) resolving a tool name to its
bounded-context server, behind OAuth-based client authentication that
reuses R0-13's existing OIDC adapter (``cairn_adapters.auth_oidc``), plus
an A2A bridge (``a2a_bridge``) that publishes agent cards for the same
registered servers and translates A2A task messages onto the same
gateway. Internal-only for both units -- no real network server, no
external agent host wired up (ADR-011: MCP/A2A are internal until R5).
"""

from cairn_mcp_gateway.a2a_bridge import (
    A2ABridge,
    A2AMessage,
    A2AResult,
    AgentCard,
    a2a_message_to_mcp_call,
    a2a_result_to_mcp_result,
    agent_card_for,
    agent_cards_for_registry,
    mcp_call_to_a2a_message,
    mcp_result_to_a2a_result,
)
from cairn_mcp_gateway.estate_server import (
    TOOL_GET_DEPENDENCIES,
    TOOL_GET_WORKLOAD,
    TOOL_LIST_RESOURCES,
    TOOL_LIST_WORKLOADS,
    build_estate_server,
)
from cairn_mcp_gateway.gateway import McpGateway
from cairn_mcp_gateway.mappings_server import (
    TOOL_GET_RELEASE,
    TOOL_LIST_RELEASES,
    TOOL_RESOLVE,
    build_mappings_server,
)
from cairn_mcp_gateway.posture_server import TOOL_GET_CONTROL, build_posture_server
from cairn_mcp_gateway.registry_factory import REQUIRED_ROLES, build_default_registry

__all__ = [
    "REQUIRED_ROLES",
    "TOOL_GET_CONTROL",
    "TOOL_GET_DEPENDENCIES",
    "TOOL_GET_RELEASE",
    "TOOL_GET_WORKLOAD",
    "TOOL_LIST_RELEASES",
    "TOOL_LIST_RESOURCES",
    "TOOL_LIST_WORKLOADS",
    "TOOL_RESOLVE",
    "A2ABridge",
    "A2AMessage",
    "A2AResult",
    "AgentCard",
    "McpGateway",
    "a2a_message_to_mcp_call",
    "a2a_result_to_mcp_result",
    "agent_card_for",
    "agent_cards_for_registry",
    "build_default_registry",
    "build_estate_server",
    "build_mappings_server",
    "build_posture_server",
    "mcp_call_to_a2a_message",
    "mcp_result_to_a2a_result",
]
