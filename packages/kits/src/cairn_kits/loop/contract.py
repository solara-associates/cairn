"""R6-02: the agent loop contract (ADR-019 §1).

``AgentSpec`` is a value, not a class hierarchy: a named, versioned,
bounded plan-act-observe loop over one project, whose toolset and
prompt references are checked before a run can even be constructed.
``AgentRun`` and ``AgentStep`` are this package's own domain types for
a run in progress -- append-only, no field that names an approval or
an execution, because this package can reach neither (``.importlinter``'s
``kits-purity`` contract, enforced structurally from R6-05 on).

Deliberately absent from ``AgentRunState``: an ``EXECUTED`` state. An
agent run only ever proposes; turning a proposal into an executed
action is the existing approval/execution machinery's job, not this
loop's, and giving the run a state that suggests otherwise would say
the opposite of what ADR-019 decided.

The state-machine shape (an ``Enum``, an ``ALLOWED_*_TRANSITIONS``
table, a ``validate_*_transition`` function that rejects anything not
named in the table, self-transitions included) matches
``cairn_modules.approvals.model.validate_approval_transition`` and
``cairn_modules.execution.model.validate_execution_transition`` -- this
package cannot import either, so the shape is copied, not shared.

R6-05 adds the propose-only boundary at ``AgentSpec.build()``: every
tool in the toolset must resolve, through a live
:class:`cairn_kits.mcp.McpRegistry`, to a ``READ`` or ``PROPOSE``
capability, and ``required_role`` must dominate every tool's own
required role -- both checked once, at construction, the same shape
as the prompt-reference check R6-01 already established.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum

from cairn_kernel.errors import InvalidStateTransitionError, MissingDependencyError, ValidationError
from cairn_kernel.security import Role

from cairn_kits.loop.budget import RunBudget
from cairn_kits.loop.prompt_registry import PromptRegistry
from cairn_kits.mcp import McpRegistry, ToolCapability

#: Role.__members__ is declared most-privileged first (ADR-012's own
#: taxonomy order); a lower index is a stronger role. "Dominates" means
#: at least as privileged, by this ranking -- the same reading
#: ``apps/mcp-gateway/src/cairn_mcp_gateway/registry_factory.py``'s own
#: comment already gives this ordering informally ("AUDITOR, the lowest
#: role R0's taxonomy grants read access... under").
_ROLE_RANK: dict[Role, int] = {role: index for index, role in enumerate(Role)}


def _role_dominates(candidate: Role, other: Role) -> bool:
    return _ROLE_RANK[candidate] <= _ROLE_RANK[other]


class StepKind(str, Enum):
    MODEL_CALL = "MODEL_CALL"
    TOOL_CALL = "TOOL_CALL"


class AgentRunState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"


ALLOWED_AGENT_RUN_TRANSITIONS: dict[AgentRunState, frozenset[AgentRunState]] = {
    AgentRunState.PENDING: frozenset({AgentRunState.RUNNING}),
    AgentRunState.RUNNING: frozenset(
        {AgentRunState.COMPLETED, AgentRunState.FAILED, AgentRunState.BUDGET_EXCEEDED}
    ),
    AgentRunState.COMPLETED: frozenset(),
    AgentRunState.FAILED: frozenset(),
    AgentRunState.BUDGET_EXCEEDED: frozenset(),
}


def validate_agent_run_transition(current: AgentRunState, target: AgentRunState) -> None:
    """Reject any transition not named in ``ALLOWED_AGENT_RUN_TRANSITIONS``,
    including a self-transition -- the same rule
    ``validate_approval_transition`` applies, for the same reason: a
    caller that thinks it changed state when it did not is a bug this
    should surface, not hide."""

    allowed = ALLOWED_AGENT_RUN_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidStateTransitionError(
            f"agent run cannot move from {current.value} to {target.value}"
        )


@dataclass(frozen=True, slots=True)
class AgentStep:
    """One step of a run: either a model call or a tool call. ``detail``
    carries kind-specific data (prompt id/version and model id for a
    ``MODEL_CALL``, tool name and arguments for a ``TOOL_CALL``) -- kept
    as a plain mapping here because the full persisted shape (token
    counts, cost, duration, outcome) is R6-15's table, not this
    package's concern."""

    index: int
    kind: StepKind
    detail: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.index, int) or isinstance(self.index, bool) or self.index < 0:
            raise ValidationError("agent step index must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """A named, versioned agent. Constructed only through
    :meth:`build`, which is the one place a prompt reference is checked
    against a live :class:`PromptRegistry` -- never at the first call
    that needs it (A5.13).

    ``budget`` is a :class:`RunBudget` (R6-03): all five dimensions
    are required there already, so an "unbounded budget" is refused
    by ``RunBudget`` itself, before ``AgentSpec`` is even constructed.
    """

    agent_id: str
    version: int
    toolset: tuple[str, ...]
    required_role: Role
    prompt_references: tuple[tuple[str, int], ...]
    budget: RunBudget

    def __post_init__(self) -> None:
        if not self.agent_id.strip():
            raise ValidationError("agent spec needs a non-blank agent_id")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version <= 0:
            raise ValidationError("agent spec version must be a positive integer")
        if not self.toolset:
            raise ValidationError("agent spec toolset must not be empty")
        if len(set(self.toolset)) != len(self.toolset) or any(
            not name.strip() for name in self.toolset
        ):
            raise ValidationError("agent spec toolset must contain unique, non-blank tool names")
        if not isinstance(self.required_role, Role):
            raise ValidationError("agent spec required_role must be a Role")
        if not isinstance(self.budget, RunBudget):
            raise ValidationError(
                "agent spec budget must be a RunBudget (an unbounded budget is refused)"
            )

    @classmethod
    def build(
        cls,
        *,
        agent_id: str,
        version: int,
        toolset: Sequence[str],
        required_role: Role,
        prompt_references: Sequence[tuple[str, int]],
        budget: RunBudget,
        prompt_registry: PromptRegistry,
        mcp_registry: McpRegistry,
        tool_roles: Mapping[str, Role],
    ) -> AgentSpec:
        """Construction-time checks beyond a single field's own shape
        (R6-05, R-AGENT-03): every tool in ``toolset`` must resolve in
        ``mcp_registry`` to a ``READ`` or ``PROPOSE`` capability -- the
        only two capabilities a tool may ever declare, so this also
        catches a tool that somehow declared something else -- and
        ``required_role`` must dominate the role each tool in
        ``toolset`` requires (``tool_roles``), so a run started under
        ``required_role`` is never short of a role some tool it may
        call actually needs.
        """

        prompt_registry.validate_references(prompt_references)

        for tool_name in toolset:
            capability = mcp_registry.capability_of(tool_name)
            if capability not in (ToolCapability.READ, ToolCapability.PROPOSE):
                raise ValidationError(
                    f"agent spec toolset names {tool_name!r}, whose capability "
                    f"{capability!r} is neither READ nor PROPOSE"
                )
            tool_role = tool_roles.get(tool_name)
            if tool_role is None:
                raise MissingDependencyError(f"no required role declared for tool {tool_name!r}")
            if not _role_dominates(required_role, tool_role):
                raise ValidationError(
                    f"agent spec required_role {required_role.value} does not dominate "
                    f"{tool_role.value}, required by tool {tool_name!r}"
                )

        return cls(
            agent_id=agent_id,
            version=version,
            toolset=tuple(toolset),
            required_role=required_role,
            prompt_references=tuple(prompt_references),
            budget=budget,
        )


@dataclass(frozen=True, slots=True)
class AgentRun:
    """A run in progress. ``steps`` only grows: the one way to add a
    step is :meth:`with_step`, which returns a new ``AgentRun`` (this
    type is frozen) -- there is no method that replaces or removes a
    step, because nothing here may rewrite history."""

    run_id: str
    agent_id: str
    agent_version: int
    tenant_id: str
    actor: str
    state: AgentRunState
    steps: tuple[AgentStep, ...] = ()
    terminal_reason: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("run_id", self.run_id),
            ("agent_id", self.agent_id),
            ("tenant_id", self.tenant_id),
            ("actor", self.actor),
        ):
            if not value.strip():
                raise ValidationError(f"agent run {field_name} must not be blank")
        for index, step in enumerate(self.steps):
            if step.index != index:
                raise ValidationError(
                    f"agent run steps must be sequential from 0; got index {step.index} at position {index}"
                )

    def with_step(self, step: AgentStep) -> AgentRun:
        if step.index != len(self.steps):
            raise ValidationError(
                f"agent run {self.run_id} expected step index {len(self.steps)}, got {step.index}"
            )
        return replace(self, steps=(*self.steps, step))

    def with_state(self, target: AgentRunState) -> AgentRun:
        validate_agent_run_transition(self.state, target)
        return replace(self, state=target)


__all__ = [
    "ALLOWED_AGENT_RUN_TRANSITIONS",
    "AgentRun",
    "AgentRunState",
    "AgentSpec",
    "AgentStep",
    "StepKind",
    "validate_agent_run_transition",
]
