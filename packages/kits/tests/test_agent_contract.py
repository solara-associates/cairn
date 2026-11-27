"""R6-02: the agent loop contract (ADR-019 §1)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from cairn_kernel.errors import InvalidStateTransitionError, MissingDependencyError, ValidationError
from cairn_kits.loop import (
    AgentRun,
    AgentRunState,
    AgentSpec,
    AgentStep,
    PromptRegistry,
    RunBudget,
    StepKind,
    validate_agent_run_transition,
)


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


def _spec(prompt_registry: PromptRegistry, **overrides: object) -> AgentSpec:
    kwargs: dict[str, object] = {
        "agent_id": "demo-agent",
        "version": 1,
        "toolset": ("estate.read_estate",),
        "required_role": "APP",
        "prompt_references": (("demo-agent/system", 1),),
        "budget": _budget(),
        "prompt_registry": prompt_registry,
    }
    kwargs.update(overrides)
    return AgentSpec.build(**kwargs)  # type: ignore[arg-type]


def _run(**overrides: object) -> AgentRun:
    kwargs: dict[str, object] = {
        "run_id": "run-1",
        "agent_id": "demo-agent",
        "agent_version": 1,
        "tenant_id": "tenant-1",
        "actor": "user-1",
        "state": AgentRunState.PENDING,
    }
    kwargs.update(overrides)
    return AgentRun(**kwargs)  # type: ignore[arg-type]


# --- AgentRunState transitions ----------------------------------------------


def test_every_illegal_state_transition_raises() -> None:
    legal = {
        (AgentRunState.PENDING, AgentRunState.RUNNING),
        (AgentRunState.RUNNING, AgentRunState.COMPLETED),
        (AgentRunState.RUNNING, AgentRunState.FAILED),
        (AgentRunState.RUNNING, AgentRunState.BUDGET_EXCEEDED),
    }
    for current in AgentRunState:
        for target in AgentRunState:
            if (current, target) in legal:
                validate_agent_run_transition(current, target)
            else:
                with pytest.raises(InvalidStateTransitionError):
                    validate_agent_run_transition(current, target)


def test_self_transition_is_rejected() -> None:
    with pytest.raises(InvalidStateTransitionError):
        validate_agent_run_transition(AgentRunState.RUNNING, AgentRunState.RUNNING)


def test_there_is_no_executed_state() -> None:
    assert "EXECUTED" not in AgentRunState.__members__


def test_no_field_on_agent_run_or_agent_step_names_an_approval_or_an_execution() -> None:
    for cls in (AgentRun, AgentStep, AgentSpec):
        for f in dataclasses.fields(cls):
            lowered = f.name.lower()
            assert "approv" not in lowered, f"{cls.__name__}.{f.name} names an approval"
            assert "execut" not in lowered, f"{cls.__name__}.{f.name} names an execution"


# --- AgentSpec construction --------------------------------------------------


def test_agent_spec_with_empty_toolset_raises(tmp_path: Path) -> None:
    registry = _prompt_registry(tmp_path)
    with pytest.raises(ValidationError):
        _spec(registry, toolset=())


def test_agent_spec_with_an_unbounded_budget_field_raises(tmp_path: Path) -> None:
    registry = _prompt_registry(tmp_path)
    with pytest.raises(ValidationError):
        _spec(registry, budget=_budget(max_steps=0))


def test_agent_spec_with_an_unresolvable_prompt_reference_raises(tmp_path: Path) -> None:
    registry = _prompt_registry(tmp_path)
    with pytest.raises(MissingDependencyError):
        _spec(registry, prompt_references=(("demo-agent/missing", 1),))


def test_agent_spec_builds_with_valid_inputs(tmp_path: Path) -> None:
    registry = _prompt_registry(tmp_path)
    spec = _spec(registry)
    assert spec.agent_id == "demo-agent"
    assert spec.toolset == ("estate.read_estate",)


# --- AgentRun / AgentStep: append-only ---------------------------------------


def test_steps_are_append_only() -> None:
    run = _run()
    step0 = AgentStep(index=0, kind=StepKind.MODEL_CALL)
    run_with_step = run.with_step(step0)

    assert run.steps == ()
    assert run_with_step.steps == (step0,)

    step1 = AgentStep(index=1, kind=StepKind.TOOL_CALL)
    run_with_two_steps = run_with_step.with_step(step1)
    assert run_with_two_steps.steps == (step0, step1)


def test_with_step_rejects_an_out_of_order_index() -> None:
    run = _run()
    with pytest.raises(ValidationError):
        run.with_step(AgentStep(index=1, kind=StepKind.MODEL_CALL))


def test_agent_run_has_no_mutation_method_for_steps() -> None:
    run = _run()
    for forbidden in ("set_step", "remove_step", "pop_step", "clear_steps"):
        assert not hasattr(run, forbidden)
    with pytest.raises(dataclasses.FrozenInstanceError):
        run.steps = (AgentStep(index=0, kind=StepKind.MODEL_CALL),)  # type: ignore[misc]


def test_with_state_validates_the_transition() -> None:
    run = _run()
    running = run.with_state(AgentRunState.RUNNING)
    assert running.state == AgentRunState.RUNNING

    with pytest.raises(InvalidStateTransitionError):
        run.with_state(AgentRunState.COMPLETED)
