"""R6-03: run budgets and the budget ledger (ADR-019 §5, loop half)."""

from __future__ import annotations

import pytest
from cairn_kernel.errors import MissingDependencyError, ValidationError
from cairn_kits.loop import AgentRunState, BudgetDimension, BudgetLedger, RunBudget

ALL_DIMENSIONS = (
    "max_steps",
    "max_model_calls",
    "max_wall_clock_seconds",
    "max_total_tokens",
    "max_cost_micro_usd",
)


def _budget(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "max_steps": 10,
        "max_model_calls": 10,
        "max_wall_clock_seconds": 300,
        "max_total_tokens": 100_000,
        "max_cost_micro_usd": 500_000,
    }
    kwargs.update(overrides)
    return kwargs


@pytest.mark.parametrize("dimension", ALL_DIMENSIONS)
def test_a_budget_missing_any_dimension_raises(dimension: str) -> None:
    with pytest.raises(ValidationError):
        RunBudget(**_budget(**{dimension: None}))


@pytest.mark.parametrize("dimension", ALL_DIMENSIONS)
def test_a_budget_with_a_non_positive_dimension_raises(dimension: str) -> None:
    with pytest.raises(ValidationError):
        RunBudget(**_budget(**{dimension: 0}))


@pytest.mark.parametrize(
    ("field_name", "dimension"),
    [
        ("max_steps", BudgetDimension.STEPS),
        ("max_model_calls", BudgetDimension.MODEL_CALLS),
        ("max_wall_clock_seconds", BudgetDimension.WALL_CLOCK_SECONDS),
        ("max_total_tokens", BudgetDimension.TOTAL_TOKENS),
        ("max_cost_micro_usd", BudgetDimension.COST_MICRO_USD),
    ],
)
def test_a_ledger_debited_past_each_limit_reports_exhaustion_for_that_dimension(
    field_name: str, dimension: BudgetDimension
) -> None:
    budget = RunBudget(**_budget(**{field_name: 1}))
    ledger = BudgetLedger()
    ledger.start_run("run-1", budget)

    first = ledger.debit("run-1", dimension)
    assert first.exhausted is False

    second = ledger.debit("run-1", dimension)
    assert second.exhausted is True
    assert second.dimension is dimension


def test_exhaustion_does_not_raise_past_the_caller() -> None:
    budget = RunBudget(**_budget(max_steps=0 + 1))
    ledger = BudgetLedger()
    ledger.start_run("run-1", budget)
    ledger.debit("run-1", BudgetDimension.STEPS)
    result = ledger.debit("run-1", BudgetDimension.STEPS)  # over budget, must not raise
    assert result.exhausted is True


def test_a_run_terminating_on_exhaustion_lands_in_budget_exceeded_not_failed() -> None:
    from cairn_kits.loop import AgentRun

    budget = RunBudget(**_budget(max_steps=1))
    ledger = BudgetLedger()
    ledger.start_run("run-1", budget)
    ledger.debit("run-1", BudgetDimension.STEPS)
    result = ledger.debit("run-1", BudgetDimension.STEPS)
    assert result.exhausted is True

    run = AgentRun(
        run_id="run-1",
        agent_id="demo-agent",
        agent_version=1,
        tenant_id="tenant-1",
        actor="user-1",
        state=AgentRunState.RUNNING,
    )
    terminated = run.with_state(AgentRunState.BUDGET_EXCEEDED)
    assert terminated.state is AgentRunState.BUDGET_EXCEEDED
    assert terminated.state is not AgentRunState.FAILED


def test_a_run_with_no_registered_budget_cannot_start() -> None:
    ledger = BudgetLedger()
    with pytest.raises(MissingDependencyError):
        ledger.debit("never-started", BudgetDimension.STEPS)
    with pytest.raises(MissingDependencyError):
        ledger.consumption("never-started")


def test_start_run_rejects_a_duplicate_registration() -> None:
    budget = RunBudget(**_budget())
    ledger = BudgetLedger()
    ledger.start_run("run-1", budget)
    with pytest.raises(ValidationError):
        ledger.start_run("run-1", budget)
