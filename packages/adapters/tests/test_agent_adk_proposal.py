"""R6-11a acceptance, ADK half: ``AdkAgentLoop`` stops discarding the
final turn, and reads the proposal off it.

The kits half (``AgentSpec.output_schema``, ``AgentRun.proposal``,
``complete_with_proposal``, ``DeterministicAgentLoop``) is in
``packages/kits/tests/test_agent_proposal.py``. The last test here is the
one that makes both halves worth having: the two ``AgentLoopPort``
implementations, given the same spec and the same proposal, produce the
same terminal state, the same proposal and the same answer on every
rejection case -- which is the alignment ADR-019's own "Negative"
consequence names as the risk of having two implementations.

Stub ``ModelGateway``, stub ``ToolInvokerPort``: no network, no
credential, no GCP project.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cairn_adapters.agent_adk import AdkAgentLoop
from cairn_adapters.agent_adk.translation import (
    AGENT_TURN_EXPECTATION,
    final_proposal,
)
from cairn_kernel.model import validate_structured_output
from cairn_kernel.model.ports import (
    ModelResponse,
    SafetyMetadata,
    StructuredOutputExpectation,
)
from cairn_kernel.security import Role
from cairn_kernel.testing.fakes import FixedClock
from cairn_kits.loop import (
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
#: Schema-invalid: ``workload_ids`` is required.
INVALID_PROPOSAL: dict[str, object] = {"summary": "no ids"}


class _StubModelGateway:
    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = responses
        self.calls: list[object] = []

    def generate(self, request: object) -> ModelResponse:
        index = len(self.calls)
        self.calls.append(request)
        return self._responses[min(index, len(self._responses) - 1)]


class _StubToolInvoker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def invoke(self, tool_name: str, arguments: dict) -> object:
        self.calls.append((tool_name, dict(arguments)))
        return {"echoed": arguments}


def _response(output: dict) -> ModelResponse:
    return ModelResponse(
        output=output,
        provider="fake",
        model="fake-model-v1",
        input_tokens=10,
        output_tokens=5,
        latency_ms=1,
        safety=SafetyMetadata(flagged=False),
        correlation_id="corr-1",
        tenant_id="tenant-1",
    )


def _prompt_registry(tmp_path: Path) -> PromptRegistry:
    agent_dir = tmp_path / "demo-agent"
    agent_dir.mkdir(exist_ok=True)
    (agent_dir / "system.v1.md").write_text(
        "---\nid: demo-agent/system\nversion: 1\n---\n\nYou help with estate questions.\n",
        encoding="utf-8",
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


def _loop(tmp_path: Path, responses: list[ModelResponse]) -> tuple[AdkAgentLoop, _StubModelGateway]:
    prompt_registry = _prompt_registry(tmp_path)
    mcp_registry = _mcp_registry()
    gateway = _StubModelGateway(responses)
    loop = AdkAgentLoop(
        model_gateway=gateway,  # type: ignore[arg-type]
        tool_invoker=_StubToolInvoker(),  # type: ignore[arg-type]
        mcp_registry=mcp_registry,
        prompt_registry=prompt_registry,
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    return loop, gateway


# --- agent_turn.v1 was extended, not replaced -------------------------------


def test_the_turn_schema_gained_proposal_and_kept_everything_else() -> None:
    """The gateway still reads a turn: the schema name does not move and
    no previously-declared field was taken away."""

    assert AGENT_TURN_EXPECTATION.schema_name == "agent_turn.v1"
    properties = AGENT_TURN_EXPECTATION.schema["properties"]
    assert set(properties) == {"kind", "tool_name", "tool_arguments", "text", "proposal"}
    assert AGENT_TURN_EXPECTATION.schema["required"] == ["kind"]


@pytest.mark.parametrize(
    "turn",
    [
        {"kind": "final", "text": "done"},
        {"kind": "tool_call", "tool_name": TOOL, "tool_arguments": {}},
        {"kind": "final", "proposal": PROPOSAL},
    ],
)
def test_a_turn_written_against_the_old_shape_still_validates(turn: dict) -> None:
    """Extending, not replacing: a turn with no ``proposal`` key is
    still a valid ``agent_turn.v1``, so nothing that produced the old
    shape starts failing at the gateway."""

    validate_structured_output(AGENT_TURN_EXPECTATION, turn)


# --- final_proposal, the reader ---------------------------------------------


def test_the_proposal_field_is_read_when_present() -> None:
    assert final_proposal({"kind": "final", "proposal": PROPOSAL}) == PROPOSAL


def test_json_text_is_read_as_the_fallback() -> None:
    assert final_proposal({"kind": "final", "text": json.dumps(PROPOSAL)}) == PROPOSAL


def test_malformed_json_text_yields_no_proposal() -> None:
    """Never a half-read proposal: text that does not parse gives
    ``None``, which the loop turns into a ``FAILED`` run."""

    assert final_proposal({"kind": "final", "text": '{"summary": "unterminated'}) is None


@pytest.mark.parametrize(
    "turn",
    [
        {"kind": "final", "text": "done"},
        {"kind": "final", "text": '["not", "an", "object"]'},
        {"kind": "final", "text": '"a bare string"'},
        {"kind": "final", "text": ""},
        {"kind": "final"},
        {"kind": "final", "proposal": "not an object"},
    ],
)
def test_anything_that_is_not_a_json_object_yields_no_proposal(turn: dict) -> None:
    assert final_proposal(turn) is None


# --- the loop terminates on the proposal ------------------------------------


def test_the_adk_loop_completes_on_a_final_turns_proposal(tmp_path: Path) -> None:
    loop, gateway = _loop(tmp_path, [_response({"kind": "final", "proposal": PROPOSAL})])

    run = loop.run(_spec(tmp_path), {"assessment_run_id": "ar-1"}, context=_context())

    assert run.state is AgentRunState.COMPLETED
    assert run.proposal == PROPOSAL
    assert len(gateway.calls) == 1


def test_the_adk_loop_completes_on_a_proposal_in_the_text_field(tmp_path: Path) -> None:
    loop, _ = _loop(tmp_path, [_response({"kind": "final", "text": json.dumps(PROPOSAL)})])

    run = loop.run(_spec(tmp_path), {}, context=_context("run-2"))

    assert run.state is AgentRunState.COMPLETED
    assert run.proposal == PROPOSAL


def test_the_adk_loop_fails_on_a_schema_invalid_proposal(tmp_path: Path) -> None:
    """Design §3's failure shape: not a retry, and nothing persisted --
    the run is ``FAILED``, carries the reason, and ``proposal`` is
    ``None``, so an application service above has nothing to persist."""

    loop, _ = _loop(tmp_path, [_response({"kind": "final", "proposal": INVALID_PROPOSAL})])

    run = loop.run(_spec(tmp_path), {}, context=_context("run-3"))

    assert run.state is AgentRunState.FAILED
    assert run.proposal is None
    assert "workload_ids" in (run.terminal_reason or "")


def test_the_adk_loop_fails_when_the_final_turn_carries_no_proposal(tmp_path: Path) -> None:
    loop, _ = _loop(tmp_path, [_response({"kind": "final", "text": "all done, thanks"})])

    run = loop.run(_spec(tmp_path), {}, context=_context("run-4"))

    assert run.state is AgentRunState.FAILED
    assert run.proposal is None
    assert run.terminal_reason == "agent run produced no final proposal"


def test_the_adk_loop_fails_on_malformed_json_in_the_final_turn(tmp_path: Path) -> None:
    loop, _ = _loop(tmp_path, [_response({"kind": "final", "text": '{"summary": "unterminated'})])

    run = loop.run(_spec(tmp_path), {}, context=_context("run-5"))

    assert run.state is AgentRunState.FAILED
    assert run.proposal is None
    assert run.terminal_reason == "agent run produced no final proposal"


def test_the_run_is_still_recorded_when_the_proposal_is_rejected(tmp_path: Path) -> None:
    """ADR-019 §5: a dead run is evidence, not an absence of it. The
    model call that produced the bad proposal is still a step."""

    recorder = InMemoryStepRecorder()
    context = AgentRunContext(
        run_id="run-6",
        tenant_id="tenant-1",
        actor="user-1",
        correlation_id="corr-1",
        budget_ledger=BudgetLedger(),
        step_recorder=recorder,
        project_id="project-1",
    )
    loop, _ = _loop(tmp_path, [_response({"kind": "final", "proposal": INVALID_PROPOSAL})])

    run = loop.run(_spec(tmp_path), {}, context=context)

    assert run.state is AgentRunState.FAILED
    assert [step.kind for step in run.steps] == [StepKind.MODEL_CALL]
    assert len(recorder.steps_for("run-6")) == 1


def test_a_proposal_arriving_after_the_budget_is_spent_is_not_a_proposal(tmp_path: Path) -> None:
    """The budget is debited before the turn is attempted, and the
    proposal is only read past the exhaustion check -- so a run whose
    last allowed model call is the one that proposes ends
    ``BUDGET_EXCEEDED`` carrying nothing. A spent run proposes nothing,
    even when the model did produce something valid."""

    loop, _ = _loop(
        tmp_path,
        [
            _response(
                {"kind": "tool_call", "tool_name": TOOL, "tool_arguments": {"workload_id": "w-1"}}
            ),
            # a perfectly valid proposal, on the turn that spends the
            # one model call past this run's budget
            _response({"kind": "final", "proposal": PROPOSAL}),
        ],
    )

    run = loop.run(
        _spec(tmp_path, budget=_budget(max_model_calls=1)), {}, context=_context("run-7")
    )

    assert run.state is AgentRunState.BUDGET_EXCEEDED
    assert run.proposal is None


# --- both implementations, one contract -------------------------------------


def _deterministic(tmp_path: Path, proposal: object) -> object:
    loop = DeterministicAgentLoop(
        (AgentStep(index=0, kind=StepKind.MODEL_CALL, detail={}),),
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        scripted_proposal=proposal,  # type: ignore[arg-type]
    )
    return loop.run(_spec(tmp_path), {}, context=_context("det"))


def _adk(tmp_path: Path, turn: dict) -> object:
    loop, _ = _loop(tmp_path, [_response(turn)])
    return loop.run(_spec(tmp_path), {}, context=_context("adk"))


@pytest.mark.parametrize(
    ("proposal", "turn", "expected_state"),
    [
        (PROPOSAL, {"kind": "final", "proposal": PROPOSAL}, AgentRunState.COMPLETED),
        (
            INVALID_PROPOSAL,
            {"kind": "final", "proposal": INVALID_PROPOSAL},
            AgentRunState.FAILED,
        ),
        (None, {"kind": "final", "text": "done"}, AgentRunState.FAILED),
        ({}, {"kind": "final", "proposal": {}}, AgentRunState.FAILED),
    ],
)
def test_both_loop_implementations_agree_on_the_same_proposal(
    tmp_path: Path, proposal: object, turn: dict, expected_state: AgentRunState
) -> None:
    """The alignment ADR-019 names as the cost of having two
    implementations, asserted rather than hoped for: same spec, same
    proposal, same terminal state and same carried proposal. Both go
    through ``complete_with_proposal``, which is why."""

    deterministic_run = _deterministic(tmp_path, proposal)
    adk_run = _adk(tmp_path, turn)

    assert deterministic_run.state is expected_state  # type: ignore[attr-defined]
    assert adk_run.state is expected_state  # type: ignore[attr-defined]
    assert deterministic_run.proposal == adk_run.proposal  # type: ignore[attr-defined]


def test_both_loop_implementations_produce_the_same_run_shape(tmp_path: Path) -> None:
    deterministic_run = _deterministic(tmp_path, PROPOSAL)
    adk_run = _adk(tmp_path, {"kind": "final", "proposal": PROPOSAL})

    assert type(deterministic_run) is type(adk_run)
    assert deterministic_run.agent_id == adk_run.agent_id  # type: ignore[attr-defined]
    assert deterministic_run.proposal == adk_run.proposal == PROPOSAL  # type: ignore[attr-defined]
    # identical content apart from the run id, so the sealed hash of one
    # is the sealed hash of the other once the ids match.
    assert deterministic_run.content_hash != adk_run.content_hash  # type: ignore[attr-defined]
