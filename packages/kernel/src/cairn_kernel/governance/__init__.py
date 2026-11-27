"""CAIRN cairn_kernel.governance: the optional policy-substrate port
(ADR-020 §4), with a no-op default adapter.

No client, SDK or commercial code for any external governance system
exists in this repository. See ``ports.py``'s docstring.
"""

from cairn_kernel.governance.ports import (
    GovernanceCheck,
    GovernanceDecision,
    GovernanceDeniedError,
    GovernanceOutcome,
    GovernancePort,
    GovernanceRequest,
    NoOpGovernance,
    evaluate_tool_call,
    require_tool_call_allowed,
)

__all__ = [
    "GovernanceCheck",
    "GovernanceDecision",
    "GovernanceDeniedError",
    "GovernanceOutcome",
    "GovernancePort",
    "GovernanceRequest",
    "NoOpGovernance",
    "evaluate_tool_call",
    "require_tool_call_allowed",
]
