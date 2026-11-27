"""R6-03: run budgets and the budget ledger (ADR-019 §5, loop half).

``RunBudget`` has five required dimensions -- steps, model calls, wall
clock, tokens and cost -- and none defaults to unbounded: a caller
that wants a limit says so, explicitly, for every dimension. The
token and cost halves are enforced again, independently, inside
``ModelGateway`` (R6-04's ``RunBudgetPolicy``) because only the
gateway can see what a call actually spent; this ledger is the loop's
own steps/model-calls/wall-clock half (§5 "In the loop").

``BudgetLedger`` debits *before* a step is attempted (debit-before-
attempt): the spend is recorded even on the attempt that pushes a run
over its limit, so a budget can never be exceeded by more than one
step's worth. Exhaustion is a terminal outcome the caller inspects on
the returned result, not an exception raised past the caller -- a
budget stop is a normal way for a run to end, the same way
``AgentRunState.BUDGET_EXCEEDED`` is a normal terminal state and not
a failure. The one case that *does* raise is the fail-closed one
(A8.fail-closed-negative): debiting a run for which no budget was
ever registered. Absent budget never means unlimited, here either.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from cairn_kernel.errors import MissingDependencyError, ValidationError


class BudgetDimension(str, Enum):
    STEPS = "STEPS"
    MODEL_CALLS = "MODEL_CALLS"
    WALL_CLOCK_SECONDS = "WALL_CLOCK_SECONDS"
    TOTAL_TOKENS = "TOTAL_TOKENS"
    COST_MICRO_USD = "COST_MICRO_USD"


@dataclass(frozen=True, slots=True)
class RunBudget:
    """All five dimensions are required and positive; there is no
    default, because a default would be a silent unbounded limit."""

    max_steps: int
    max_model_calls: int
    max_wall_clock_seconds: int
    max_total_tokens: int
    max_cost_micro_usd: int

    def __post_init__(self) -> None:
        for dimension, value in self.limit_by_dimension().items():
            if not isinstance(value, int) or isinstance(value, bool) or value is None or value <= 0:
                raise ValidationError(
                    f"run budget dimension {dimension.value} must be a positive integer "
                    "(an unbounded budget is refused)"
                )

    def limit_by_dimension(self) -> dict[BudgetDimension, int]:
        return {
            BudgetDimension.STEPS: self.max_steps,
            BudgetDimension.MODEL_CALLS: self.max_model_calls,
            BudgetDimension.WALL_CLOCK_SECONDS: self.max_wall_clock_seconds,
            BudgetDimension.TOTAL_TOKENS: self.max_total_tokens,
            BudgetDimension.COST_MICRO_USD: self.max_cost_micro_usd,
        }


@dataclass(frozen=True, slots=True)
class BudgetDebitResult:
    """The outcome of one debit. ``exhausted`` is the terminal signal a
    caller inspects; this never raises for exhaustion, only for the
    fail-closed case :meth:`BudgetLedger.debit` raises before
    returning anything."""

    dimension: BudgetDimension
    consumed: int
    limit: int
    exhausted: bool


@dataclass(slots=True)
class _RunLedger:
    budget: RunBudget
    consumed: dict[BudgetDimension, int] = field(default_factory=dict)


class BudgetLedger:
    """Tracks consumption per ``agent_run_id`` against its registered
    ``RunBudget``. A run must be started with :meth:`start_run` before
    anything can be debited against it."""

    def __init__(self) -> None:
        self._runs: dict[str, _RunLedger] = {}

    def start_run(self, run_id: str, budget: RunBudget) -> None:
        if not run_id.strip():
            raise ValidationError("budget ledger run_id must not be blank")
        if not isinstance(budget, RunBudget):
            raise ValidationError("budget ledger start_run requires a RunBudget")
        if run_id in self._runs:
            raise ValidationError(f"run {run_id} already has a budget registered")
        self._runs[run_id] = _RunLedger(budget=budget)

    def debit(self, run_id: str, dimension: BudgetDimension, amount: int = 1) -> BudgetDebitResult:
        """Debit before the step is attempted. Raises
        ``MissingDependencyError`` (fail-closed) if ``run_id`` has no
        registered budget -- a run with no registered budget cannot
        start spending against one."""

        ledger = self._runs.get(run_id)
        if ledger is None:
            raise MissingDependencyError(f"run {run_id} has no registered budget; it cannot start")

        consumed = ledger.consumed.get(dimension, 0) + amount
        ledger.consumed[dimension] = consumed
        limit = ledger.budget.limit_by_dimension()[dimension]
        return BudgetDebitResult(
            dimension=dimension, consumed=consumed, limit=limit, exhausted=consumed > limit
        )

    def consumption(self, run_id: str) -> dict[BudgetDimension, int]:
        ledger = self._runs.get(run_id)
        if ledger is None:
            raise MissingDependencyError(f"run {run_id} has no registered budget")
        return dict(ledger.consumed)


__all__ = ["BudgetDebitResult", "BudgetDimension", "BudgetLedger", "RunBudget"]
