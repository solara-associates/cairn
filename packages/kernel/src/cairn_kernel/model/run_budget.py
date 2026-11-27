"""R6-04: ``RunBudgetPolicy`` (ADR-019 §5, gateway half).

The loop's own ``cairn_kits.loop.budget.RunBudget``/``BudgetLedger``
track steps, model calls and wall clock -- things the loop itself can
see. Tokens and cost can only be seen here, inside ``ModelGateway``,
once a response comes back with real token counts and this gateway's
own price table turns them into a cost. ``cairn_kernel`` is a leaf
(``.importlinter``'s "Kernel and contracts are leaves" contract) and
cannot import ``cairn_kits``, so this is a second, independent policy
with its own two-dimension limit type, not a reuse of the loop's
``RunBudget`` -- keyed the same way, on ``ModelRequest.agent_run_id``.

Fail-closed, same as the three existing gateway policies: a request
carrying an ``agent_run_id`` with no registered budget is refused, not
treated as unlimited. A request with no ``agent_run_id`` is not an
agent call and this policy never touches it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cairn_kernel.errors import RunBudgetExceededError, ValidationError
from cairn_kernel.model.ports import ModelRequest


@dataclass(frozen=True, slots=True)
class RunBudgetLimits:
    """Both dimensions are required and positive; neither defaults to
    unbounded."""

    max_total_tokens: int
    max_cost_micro_usd: int

    def __post_init__(self) -> None:
        for name, value in (
            ("max_total_tokens", self.max_total_tokens),
            ("max_cost_micro_usd", self.max_cost_micro_usd),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValidationError(
                    f"run budget limit {name} must be a positive integer (an unbounded budget is refused)"
                )


@dataclass(slots=True)
class _RunConsumption:
    total_tokens: int = 0
    cost_micro_usd: int = 0


@dataclass
class RunBudgetPolicy:
    """Joins ``ModelGateway``'s pre-call chain after the circuit
    breaker. Consumption is recorded by the gateway, after a call
    completes and its real token/cost numbers are known
    (:meth:`record`); :meth:`check` only ever reads what has already
    been spent, so it can run before the adapter without knowing this
    call's own cost in advance."""

    _limits: dict[str, RunBudgetLimits] = field(default_factory=dict, init=False, repr=False)
    _consumption: dict[str, _RunConsumption] = field(default_factory=dict, init=False, repr=False)

    def register(self, agent_run_id: str, limits: RunBudgetLimits) -> None:
        if not agent_run_id.strip():
            raise ValidationError("run budget policy agent_run_id must not be blank")
        if not isinstance(limits, RunBudgetLimits):
            raise ValidationError("run budget policy register requires RunBudgetLimits")
        self._limits[agent_run_id] = limits
        self._consumption.setdefault(agent_run_id, _RunConsumption())

    def check(self, request: ModelRequest) -> None:
        if request.agent_run_id is None:
            return  # not an agent call; this policy never touches it.

        limits = self._limits.get(request.agent_run_id)
        if limits is None:
            raise RunBudgetExceededError(
                f"agent run {request.agent_run_id!r} has no registered budget; refused"
            )

        consumed = self._consumption[request.agent_run_id]
        if consumed.total_tokens >= limits.max_total_tokens:
            raise RunBudgetExceededError(
                f"agent run {request.agent_run_id!r} exceeded max_total_tokens "
                f"({consumed.total_tokens}/{limits.max_total_tokens})"
            )
        if consumed.cost_micro_usd >= limits.max_cost_micro_usd:
            raise RunBudgetExceededError(
                f"agent run {request.agent_run_id!r} exceeded max_cost_micro_usd "
                f"({consumed.cost_micro_usd}/{limits.max_cost_micro_usd})"
            )

    def record(self, agent_run_id: str, *, tokens: int, cost_micro_usd: int) -> None:
        consumption = self._consumption.get(agent_run_id)
        if consumption is None:
            return  # unregistered; check() already refused any call for this run.
        consumption.total_tokens += tokens
        consumption.cost_micro_usd += cost_micro_usd


__all__ = ["RunBudgetLimits", "RunBudgetPolicy"]
