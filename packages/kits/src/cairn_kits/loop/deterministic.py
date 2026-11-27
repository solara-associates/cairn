"""R6-07: ``DeterministicAgentLoop`` -- the other :class:`AgentLoopPort`
implementation, lands in the same unit as ``cairn_adapters.agent_adk``
so both can be asserted to produce an :class:`AgentRun` of the same
shape (design §7).

It replays a scripted sequence of :class:`AgentStep`\\ s handed to it at
construction, debits the same :class:`BudgetLedger` before each one, and
records through the same :class:`StepRecorder` -- no reasoning, no
branching, no tool actually invoked and no model actually called. This
is why it is not a hand-rolled reasoning loop (ADR-019/A6.framework):
it never decides anything, it only replays what the caller already
decided, which is exactly what every agent test, API test and console
test runs against instead of a real provider.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from cairn_kernel.governance import (
    GovernancePort,
    GovernanceRequest,
    NoOpGovernance,
    evaluate_tool_call,
)
from cairn_kernel.hex.ports import Clock

from cairn_kits.loop.budget import BudgetDimension
from cairn_kits.loop.contract import AgentRun, AgentRunState, AgentSpec, AgentStep, StepKind
from cairn_kits.loop.ports import AgentRunContext


class DeterministicAgentLoop:
    """Replays ``scripted_steps`` against ``spec``'s budget, in order.

    Each scripted step is debited (one ``STEPS``, plus one
    ``MODEL_CALLS`` if its ``kind`` is ``MODEL_CALL``) *before* it is
    appended to the run -- debit-before-attempt, the same rule
    ``BudgetLedger`` itself documents. The first debit result that
    comes back exhausted stops the run there, in ``BUDGET_EXCEEDED``,
    with every step up to and including that one already recorded (the
    exhausting step is attempted and recorded, consistent with "a
    budget can never be exceeded by more than one step's worth").
    Otherwise, once every scripted step has been replayed, the run
    ends ``COMPLETED``.
    """

    def __init__(
        self,
        scripted_steps: Sequence[AgentStep],
        clock: Clock,
        governance: GovernancePort | None = None,
    ) -> None:
        self._scripted_steps = tuple(scripted_steps)
        self._clock = clock
        self._governance = governance if governance is not None else NoOpGovernance()

    def run(
        self,
        spec: AgentSpec,
        inputs: Mapping[str, object],
        *,
        context: AgentRunContext,
    ) -> AgentRun:
        del inputs  # the script already encodes what a real run would have produced

        context.budget_ledger.start_run(context.run_id, spec.budget)
        run = AgentRun(
            run_id=context.run_id,
            agent_id=spec.agent_id,
            agent_version=spec.version,
            tenant_id=context.tenant_id,
            actor=context.actor,
            state=AgentRunState.PENDING,
        ).with_state(AgentRunState.RUNNING)

        started_at = self._clock.now()
        last_checked_at = started_at

        for step in self._scripted_steps:
            decision = evaluate_tool_call(
                self._governance, _governance_request(spec, context, step)
            )
            if not decision.allowed:
                return replace(
                    run,
                    terminal_reason=(
                        f"governance denied step {step.index}"
                        f" ({decision.check.value}): {decision.reason}"
                    ),
                ).with_state(AgentRunState.FAILED)

            now = self._clock.now()
            elapsed_delta = max(int((now - last_checked_at).total_seconds()), 0)
            last_checked_at = now

            steps_result = context.budget_ledger.debit(context.run_id, BudgetDimension.STEPS)
            model_calls_result = None
            if step.kind is StepKind.MODEL_CALL:
                model_calls_result = context.budget_ledger.debit(
                    context.run_id, BudgetDimension.MODEL_CALLS
                )
            wall_clock_result = context.budget_ledger.debit(
                context.run_id, BudgetDimension.WALL_CLOCK_SECONDS, amount=elapsed_delta
            )

            run = run.with_step(step)
            context.step_recorder.record(context.run_id, step)

            if (
                steps_result.exhausted
                or wall_clock_result.exhausted
                or (model_calls_result is not None and model_calls_result.exhausted)
            ):
                return run.with_state(AgentRunState.BUDGET_EXCEEDED)

        return run.with_state(AgentRunState.COMPLETED)


def _governance_request(
    spec: AgentSpec, context: AgentRunContext, step: AgentStep
) -> GovernanceRequest:
    """One step, as the governance port sees it.

    ``tool_name``/``capability`` come from the step's own ``detail`` for
    a ``TOOL_CALL`` and are the step kind itself for a ``MODEL_CALL`` --
    a model call has no tool and no ``ToolCapability``, and inventing one
    would misreport it to an adapter. ``actor_roles`` is the run's
    ``required_role``, which ``AgentSpec.build`` already proved dominates
    every role the toolset needs, so it is the authority the run acts
    under rather than a guess.
    """

    detail = step.detail
    tool_name = detail.get("tool_name") if step.kind is StepKind.TOOL_CALL else None
    return GovernanceRequest(
        tenant_id=context.tenant_id,
        actor=context.actor,
        actor_roles=(spec.required_role.value,),
        tool_name=str(tool_name) if tool_name else step.kind.value,
        capability=step.kind.value,
        arguments=dict(detail),
        run_id=context.run_id,
        project_id=context.project_id,
        correlation_id=context.correlation_id,
    )


__all__ = ["DeterministicAgentLoop"]
