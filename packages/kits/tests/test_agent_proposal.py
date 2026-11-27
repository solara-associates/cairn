"""R6-11a acceptance: the proposal channel an agent's output travels on.

``AgentSpec.output_schema``, ``AgentRun.proposal``,
``AgentRun.with_proposal``, ``complete_with_proposal`` and
``DeterministicAgentLoop``'s scripted proposal. The ADK half of the
same contract is in ``packages/adapters/tests/test_agent_adk_proposal.py``,
which also asserts the two implementations agree.

The property this file exists to pin down: ``run.proposal is not None``
means "this proposal satisfied the agent's declared output schema", and
there is no way to construct an ``AgentRun`` for which that reading is
wrong.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cairn_kernel.errors import ModelSchemaValidationError, ValidationError
from cairn_kernel.model.ports import StructuredOutputExpectation
from cairn_kernel.security import Role
from cairn_kits.loop import (
    AgentRun,
    AgentRunContext,
    AgentRunState,
    AgentSpec,
    AgentStep,
    BudgetLedger,
    DeterministicAgentLoop,
    InMemoryStepRecorder,
    PromptRegistry,
    RunBudget,
    StepKind,
    complete_with_proposal,
)
from cairn_kits.mcp import BoundedContextServer, McpRegistry, ToolCapability

TOOL = "estate.read_estate"

OUTPUT_SCHEMA = StructuredOutputExpectation(
    schema_name="demo_proposal.v1",
    schema={
        "type": "object",
        "required": ["summary", "workload_ids"],
        "properties": {
            "summary": {"type": "string"},
            "workload_ids": {"type": "array"},
            "confidence": {"type": "number"},
        },
    },
)
PROPOSAL: dict[str, object] = {
    "summary": "two workloads rehost cleanly",
    "workload_ids": ["w-1", "w-2"],
    "confidence": 0.8,
}


class _SequenceClock:
    """Returns each given instant in turn, repeating the last."""

    def __init__(self, instants: list[datetime]) -> None:
        self._instants = instants
        self._index = 0

    def now(self) -> datetime:
        instant = self._instants[min(self._index, len(self._instants) - 1)]
        self._index += 1
        return instant


def _budget(**overrides: object) -> RunBudget:
    kwargs: dict[str, object] = {
        "max_steps": 10,
        "max_model_calls": 10,
        "max_wall_clock_seconds": 300,
        "max_total_tokens": 100_000,
        "max_cost_micro_usd": 500_000,
    }
    kwargs.update(overrides)
    return RunBudget(**kwargs)  # type: ignore[arg-type]


def _prompt_registry(tmp_path: Path) -> PromptRegistry:
    agent_dir = tmp_path / "demo-agent"
    agent_dir.mkdir(exist_ok=True)
    (agent_dir / "system.v1.md").write_text(
        "---\nid: demo-agent/system\nversion: 1\n---\n\nbody\n", encoding="utf-8"
    )
    return PromptRegistry.load(tmp_path)


def _mcp_registry() -> McpRegistry:
    registry = McpRegistry()
    registry.register(
        BoundedContextServer(
            context_id="estate",
            name="estate",
            tools=(TOOL,),
            capabilities={TOOL: ToolCapability.READ},
            handle=lambda tool_name, arguments, principal: None,
        )
    )
    return registry


def _spec(tmp_path: Path, **overrides: object) -> AgentSpec:
    kwargs: dict[str, object] = {
        "agent_id": "demo-agent",
        "version": 1,
        "toolset": (TOOL,),
        "required_role": Role.ENGINEER,
        "prompt_references": (("demo-agent/system", 1),),
        "budget": _budget(),
        "output_schema": OUTPUT_SCHEMA,
        "prompt_registry": _prompt_registry(tmp_path),
        "mcp_registry": _mcp_registry(),
        "tool_roles": {TOOL: Role.ENGINEER},
    }
    kwargs.update(overrides)
    return AgentSpec.build(**kwargs)  # type: ignore[arg-type]


def _context(run_id: str = "run-1") -> AgentRunContext:
    return AgentRunContext(
        run_id=run_id,
        tenant_id="tenant-1",
        actor="user-1",
        correlation_id="corr-1",
        budget_ledger=BudgetLedger(),
        step_recorder=InMemoryStepRecorder(),
        project_id="project-1",
    )


def _running_run() -> AgentRun:
    return AgentRun(
        run_id="run-1",
        agent_id="demo-agent",
        agent_version=1,
        tenant_id="tenant-1",
        actor="user-1",
        state=AgentRunState.PENDING,
    ).with_state(AgentRunState.RUNNING)


def _steps() -> tuple[AgentStep, ...]:
    return (
        AgentStep(index=0, kind=StepKind.MODEL_CALL, detail={"prompt_id": "demo-agent/system"}),
        AgentStep(index=1, kind=StepKind.TOOL_CALL, detail={"tool_name": TOOL}),
    )


# --- AgentSpec.output_schema ------------------------------------------------


def test_an_agent_spec_must_declare_an_output_schema(tmp_path: Path) -> None:
    """ADR-019 §1 names ``output_schema`` as a field of every
    ``AgentSpec``. It is required and has no default: an agent with no
    declared output contract is the hole R-AI-01 exists to close, so
    omitting it is a ``TypeError`` at the call, not a run that discovers
    at step 30 that nobody said what it should produce."""

    with pytest.raises(TypeError, match="output_schema"):
        AgentSpec.build(
            agent_id="demo-agent",
            version=1,
            toolset=(TOOL,),
            required_role=Role.ENGINEER,
            prompt_references=(("demo-agent/system", 1),),
            budget=_budget(),
            prompt_registry=_prompt_registry(tmp_path),
            mcp_registry=_mcp_registry(),
            tool_roles={TOOL: Role.ENGINEER},
        )


def test_an_output_schema_that_is_not_a_structured_output_expectation_raises(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError, match="output_schema"):
        _spec(tmp_path, output_schema={"type": "object"})


def test_a_spec_carries_the_output_schema_it_was_built_with(tmp_path: Path) -> None:
    assert _spec(tmp_path).output_schema is OUTPUT_SCHEMA


# --- AgentRun.proposal, and the biconditional with COMPLETED ----------------


def test_a_run_in_progress_carries_no_proposal() -> None:
    assert _running_run().proposal is None


def test_a_valid_proposal_completes_the_run_and_is_carried_verbatim(tmp_path: Path) -> None:
    run = _running_run().with_proposal(_spec(tmp_path), PROPOSAL)

    assert run.state is AgentRunState.COMPLETED
    assert run.proposal == PROPOSAL


def test_a_proposal_violating_the_schema_raises_and_leaves_the_run_untouched(
    tmp_path: Path,
) -> None:
    """``workload_ids`` is required; a proposal without it is not a
    proposal this agent declared it would produce."""

    run = _running_run()

    with pytest.raises(ModelSchemaValidationError, match="workload_ids"):
        run.with_proposal(_spec(tmp_path), {"summary": "no ids"})

    assert run.state is AgentRunState.RUNNING
    assert run.proposal is None


def test_a_proposal_whose_field_has_the_wrong_type_raises(tmp_path: Path) -> None:
    with pytest.raises(ModelSchemaValidationError, match="summary"):
        _running_run().with_proposal(_spec(tmp_path), {"summary": 7, "workload_ids": ["w-1"]})


def test_a_run_proposes_once(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    run = _running_run().with_proposal(spec, PROPOSAL)

    with pytest.raises(ValidationError, match="proposes once"):
        run.with_proposal(spec, PROPOSAL)


def test_a_completed_run_cannot_be_constructed_with_no_proposal() -> None:
    """The structural half of "a run that produced nothing valid is not
    COMPLETED" -- a loop implementation cannot report success by
    forgetting to attach what it succeeded at."""

    with pytest.raises(ValidationError, match="cannot complete with no proposal"):
        AgentRun(
            run_id="run-1",
            agent_id="demo-agent",
            agent_version=1,
            tenant_id="tenant-1",
            actor="user-1",
            state=AgentRunState.COMPLETED,
        )


@pytest.mark.parametrize(
    "state", [AgentRunState.FAILED, AgentRunState.BUDGET_EXCEEDED, AgentRunState.RUNNING]
)
def test_a_non_completed_run_cannot_carry_a_proposal(state: AgentRunState) -> None:
    """The other half: nothing can hand an approver a proposal off a run
    that failed or ran out of budget."""

    with pytest.raises(ValidationError, match="must not carry a"):
        AgentRun(
            run_id="run-1",
            agent_id="demo-agent",
            agent_version=1,
            tenant_id="tenant-1",
            actor="user-1",
            state=state,
            proposal=PROPOSAL,
        )


def test_a_proposal_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(ValidationError, match="must be an object"):
        AgentRun(
            run_id="run-1",
            agent_id="demo-agent",
            agent_version=1,
            tenant_id="tenant-1",
            actor="user-1",
            state=AgentRunState.COMPLETED,
            proposal="a string",  # type: ignore[arg-type]
        )


# --- complete_with_proposal -------------------------------------------------


def test_complete_with_proposal_completes_on_a_valid_proposal(tmp_path: Path) -> None:
    run = complete_with_proposal(_running_run(), _spec(tmp_path), PROPOSAL)

    assert run.state is AgentRunState.COMPLETED
    assert run.proposal == PROPOSAL
    assert run.terminal_reason is None


def test_complete_with_proposal_fails_the_run_when_there_is_no_proposal(tmp_path: Path) -> None:
    run = complete_with_proposal(_running_run(), _spec(tmp_path), None)

    assert run.state is AgentRunState.FAILED
    assert run.proposal is None
    assert run.terminal_reason == "agent run produced no final proposal"


def test_complete_with_proposal_fails_the_run_and_records_why_on_a_schema_violation(
    tmp_path: Path,
) -> None:
    """Design §3's failure shape: "a proposal that fails validation is
    never persisted and never shown as a draft". The reason is on the
    run, so the evidence envelope carries it."""

    run = complete_with_proposal(_running_run(), _spec(tmp_path), {"summary": "no ids"})

    assert run.state is AgentRunState.FAILED
    assert run.proposal is None
    assert run.terminal_reason is not None
    assert "workload_ids" in run.terminal_reason


def test_complete_with_proposal_raises_nothing_at_its_caller(tmp_path: Path) -> None:
    """An agent run's own failure to propose is a terminal state of that
    run, never an exception the service above has to catch."""

    for proposal in (None, {"summary": "no ids"}, {}):
        run = complete_with_proposal(_running_run(), _spec(tmp_path), proposal)
        assert run.state is AgentRunState.FAILED


# --- content_hash covers the proposal ---------------------------------------


def test_the_run_content_hash_covers_the_proposal(tmp_path: Path) -> None:
    """R6-15 seals this into the run's evidence envelope, so the
    proposal must be under the same integrity as the steps: alter one
    field of it and the hash moves."""

    spec = _spec(tmp_path)
    base = _running_run()
    for step in _steps():
        base = base.with_step(step)

    first = base.with_proposal(spec, PROPOSAL)
    altered = base.with_proposal(spec, {**PROPOSAL, "summary": "something else"})

    assert first.content_hash != altered.content_hash


def test_the_run_content_hash_is_stable_for_identical_content(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    base = _running_run()
    for step in _steps():
        base = base.with_step(step)

    assert (
        base.with_proposal(spec, PROPOSAL).content_hash
        == base.with_proposal(spec, dict(PROPOSAL)).content_hash
    )


def test_the_run_content_hash_still_covers_the_steps(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    without_steps = _running_run().with_proposal(spec, PROPOSAL)
    with_steps = _running_run()
    for step in _steps():
        with_steps = with_steps.with_step(step)

    assert without_steps.content_hash != with_steps.with_proposal(spec, PROPOSAL).content_hash


# --- DeterministicAgentLoop -------------------------------------------------


def test_the_deterministic_loop_completes_on_its_scripted_proposal(tmp_path: Path) -> None:
    loop = DeterministicAgentLoop(
        _steps(),
        clock=_SequenceClock([datetime(2026, 1, 1, tzinfo=UTC)]),
        scripted_proposal=PROPOSAL,
    )

    run = loop.run(_spec(tmp_path), {}, context=_context())

    assert run.state is AgentRunState.COMPLETED
    assert run.proposal == PROPOSAL


def test_the_deterministic_loop_fails_with_no_scripted_proposal(tmp_path: Path) -> None:
    loop = DeterministicAgentLoop(
        _steps(), clock=_SequenceClock([datetime(2026, 1, 1, tzinfo=UTC)])
    )

    run = loop.run(_spec(tmp_path), {}, context=_context())

    assert run.state is AgentRunState.FAILED
    assert run.proposal is None
    assert run.terminal_reason == "agent run produced no final proposal"
    # the steps still happened and are still recorded: a failed run is
    # evidence, not an absence of it (ADR-019 §5).
    assert [step.index for step in run.steps] == [0, 1]


def test_the_deterministic_loop_fails_on_a_scripted_proposal_that_violates_the_schema(
    tmp_path: Path,
) -> None:
    """The reason both implementations call the same gate: a scripted
    proposal gets no easier a ride than a model-produced one."""

    loop = DeterministicAgentLoop(
        _steps(),
        clock=_SequenceClock([datetime(2026, 1, 1, tzinfo=UTC)]),
        scripted_proposal={"summary": "no ids"},
    )

    run = loop.run(_spec(tmp_path), {}, context=_context())

    assert run.state is AgentRunState.FAILED
    assert run.proposal is None
    assert "workload_ids" in (run.terminal_reason or "")


def test_a_budget_stopped_deterministic_run_proposes_nothing(tmp_path: Path) -> None:
    """A proposal that arrives after the budget is spent is not a
    proposal: the run ends ``BUDGET_EXCEEDED`` carrying none."""

    loop = DeterministicAgentLoop(
        _steps(),
        clock=_SequenceClock([datetime(2026, 1, 1, tzinfo=UTC)]),
        scripted_proposal=PROPOSAL,
    )

    run = loop.run(_spec(tmp_path, budget=_budget(max_steps=1)), {}, context=_context())

    assert run.state is AgentRunState.BUDGET_EXCEEDED
    assert run.proposal is None


def test_a_wall_clock_stopped_deterministic_run_proposes_nothing(tmp_path: Path) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    loop = DeterministicAgentLoop(
        _steps(),
        clock=_SequenceClock([start, start + timedelta(seconds=5)]),
        scripted_proposal=PROPOSAL,
    )

    run = loop.run(
        _spec(tmp_path, budget=_budget(max_wall_clock_seconds=1)), {}, context=_context()
    )

    assert run.state is AgentRunState.BUDGET_EXCEEDED
    assert run.proposal is None
