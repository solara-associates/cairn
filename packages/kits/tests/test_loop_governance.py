"""ADR-020 §4: ``DeterministicAgentLoop`` puts every step to the
governance port before attempting it.

This is the seam the MCP gateway cannot cover. A ``MODEL_CALL`` step
never goes near ``McpGateway.call_tool``, and a model call is exactly
where an agent run's budget goes -- so a budget ceiling enforced only at
the gateway would miss the thing it most needs to see.

The two claims, at this seam:

1. With the default no-op adapter -- or none passed at all -- the loop
   behaves exactly as R6-07 left it.
2. A test adapter can deny a step, and the run then ends ``FAILED`` with
   the reason on ``terminal_reason``, with the denied step never
   attempted, recorded or debited.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from cairn_kernel.governance import (
    GovernanceCheck,
    GovernanceDecision,
    GovernanceRequest,
    NoOpGovernance,
)
from cairn_kernel.model.ports import StructuredOutputExpectation
from cairn_kernel.security import Role
from cairn_kits.loop import (
    AgentRunState,
    AgentSpec,
    AgentStep,
    BudgetLedger,
    DeterministicAgentLoop,
    InMemoryStepRecorder,
    PromptRegistry,
    RunBudget,
    StepKind,
)
from cairn_kits.loop.ports import AgentRunContext
from cairn_kits.mcp import BoundedContextServer, McpRegistry, ToolCapability

TOOL = "estate.read_estate"


class SpyGovernance(NoOpGovernance):
    """Allows every step and records what it was asked, or denies the
    step at ``deny_at_index``."""

    def __init__(self, *, deny_at_index: int | None = None) -> None:
        self.requests: list[GovernanceRequest] = []
        self.recorded: list[GovernanceDecision] = []
        self._deny_at_index = deny_at_index

    def check_policy(self, request: GovernanceRequest) -> GovernanceDecision:
        self.requests.append(request)
        if (
            self._deny_at_index is not None
            and len(self.requests) - 1 == self._deny_at_index
        ):
            return GovernanceDecision.deny(
                GovernanceCheck.POLICY, reason="this run may not take that step"
            )
        return GovernanceDecision.allow(GovernanceCheck.POLICY)

    def record(self, request: GovernanceRequest, decision: GovernanceDecision) -> None:
        del request
        self.recorded.append(decision)


#: R6-11a: every ``AgentSpec`` now declares the shape of the one thing
#: it produces. A small two-field object is enough for this file's own
#: assertions, which are about the spec/loop contract, not about any
#: real agent's proposal shape.
_OUTPUT_SCHEMA = StructuredOutputExpectation(
    schema_name="demo_proposal.v1",
    schema={
        "type": "object",
        "required": ["summary"],
        "properties": {"summary": {"type": "string"}, "confidence": {"type": "number"}},
    },
)
_PROPOSAL: dict[str, object] = {"summary": "a proposal", "confidence": 0.5}


def _clock() -> object:
    class _Fixed:
        def now(self) -> datetime:
            return datetime(2026, 1, 1, tzinfo=UTC)

    return _Fixed()


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
            tools=(TOOL,),
            capabilities={TOOL: ToolCapability.READ},
            handle=lambda tool_name, arguments, principal: None,
        )
    )
    return registry


def _spec(tmp_path: Path) -> AgentSpec:
    return AgentSpec.build(
        agent_id="demo-agent",
        version=1,
        toolset=(TOOL,),
        required_role=Role.ENGINEER,
        prompt_references=(("demo-agent/system", 1),),
        budget=RunBudget(
            max_steps=10,
            max_model_calls=10,
            max_wall_clock_seconds=300,
            max_total_tokens=100_000,
            max_cost_micro_usd=500_000,
        ),
        output_schema=_OUTPUT_SCHEMA,
        prompt_registry=_prompt_registry(tmp_path),
        mcp_registry=_mcp_registry(),
        tool_roles={TOOL: Role.ENGINEER},
    )


def _context() -> AgentRunContext:
    return AgentRunContext(
        run_id="run-1",
        tenant_id="tenant-1",
        actor="user-1",
        correlation_id="corr-1",
        budget_ledger=BudgetLedger(),
        step_recorder=InMemoryStepRecorder(),
        project_id="project-1",
    )


def _steps() -> tuple[AgentStep, ...]:
    return (
        AgentStep(index=0, kind=StepKind.MODEL_CALL, detail={"prompt_id": "demo-agent/system"}),
        AgentStep(index=1, kind=StepKind.TOOL_CALL, detail={"tool_name": TOOL}),
    )


# -- the default changes nothing --------------------------------------


def test_the_loop_completes_unchanged_with_no_governance_passed(tmp_path: Path) -> None:
    loop = DeterministicAgentLoop(_steps(), clock=_clock(), scripted_proposal=_PROPOSAL)
    context = _context()

    run = loop.run(_spec(tmp_path), {}, context=context)

    assert run.state is AgentRunState.COMPLETED
    assert [step.index for step in run.steps] == [0, 1]
    assert context.step_recorder.steps_for(run.run_id) == run.steps
    assert run.terminal_reason is None


def test_the_loop_completes_unchanged_with_the_no_op_adapter(tmp_path: Path) -> None:
    loop = DeterministicAgentLoop(
        _steps(), clock=_clock(), governance=NoOpGovernance(), scripted_proposal=_PROPOSAL
    )

    run = loop.run(_spec(tmp_path), {}, context=_context())

    assert run.state is AgentRunState.COMPLETED
    assert [step.index for step in run.steps] == [0, 1]


def test_an_allowing_adapter_is_asked_about_every_step(tmp_path: Path) -> None:
    """Every step, model calls included -- which is the whole reason this
    seam exists alongside the gateway's."""

    governance = SpyGovernance()
    loop = DeterministicAgentLoop(
        _steps(), clock=_clock(), governance=governance, scripted_proposal=_PROPOSAL
    )

    run = loop.run(_spec(tmp_path), {}, context=_context())

    assert run.state is AgentRunState.COMPLETED
    assert [request.capability for request in governance.requests] == [
        StepKind.MODEL_CALL.value,
        StepKind.TOOL_CALL.value,
    ]
    assert len(governance.recorded) == 2


# -- a test adapter can deny ------------------------------------------


def test_a_denied_step_ends_the_run_failed_with_the_reason(tmp_path: Path) -> None:
    """A run refused by policy part-way through is a run *outcome*,
    recorded like any other -- not an exception for the caller to
    catch."""

    governance = SpyGovernance(deny_at_index=1)
    context = _context()
    loop = DeterministicAgentLoop(
        _steps(), clock=_clock(), governance=governance, scripted_proposal=_PROPOSAL
    )

    run = loop.run(_spec(tmp_path), {}, context=context)

    assert run.state is AgentRunState.FAILED
    assert run.terminal_reason is not None
    assert "governance denied step 1" in run.terminal_reason
    assert "POLICY" in run.terminal_reason
    assert "this run may not take that step" in run.terminal_reason


def test_a_denied_step_is_never_attempted_recorded_or_debited(tmp_path: Path) -> None:
    """Debit-before-attempt is the loop's own rule for budget; the
    governance check sits *before* that, so a denied step costs the run
    nothing at all."""

    governance = SpyGovernance(deny_at_index=1)
    context = _context()
    loop = DeterministicAgentLoop(
        _steps(), clock=_clock(), governance=governance, scripted_proposal=_PROPOSAL
    )

    run = loop.run(_spec(tmp_path), {}, context=context)

    assert [step.index for step in run.steps] == [0]
    assert [step.index for step in context.step_recorder.steps_for("run-1")] == [0]


def test_denying_the_first_step_ends_the_run_with_no_steps_at_all(tmp_path: Path) -> None:
    governance = SpyGovernance(deny_at_index=0)
    loop = DeterministicAgentLoop(
        _steps(), clock=_clock(), governance=governance, scripted_proposal=_PROPOSAL
    )

    run = loop.run(_spec(tmp_path), {}, context=_context())

    assert run.state is AgentRunState.FAILED
    assert run.steps == ()
    assert "governance denied step 0" in str(run.terminal_reason)


# -- what the port is told about a run ---------------------------------


def test_the_request_carries_the_run_context_the_gateway_cannot_know(
    tmp_path: Path,
) -> None:
    """``run_id``, ``project_id`` and ``correlation_id`` are not on a
    ``Principal``, so the gateway cannot supply them. A policy substrate
    deciding a *per-run* budget needs exactly these."""

    governance = SpyGovernance()
    loop = DeterministicAgentLoop(
        _steps(), clock=_clock(), governance=governance, scripted_proposal=_PROPOSAL
    )

    loop.run(_spec(tmp_path), {}, context=_context())

    request = governance.requests[0]
    assert request.run_id == "run-1"
    assert request.project_id == "project-1"
    assert request.correlation_id == "corr-1"
    assert request.tenant_id == "tenant-1"
    assert request.actor == "user-1"


def test_the_request_reports_the_runs_own_authority_not_a_guess(tmp_path: Path) -> None:
    """``AgentSpec.build`` already proved ``required_role`` dominates
    every role the toolset needs, so it is the authority the run acts
    under."""

    governance = SpyGovernance()
    loop = DeterministicAgentLoop(
        _steps(), clock=_clock(), governance=governance, scripted_proposal=_PROPOSAL
    )

    loop.run(_spec(tmp_path), {}, context=_context())

    assert governance.requests[0].actor_roles == (Role.ENGINEER.value,)


@pytest.mark.parametrize(
    ("index", "expected_tool_name"),
    [(0, StepKind.MODEL_CALL.value), (1, TOOL)],
)
def test_a_model_call_is_not_misreported_as_a_tool(
    tmp_path: Path, index: int, expected_tool_name: str
) -> None:
    """A model call has no tool and no ``ToolCapability``; inventing one
    would misreport it to an adapter."""

    governance = SpyGovernance()
    loop = DeterministicAgentLoop(
        _steps(), clock=_clock(), governance=governance, scripted_proposal=_PROPOSAL
    )

    loop.run(_spec(tmp_path), {}, context=_context())

    assert governance.requests[index].tool_name == expected_tool_name
