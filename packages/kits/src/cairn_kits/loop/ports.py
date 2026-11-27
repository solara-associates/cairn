"""R6-07: the two outbound ports an :class:`AgentLoopPort` implementation
needs, and the run-scoped context ``run`` is called with.

Neither port names a tool's real behaviour or a provider: ``ToolInvokerPort``
is bound, above this package, to ``McpGateway.call_tool`` (or a fake, for
tests); ``AgentLoopPort`` itself is bound to either
``cairn_adapters.agent_adk``'s ADK-backed implementation or
``DeterministicAgentLoop`` (this package). Nothing here imports
``cairn_adapters`` or ``cairn_modules`` (``kits-purity``): a port is a
shape, not a wiring.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from cairn_kernel.errors import ValidationError
from cairn_kernel.hex.primitives import Port

from cairn_kits.loop.budget import BudgetLedger
from cairn_kits.loop.contract import AgentRun, AgentSpec, AgentStep


class ToolInvokerPort(Port, Protocol):
    """Invokes one already-authorized tool call. Bound above this
    package to the real gateway; carries no authority itself -- the
    capability and role checks happen before this is ever reached
    (``AgentSpec.build`` at construction, the loop's pre-tool check at
    call time)."""

    def invoke(self, tool_name: str, arguments: Mapping[str, object]) -> object: ...


class StepRecorder(Protocol):
    """Durably records one :class:`AgentStep` for a run. R6-15 gives
    this a real implementation (audit entry + evidence envelope); the
    in-memory one here is the test/default."""

    def record(self, run_id: str, step: AgentStep) -> None: ...


class InMemoryStepRecorder:
    """Reference ``StepRecorder``: a dict of lists, keyed by ``run_id``."""

    def __init__(self) -> None:
        self._steps: dict[str, list[AgentStep]] = {}

    def record(self, run_id: str, step: AgentStep) -> None:
        self._steps.setdefault(run_id, []).append(step)

    def steps_for(self, run_id: str) -> tuple[AgentStep, ...]:
        return tuple(self._steps.get(run_id, ()))


@dataclass(frozen=True, slots=True)
class AgentRunContext:
    """Everything identifying *this* run that both loop implementations
    need and neither owns: who started it, which tenant/project it is
    scoped to, and the shared ledger/recorder it reports through.
    Deliberately absent: any model or tool binding -- those are each
    ``AgentLoopPort`` implementation's own constructor dependency, not
    part of the per-call context, because they are the same for every
    run a given loop instance drives."""

    run_id: str
    tenant_id: str
    actor: str
    correlation_id: str
    budget_ledger: BudgetLedger
    step_recorder: StepRecorder
    project_id: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("run_id", self.run_id),
            ("tenant_id", self.tenant_id),
            ("actor", self.actor),
            ("correlation_id", self.correlation_id),
        ):
            if not value.strip():
                raise ValidationError(f"agent run context {field_name} must not be blank")


class AgentLoopPort(Port, Protocol):
    """Drives one agent run to a terminal state (design §7). Bound to
    exactly one real implementation per deployment
    (``cairn_adapters.agent_adk``) and to ``DeterministicAgentLoop``
    everywhere in this repository's own tests -- both produce an
    ``AgentRun`` of the same shape."""

    def run(
        self,
        spec: AgentSpec,
        inputs: Mapping[str, object],
        *,
        context: AgentRunContext,
    ) -> AgentRun: ...


__all__ = [
    "AgentLoopPort",
    "AgentRunContext",
    "InMemoryStepRecorder",
    "StepRecorder",
    "ToolInvokerPort",
]
