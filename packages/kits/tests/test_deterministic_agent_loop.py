"""R6-07 acceptance (loop half): ``DeterministicAgentLoop`` replays a
scripted step sequence against the same ``BudgetLedger``/``StepRecorder``
shapes the ADK adapter uses, and produces an ``AgentRun`` of the same
shape.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cairn_kernel.errors import MissingDependencyError
from cairn_kernel.security import Role
from cairn_kits.loop import (
    AgentRunState,
    AgentSpec,
    AgentStep,
    BudgetDimension,
    BudgetLedger,
    DeterministicAgentLoop,
    InMemoryStepRecorder,
    PromptRegistry,
    RunBudget,
    StepKind,
)
from cairn_kits.loop.ports import AgentRunContext
from cairn_kits.mcp import BoundedContextServer, McpRegistry, ToolCapability


class _SequenceClock:
    """Each call to ``now()`` pops the next of a fixed sequence of
    instants -- lets a test drive wall-clock budget exhaustion
    deterministically, without a real sleep."""

    def __init__(self, instants: list[datetime]) -> None:
        self._instants = list(instants)

    def now(self) -> datetime:
        if len(self._instants) > 1:
            return self._instants.pop(0)
        return self._instants[0]


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
    agent_dir.mkdir()
    (agent_dir / "system.v1.md").write_text(
        "---\nid: demo-agent/system\nversion: 1\n---\n\nbody\n", encoding="utf-8"
    )
    return PromptRegistry.load(tmp_path)


def _mcp_registry() -> McpRegistry:
    registry = McpRegistry()
    registry.register(
        BoundedContextServer(
            context_id="fixture",
            name="fixture",
            tools=("estate.read_estate",),
            capabilities={"estate.read_estate": ToolCapability.READ},
            handle=lambda tool_name, arguments: None,
        )
    )
    return registry


def _spec(prompt_registry: PromptRegistry, **overrides: object) -> AgentSpec:
    kwargs: dict[str, object] = {
        "agent_id": "demo-agent",
        "version": 1,
        "toolset": ("estate.read_estate",),
        "required_role": Role.ENGINEER,
        "prompt_references": (("demo-agent/system", 1),),
        "budget": _budget(),
        "prompt_registry": prompt_registry,
        "mcp_registry": _mcp_registry(),
        "tool_roles": {"estate.read_estate": Role.ENGINEER},
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
    )


def test_replays_scripted_steps_and_completes(tmp_path: Path) -> None:
    spec = _spec(_prompt_registry(tmp_path))
    steps = (
        AgentStep(index=0, kind=StepKind.MODEL_CALL, detail={"prompt_id": "demo-agent/system"}),
        AgentStep(index=1, kind=StepKind.TOOL_CALL, detail={"tool_name": "estate.read_estate"}),
    )
    loop = DeterministicAgentLoop(steps, clock=_SequenceClock([datetime(2026, 1, 1, tzinfo=UTC)]))
    context = _context()

    run = loop.run(spec, {}, context=context)

    assert run.state is AgentRunState.COMPLETED
    assert [step.index for step in run.steps] == [0, 1]
    assert context.step_recorder.steps_for(run.run_id) == run.steps
    assert context.budget_ledger.consumption(run.run_id)


def test_stops_on_step_budget_exhaustion(tmp_path: Path) -> None:
    spec = _spec(_prompt_registry(tmp_path), budget=_budget(max_steps=1))
    steps = (
        AgentStep(index=0, kind=StepKind.TOOL_CALL, detail={}),
        AgentStep(index=1, kind=StepKind.TOOL_CALL, detail={}),
    )
    loop = DeterministicAgentLoop(steps, clock=_SequenceClock([datetime(2026, 1, 1, tzinfo=UTC)]))

    run = loop.run(spec, {}, context=_context())

    assert run.state is AgentRunState.BUDGET_EXCEEDED
    # the exhausting step (the second, over a max_steps=1 budget) is
    # still attempted and recorded -- never more than one step's worth
    # over the limit, never silently dropped.
    assert len(run.steps) == 2


def test_stops_on_wall_clock_exhaustion(tmp_path: Path) -> None:
    spec = _spec(_prompt_registry(tmp_path), budget=_budget(max_wall_clock_seconds=1))
    steps = (
        AgentStep(index=0, kind=StepKind.TOOL_CALL, detail={}),
        AgentStep(index=1, kind=StepKind.TOOL_CALL, detail={}),
    )
    start = datetime(2026, 1, 1, tzinfo=UTC)
    loop = DeterministicAgentLoop(
        steps, clock=_SequenceClock([start, start + timedelta(seconds=5)])
    )

    run = loop.run(spec, {}, context=_context())

    assert run.state is AgentRunState.BUDGET_EXCEEDED


def test_a_run_with_no_registered_budget_cannot_be_debited_against() -> None:
    ledger = BudgetLedger()
    with pytest.raises(MissingDependencyError):
        ledger.debit("unregistered-run", BudgetDimension.STEPS)
