"""CAIRN cairn_kits.loop: the agent loop kit (ADR-019).

R6-01 adds the prompt registry; R6-02 adds the loop contract; R6-03
adds run budgets and the budget ledger; R6-05 adds the propose-only
tool-capability boundary; R6-11a adds the proposal channel an agent's
output actually travels on (``AgentSpec.output_schema``,
``AgentRun.proposal``, ``complete_with_proposal``).
"""

from cairn_kits.loop.budget import BudgetDebitResult, BudgetDimension, BudgetLedger, RunBudget
from cairn_kits.loop.contract import (
    ALLOWED_AGENT_RUN_TRANSITIONS,
    AgentRun,
    AgentRunState,
    AgentSpec,
    AgentStep,
    StepKind,
    complete_with_proposal,
    validate_agent_run_transition,
)
from cairn_kits.loop.deterministic import DeterministicAgentLoop
from cairn_kits.loop.ports import (
    AgentLoopPort,
    AgentRunContext,
    InMemoryStepRecorder,
    StepRecorder,
    ToolInvokerPort,
)
from cairn_kits.loop.prompt_lint import (
    DEFAULT_THRESHOLD,
    PromptLiteralViolation,
    find_prompt_literal_violations,
)
from cairn_kits.loop.prompt_registry import PromptArtifact, PromptRegistry

__all__ = [
    "ALLOWED_AGENT_RUN_TRANSITIONS",
    "DEFAULT_THRESHOLD",
    "AgentLoopPort",
    "AgentRun",
    "AgentRunContext",
    "AgentRunState",
    "AgentSpec",
    "AgentStep",
    "BudgetDebitResult",
    "BudgetDimension",
    "BudgetLedger",
    "DeterministicAgentLoop",
    "InMemoryStepRecorder",
    "PromptArtifact",
    "PromptLiteralViolation",
    "PromptRegistry",
    "RunBudget",
    "StepKind",
    "StepRecorder",
    "ToolInvokerPort",
    "complete_with_proposal",
    "find_prompt_literal_violations",
    "validate_agent_run_transition",
]
