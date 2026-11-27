"""CAIRN cairn_kits.mcp: the R5-04a MCP gateway registry (ADR-011).

One entry per bounded context's MCP server -- see ``registry.py`` for the
shape and ``apps/mcp-gateway`` for the authenticated gateway built on top
of it.
"""

from cairn_kits.mcp.capability import ToolCapability
from cairn_kits.mcp.registry import (
    BoundedContextServer,
    DuplicateToolRegistrationError,
    McpRegistry,
    ToolHandle,
    ToolNotRegisteredError,
    ToolRegistration,
)

__all__ = [
    "BoundedContextServer",
    "DuplicateToolRegistrationError",
    "McpRegistry",
    "ToolCapability",
    "ToolHandle",
    "ToolNotRegisteredError",
    "ToolRegistration",
]
