"""R6-07 acceptance: ``AdkAgentLoop`` over a real ADK ``Agent``/``Runner``,
with a stub ``ModelGateway`` and a stub ``ToolInvokerPort`` standing in
for the real ones -- no network, no real credential, no GCP project.
"""

from __future__ import annotations

import ast
import inspect
import typing
from datetime import UTC, datetime
from pathlib import Path

from cairn_adapters.agent_adk import AdkAgentLoop, sanitize_tool_name
from cairn_kernel.model.ports import ModelResponse, SafetyMetadata
from cairn_kernel.security import Role
from cairn_kernel.testing.fakes import FixedClock
from cairn_kits.loop import (
    AgentRunState,
    AgentSpec,
    BudgetLedger,
    InMemoryStepRecorder,
    PromptRegistry,
    RunBudget,
    StepKind,
)
from cairn_kits.loop.ports import AgentRunContext
from cairn_kits.mcp import BoundedContextServer, McpRegistry, ToolCapability

REPO_ROOT = Path(__file__).resolve().parents[3]
AGENT_ADK_PACKAGE = Path(__file__).resolve().parents[1] / "src" / "cairn_adapters" / "agent_adk"


class _StubModelGateway:
    """Stands in for ``cairn_kernel.model.ModelGateway``: records every
    call it receives, in order, and returns the next canned response --
    exactly the property the run sheet's acceptance asks for ("the
    count equals the run's model-call count")."""

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
    agent_dir.mkdir()
    (agent_dir / "system.v1.md").write_text(
        "---\nid: demo-agent/system\nversion: 1\n---\n\nYou help with estate questions.\n",
        encoding="utf-8",
    )
    return PromptRegistry.load(tmp_path)


def _mcp_registry(capability: ToolCapability = ToolCapability.READ) -> McpRegistry:
    registry = McpRegistry()
    registry.register(
        BoundedContextServer(
            context_id="estate",
            name="estate",
            tools=("estate.read_estate",),
            capabilities={"estate.read_estate": capability},
            handle=lambda tool_name, arguments: None,
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


def _spec(
    prompt_registry: PromptRegistry, mcp_registry: McpRegistry, **overrides: object
) -> AgentSpec:
    kwargs: dict[str, object] = {
        "agent_id": "demo-agent",
        "version": 1,
        "toolset": ("estate.read_estate",),
        "required_role": Role.ENGINEER,
        "prompt_references": (("demo-agent/system", 1),),
        "budget": _budget(),
        "prompt_registry": prompt_registry,
        "mcp_registry": mcp_registry,
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


def _loop(model_gateway, tool_invoker, mcp_registry, prompt_registry) -> AdkAgentLoop:
    return AdkAgentLoop(
        model_gateway=model_gateway,
        tool_invoker=tool_invoker,
        mcp_registry=mcp_registry,
        prompt_registry=prompt_registry,
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
    )


def test_every_model_call_goes_through_the_gateway_no_call_escapes(tmp_path: Path) -> None:
    prompt_registry = _prompt_registry(tmp_path)
    mcp_registry = _mcp_registry()
    model_gateway = _StubModelGateway(
        [
            _response(
                {
                    "kind": "tool_call",
                    "tool_name": "estate.read_estate",
                    "tool_arguments": {"workload_id": "w-1"},
                }
            ),
            _response({"kind": "final", "text": "done"}),
        ]
    )
    tool_invoker = _StubToolInvoker()
    spec = _spec(prompt_registry, mcp_registry)
    loop = _loop(model_gateway, tool_invoker, mcp_registry, prompt_registry)

    run = loop.run(spec, {"assessment_run_id": "ar-1"}, context=_context())

    assert run.state is AgentRunState.COMPLETED
    model_call_steps = [s for s in run.steps if s.kind is StepKind.MODEL_CALL]
    assert len(model_call_steps) == len(model_gateway.calls)
    assert len(model_gateway.calls) == 2
    assert tool_invoker.calls == [("estate.read_estate", {"workload_id": "w-1"})]


def test_adapter_builds_no_tool_outside_the_spec_toolset(tmp_path: Path) -> None:
    prompt_registry = _prompt_registry(tmp_path)
    mcp_registry = _mcp_registry()
    model_gateway = _StubModelGateway([_response({"kind": "final", "text": "done"})])
    tool_invoker = _StubToolInvoker()
    spec = _spec(prompt_registry, mcp_registry)
    loop = _loop(model_gateway, tool_invoker, mcp_registry, prompt_registry)

    # Build the Agent the same way .run() does, capturing it, so we can
    # assert on its tool list without re-deriving the construction logic.
    from google.adk.agents import Agent as RealAgent

    built_agents: list[RealAgent] = []
    original_init = RealAgent.__init__

    def _capturing_init(self, *args: object, **kwargs: object) -> None:
        built_agents.append(self)
        original_init(self, *args, **kwargs)

    RealAgent.__init__ = _capturing_init  # type: ignore[method-assign]
    try:
        loop.run(spec, {}, context=_context("run-2"))
    finally:
        RealAgent.__init__ = original_init  # type: ignore[method-assign]

    assert len(built_agents) == 1
    tool_names = {tool.name for tool in built_agents[0].tools}
    # ADK/Gemini function names must be identifiers; CAIRN's dotted tool
    # names are translated at the boundary (sanitize_tool_name) -- this
    # still proves the adapter built exactly the spec's own toolset and
    # nothing else, one tool per declared name, no more.
    assert tool_names == {sanitize_tool_name(name) for name in spec.toolset}


def test_pre_tool_callback_refuses_a_non_read_or_propose_capability_even_past_construction(
    tmp_path: Path,
) -> None:
    """The redundant, last-gate check (design §7): force a toolset whose
    capability is neither READ nor PROPOSE past ``AgentSpec.build()`` by
    substituting a registry whose ``capability_of`` returns a value
    outside the enum -- the only way to simulate "forced past
    construction" since the real ``ToolCapability`` enum has no third
    value for a real registry to ever declare.
    """

    prompt_registry = _prompt_registry(tmp_path)

    class _BadRegistry:
        def capability_of(self, tool_name: str) -> str:
            return "EXECUTE"

    mcp_registry = _mcp_registry()  # used to pass AgentSpec.build()'s own check
    spec = _spec(prompt_registry, mcp_registry)

    bad_registry = _BadRegistry()
    model_gateway = _StubModelGateway(
        [
            _response(
                {
                    "kind": "tool_call",
                    "tool_name": "estate.read_estate",
                    "tool_arguments": {},
                }
            )
        ]
    )
    tool_invoker = _StubToolInvoker()
    loop = AdkAgentLoop(
        model_gateway=model_gateway,
        tool_invoker=tool_invoker,
        mcp_registry=bad_registry,  # type: ignore[arg-type]
        prompt_registry=prompt_registry,
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
    )

    run = loop.run(spec, {}, context=_context("run-3"))

    # the tool was never actually invoked -- the before_tool_callback's
    # ForbiddenError stopped it before the tool function's body ran.
    assert tool_invoker.calls == []
    assert run.state is AgentRunState.FAILED


def test_budget_exhaustion_stops_the_run(tmp_path: Path) -> None:
    prompt_registry = _prompt_registry(tmp_path)
    mcp_registry = _mcp_registry()
    model_gateway = _StubModelGateway(
        [
            _response(
                {"kind": "tool_call", "tool_name": "estate.read_estate", "tool_arguments": {}}
            ),
            _response({"kind": "final", "text": "done"}),
        ]
    )
    tool_invoker = _StubToolInvoker()
    # one model call is allowed; the second (after the tool call/result
    # round trip) is the one that exceeds it.
    spec = _spec(prompt_registry, mcp_registry, budget=_budget(max_model_calls=1))
    loop = _loop(model_gateway, tool_invoker, mcp_registry, prompt_registry)

    run = loop.run(spec, {}, context=_context("run-4"))

    assert run.state is AgentRunState.BUDGET_EXCEEDED
    model_call_steps = [s for s in run.steps if s.kind is StepKind.MODEL_CALL]
    assert len(model_call_steps) == 2


def test_no_adk_type_appears_in_the_loops_public_signatures() -> None:
    for name, member in inspect.getmembers(AdkAgentLoop):
        if name.startswith("_"):
            continue
        if not (inspect.isfunction(member) or inspect.ismethod(member)):
            continue
        signature = inspect.signature(member)
        for parameter in signature.parameters.values():
            annotation = parameter.annotation
            assert "adk" not in str(annotation).lower(), (
                f"AdkAgentLoop.{name} parameter {parameter.name!r} names an ADK type: "
                f"{annotation!r}"
            )
        assert "adk" not in str(signature.return_annotation).lower()

    for field_name, field_type in typing.get_type_hints(AdkAgentLoop).items():
        assert "adk" not in str(field_type).lower(), (
            f"AdkAgentLoop field {field_name!r} names an ADK type: {field_type!r}"
        )


def _modules_importing_adk(root: Path, *, exclude: Path) -> dict[str, list[str]]:
    """Scans every package/app's own ``src/`` tree -- production source
    only. Test files are deliberately out of scope: a test exercising
    this adapter's internals (this file included) may legitimately
    import ``google.adk`` itself to assert against it, the same way
    this repository's other framework-confinement tests are themselves
    exempt from the rule they check.
    """

    violations: dict[str, list[str]] = {}
    for src_dir in sorted(root.glob("*/*/src")) + sorted(root.glob("*/src")):
        for path in sorted(src_dir.rglob("*.py")):
            if exclude in path.parents or path == exclude:
                continue
            parts = set(path.parts)
            if parts & {".venv", "__pycache__", "node_modules", "target", ".git"}:
                continue
            _scan_for_adk_import(path, root, violations)
    return violations


def _scan_for_adk_import(path: Path, root: Path, violations: dict[str, list[str]]) -> None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            hits.extend(alias.name for alias in node.names if alias.name.startswith("google.adk"))
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("google.adk")
        ):
            hits.append(node.module)
    if hits:
        violations[str(path.relative_to(root))] = hits


def test_adk_import_confined_to_this_package() -> None:
    """A6.port / R-AGENT-06, proved directly against the source.

    **Tooling limitation, stated plainly:** ``import-linter`` (pinned
    in this repo) refuses a *subpackage* of an external package as a
    ``forbidden_modules`` entry ("subpackages of external packages are
    not valid") -- so ``.importlinter`` cannot express "no module but
    ``cairn_adapters.agent_adk`` imports ``google.adk``" the way
    ``loop-cannot-execute`` expresses its own, internal-only version of
    the same rule. Forbidding the whole ``google`` namespace would also
    catch ``google.genai``/``google.cloud.kms``, which several other
    adapters import legitimately (R6-06, ``evidence_kms``) -- too
    broad to be the right contract. This AST scan is the correct
    mechanism here, not a workaround for one the tool already covers:
    it is this repository's only enforcement of R-AGENT-06.
    """

    violations = _modules_importing_adk(REPO_ROOT, exclude=AGENT_ADK_PACKAGE)
    assert not violations, f"only cairn_adapters.agent_adk may import google.adk: {violations}"
