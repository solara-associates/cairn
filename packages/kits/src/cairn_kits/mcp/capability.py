"""R6-05: tool capabilities (ADR-019 §1/§4.2).

Every tool a ``BoundedContextServer`` exposes is either ``READ`` (looks
something up, changes nothing) or ``PROPOSE`` (writes CAIRN's own
candidate-artefact rows -- a Class A/B operation against CAIRN's own
store, already audited, never a customer resource). There is no third
value here on purpose: a tool that mutates a customer resource, applies,
approves or executes anything has no place in this enum, and therefore
no way to declare itself safe for an agent's toolset (``AgentSpec``
rejects any tool whose capability is not one of these two, at
construction -- see ``cairn_kits.loop.contract``).
"""

from __future__ import annotations

from enum import Enum


class ToolCapability(str, Enum):
    READ = "READ"
    PROPOSE = "PROPOSE"


__all__ = ["ToolCapability"]
