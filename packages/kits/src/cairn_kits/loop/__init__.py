"""CAIRN cairn_kits.loop: the agent loop kit (ADR-019).

R6-01 adds the prompt registry; R6-02 adds the loop contract. Later R6
units add budgets and the propose-only tool-capability boundary in
this same package.
"""

from cairn_kits.loop.contract import (
    ALLOWED_AGENT_RUN_TRANSITIONS,
    AgentRun,
    AgentRunState,
    AgentSpec,
    AgentStep,
    StepKind,
    validate_agent_run_transition,
)
from cairn_kits.loop.prompt_lint import (
    DEFAULT_THRESHOLD,
    PromptLiteralViolation,
    find_prompt_literal_violations,
)
from cairn_kits.loop.prompt_registry import PromptArtifact, PromptRegistry

__all__ = [
    "ALLOWED_AGENT_RUN_TRANSITIONS",
    "AgentRun",
    "AgentRunState",
    "AgentSpec",
    "AgentStep",
    "DEFAULT_THRESHOLD",
    "PromptArtifact",
    "PromptLiteralViolation",
    "PromptRegistry",
    "StepKind",
    "find_prompt_literal_violations",
    "validate_agent_run_transition",
]
