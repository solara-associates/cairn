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

R6-11a adds the other half of a scripted run: ``scripted_proposal``,
the final structured output this run "produced". It goes through
exactly the same gate ``AdkAgentLoop`` puts a real final turn through
(``AgentRun.with_proposal``, which validates against
``spec.output_schema``), so a scripted proposal that does not satisfy
the agent's own schema fails the run here just as a model-produced one
would -- which is the point of having both implementations: a Wave 4
test written against this loop is testing the same contract the ADK
loop obeys. A loop constructed with no ``scripted_proposal`` ends
``FAILED``: a run that reaches the end of its script with nothing to
propose has not succeeded at the one thing an agent does.
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
from cairn_kits.loop.contract import (
    AgentRun,
    AgentRunState,
    AgentSpec,
    AgentStep,
    StepKind,
    complete_with_proposal,
)
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
    budget can never be exceeded by more than one step's worth"), and
    its ``scripted_proposal`` is **not** attached -- a budget-stopped
    run proposes nothing, even if the script said it would.
    Otherwise, once every scripted step has been replayed, the
    ``scripted_proposal`` is validated against ``spec.output_schema``
    and the run ends ``COMPLETED``; a missing or schema-invalid
    proposal ends it ``FAILED`` with the reason recorded.
    """

    def __init__(
        self,
        scripted_steps: Sequence[AgentStep],
        clock: Clock,
        governance: GovernancePort | None = None,
        scripted_proposal: Mapping[str, object] | None = None,
    ) -> None:
        self._scripted_steps = tuple(scripted_steps)
        self._clock = clock
        self._governance = governance if governance is not None else NoOpGovernance()
        self._scripted_proposal = scripted_proposal

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

        return complete_with_proposal(run, spec, self._scripted_proposal)


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
