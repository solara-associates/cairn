"""R6-07: ``cairn_adapters.agent_adk`` -- the only package in this
repository that may import ``google.adk`` (A6.port, enforced by the
``adk-confined`` import-linter contract). Everything else reaches an
agent run through :class:`cairn_kits.loop.AgentLoopPort`, bound to
:class:`AdkAgentLoop` only in a composition root.
"""

from cairn_adapters.agent_adk.adapter import AdkAgentLoop, sanitize_tool_name

__all__ = ["AdkAgentLoop", "sanitize_tool_name"]
