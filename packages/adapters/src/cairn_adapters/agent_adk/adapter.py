"""R6-07: ``AdkAgentLoop``, the only place an ADK type appears
(A6.port). Implements ``cairn_kits.loop.AgentLoopPort`` over Google's
Agent Development Kit (A1, A6.framework): ADK's own runner drives
plan -> tool call -> observation, CAIRN does not re-implement it.

Two bridges are the whole of this module's job, and both are narrow on
purpose:

- ``_GatewayBackedLlm`` -- an ADK ``BaseLlm`` whose
  ``generate_content_async`` delegates every call, unconditionally, to
  ``ModelGateway.generate`` with the run's ``agent_run_id``. No other
  code path in this module reaches a provider SDK, so no agent model
  call escapes the gateway's deny-list, rate limiter, breaker, schema
  validation, cost accounting or run budget (R-AGENT-05).
- a tool function built per name in ``spec.toolset``, whose body calls
  ``ToolInvokerPort.invoke`` and nothing else -- the adapter builds no
  tool outside that closed list, and ``before_tool_callback`` re-checks
  the invoked tool's declared capability one more time, deliberately
  redundant with ``AgentSpec.build()``'s own check, because this is the
  last gate before a tool actually runs (R-AGENT-03).

Both bridges debit ``BudgetLedger`` before the step they are about to
attempt and record the attempted step through ``StepRecorder`` even
when that debit comes back exhausted -- the same debit-before-attempt,
record-regardless shape ``DeterministicAgentLoop`` uses, so both
implementations can be asserted to produce an ``AgentRun`` of the same
shape.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from cairn_kernel.errors import ForbiddenError
from cairn_kernel.hex.ports import Clock
from cairn_kernel.model.ports import ModelPort, ModelRequest, SafetyParameters
from cairn_kits.loop.budget import BudgetDimension
from cairn_kits.loop.contract import AgentRun, AgentRunState, AgentSpec, AgentStep, StepKind
from cairn_kits.loop.ports import AgentRunContext, ToolInvokerPort
from cairn_kits.loop.prompt_registry import PromptRegistry
from cairn_kits.mcp import McpRegistry, ToolCapability

from cairn_adapters.agent_adk.translation import (
    AGENT_TURN_EXPECTATION,
    TURN_KIND_TOOL_CALL,
    output_to_llm_parts,
    render_prompt,
)


class _RunBudgetStopped(Exception):
    """Internal sentinel: a bridge debited past this run's budget. Caught
    only inside :meth:`AdkAgentLoop.run`, never allowed to escape this
    module."""


@dataclass(slots=True)
class _StepSink:
    """Collects the steps one run actually produced, in order -- both
    bridges share one instance per run so a tool-call step and the
    model-call steps around it land with contiguous, correct indices."""

    context: AgentRunContext
    steps: list[AgentStep] = field(default_factory=list)

    def next_index(self) -> int:
        return len(self.steps)

    def add(self, step: AgentStep) -> None:
        self.steps.append(step)
        self.context.step_recorder.record(self.context.run_id, step)


def _debit_step(sink: _StepSink, *, also_model_call: bool) -> bool:
    """Debits STEPS (and MODEL_CALLS, for a model-call step) before the
    step is attempted. Returns whether either debit came back
    exhausted."""

    ledger = sink.context.budget_ledger
    run_id = sink.context.run_id
    steps_result = ledger.debit(run_id, BudgetDimension.STEPS)
    exhausted = steps_result.exhausted
    if also_model_call:
        model_calls_result = ledger.debit(run_id, BudgetDimension.MODEL_CALLS)
        exhausted = exhausted or model_calls_result.exhausted
    return exhausted


class _GatewayBackedLlm:
    """The ADK model implementation. A thin wrapper is built lazily
    (``_build``) around ``google.adk.models.base_llm.BaseLlm`` so that
    importing this module -- and every module that imports it --
    does not require ``google-adk`` unless an ``AdkAgentLoop`` is
    actually constructed.
    """

    def __init__(
        self,
        *,
        model_gateway: ModelPort,
        context: AgentRunContext,
        sink: _StepSink,
        system_instruction: str,
    ) -> None:
        from google.adk.models.base_llm import BaseLlm
        from google.genai import types as genai_types

        model_gateway_ref = model_gateway
        context_ref = context
        sink_ref = sink
        system_instruction_ref = system_instruction

        class _Impl(BaseLlm):
            def __init__(self) -> None:
                super().__init__(model="cairn-model-gateway")

            async def generate_content_async(self, llm_request, stream: bool = False):  # type: ignore[override]
                transcript_lines = _render_transcript(llm_request, genai_types)
                prompt = render_prompt(
                    system_instruction=system_instruction_ref, transcript_lines=transcript_lines
                )
                request = ModelRequest(
                    prompt=prompt,
                    structured_output=AGENT_TURN_EXPECTATION,
                    safety=SafetyParameters(max_output_tokens=2048),
                    tenant_id=context_ref.tenant_id,
                    correlation_id=context_ref.correlation_id,
                    project_id=context_ref.project_id,
                    agent_run_id=context_ref.run_id,
                )

                exhausted = _debit_step(sink_ref, also_model_call=True)
                response = model_gateway_ref.generate(request)

                step = AgentStep(
                    index=sink_ref.next_index(),
                    kind=StepKind.MODEL_CALL,
                    detail={
                        "provider": response.provider,
                        "model": response.model,
                        "input_tokens": response.input_tokens,
                        "output_tokens": response.output_tokens,
                    },
                )
                sink_ref.add(step)

                if exhausted:
                    raise _RunBudgetStopped()

                kind, tool_call, final_text = output_to_llm_parts(response.output)
                if kind == TURN_KIND_TOOL_CALL:
                    part = genai_types.Part(
                        function_call=genai_types.FunctionCall(
                            name=sanitize_tool_name(tool_call["name"]),
                            args={"arguments": tool_call["arguments"]},
                        )
                    )
                else:
                    part = genai_types.Part(text=final_text)
                yield _llm_response(genai_types, part, response)

        self._impl = _Impl()

    @property
    def adk_model(self) -> Any:
        return self._impl


def _render_transcript(llm_request: Any, genai_types: Any) -> list[str]:
    lines: list[str] = []
    for content in getattr(llm_request, "contents", None) or ():
        role = getattr(content, "role", "user")
        for part in getattr(content, "parts", None) or ():
            if getattr(part, "text", None):
                lines.append(f"{role}: {part.text}")
            elif getattr(part, "function_call", None) is not None:
                call = part.function_call
                lines.append(f"{role}: tool_call {call.name} {dict(call.args or {})}")
            elif getattr(part, "function_response", None) is not None:
                response = part.function_response
                lines.append(f"{role}: tool_result {response.name} {response.response}")
    return lines


def _llm_response(genai_types: Any, part: Any, response: Any) -> Any:
    from google.adk.models.llm_response import LlmResponse

    return LlmResponse(
        content=genai_types.Content(role="model", parts=[part]),
        usage_metadata=genai_types.GenerateContentResponseUsageMetadata(
            prompt_token_count=response.input_tokens,
            candidates_token_count=response.output_tokens,
        ),
    )


def _build_tool_function(tool_name: str, tool_invoker: ToolInvokerPort, sink: _StepSink) -> Any:
    def _tool(arguments: dict | None = None) -> dict[str, object]:
        """Invokes one CAIRN MCP tool through ``ToolInvokerPort``."""

        exhausted = _debit_step(sink, also_model_call=False)
        result = tool_invoker.invoke(tool_name, dict(arguments or {}))

        step = AgentStep(
            index=sink.next_index(),
            kind=StepKind.TOOL_CALL,
            detail={"tool_name": tool_name, "arguments": dict(arguments or {})},
        )
        sink.add(step)

        if exhausted:
            raise _RunBudgetStopped()
        return {"result": result}

    _tool.__name__ = sanitize_tool_name(tool_name)
    return _tool


@dataclass(frozen=True, slots=True)
class AdkAgentLoop:
    """``AgentLoopPort`` implementation over ADK. ``model_gateway`` and
    ``tool_invoker`` are bound once, at construction -- the same
    dependency for every run this instance drives (design §7)."""

    model_gateway: ModelPort
    tool_invoker: ToolInvokerPort
    mcp_registry: McpRegistry
    prompt_registry: PromptRegistry
    clock: Clock

    def run(
        self,
        spec: AgentSpec,
        inputs: Mapping[str, object],
        *,
        context: AgentRunContext,
    ) -> AgentRun:
        from google.adk.agents import Agent
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.adk.tools import FunctionTool
        from google.genai import types as genai_types

        context.budget_ledger.start_run(context.run_id, spec.budget)
        run = AgentRun(
            run_id=context.run_id,
            agent_id=spec.agent_id,
            agent_version=spec.version,
            tenant_id=context.tenant_id,
            actor=context.actor,
            state=AgentRunState.PENDING,
        ).with_state(AgentRunState.RUNNING)

        sink = _StepSink(context=context)
        system_instruction = self._resolve_system_instruction(spec)

        model = _GatewayBackedLlm(
            model_gateway=self.model_gateway,
            context=context,
            sink=sink,
            system_instruction=system_instruction,
        )

        tools = [
            FunctionTool(_build_tool_function(tool_name, self.tool_invoker, sink))
            for tool_name in spec.toolset
        ]
        dotted_name_by_sanitized = {sanitize_tool_name(name): name for name in spec.toolset}

        def before_tool_callback(tool: Any, tool_args: Any, tool_context: Any) -> None:
            dotted_name = dotted_name_by_sanitized.get(tool.name, tool.name)
            self._check_tool_capability(dotted_name)

        agent = Agent(
            name=_adk_node_name(spec.agent_id),
            model=model.adk_model,
            instruction=system_instruction,
            tools=tools,
            before_tool_callback=before_tool_callback,
        )

        session_service = InMemorySessionService()
        session = asyncio.run(
            session_service.create_session(app_name=spec.agent_id, user_id=context.actor)
        )
        runner = Runner(agent=agent, app_name=spec.agent_id, session_service=session_service)

        opening_message = genai_types.Content(
            role="user", parts=[genai_types.Part(text=_render_inputs(inputs))]
        )

        try:
            for _event in runner.run(
                user_id=context.actor, session_id=session.id, new_message=opening_message
            ):
                pass
        except _RunBudgetStopped:
            terminal_state = AgentRunState.BUDGET_EXCEEDED
            terminal_reason = None
        except Exception as exc:  # noqa: BLE001 -- deliberately caught and
            # turned into AgentRunState.FAILED (design §3: "the run ends
            # FAILED with the validation error recorded"), not re-raised:
            # an agent run's own failure must land in its terminal state,
            # never crash the loop that is driving it.
            run = _apply_steps(run, sink.steps)
            return replace(run, terminal_reason=str(exc)).with_state(AgentRunState.FAILED)
        else:
            terminal_state = AgentRunState.COMPLETED
            terminal_reason = None

        run = _apply_steps(run, sink.steps)
        if terminal_reason is not None:
            run = replace(run, terminal_reason=terminal_reason)
        return run.with_state(terminal_state)

    def _resolve_system_instruction(self, spec: AgentSpec) -> str:
        """The first prompt reference is this agent's system
        instruction -- a judgement call (``AgentSpec`` does not itself
        distinguish a "system" prompt from any other), documented
        here rather than silently assumed; a concrete agent (Wave 4)
        is free to pass a richer, multi-prompt instruction by
        resolving more of ``spec.prompt_references`` itself before
        this loop ever sees it.
        """

        prompt_id, version = spec.prompt_references[0]
        artifact = self.prompt_registry.get(prompt_id, version)
        return artifact.body

    def _check_tool_capability(self, tool_name: str) -> None:
        capability = self.mcp_registry.capability_of(tool_name)
        if capability not in (ToolCapability.READ, ToolCapability.PROPOSE):
            raise ForbiddenError(
                f"tool {tool_name!r} declares capability {capability!r}, neither READ nor "
                "PROPOSE -- refused at the pre-tool callback"
            )


def sanitize_tool_name(tool_name: str) -> str:
    """ADK/Gemini function-calling names must be valid identifiers;
    CAIRN's own tool names are dotted (``estate.get_workload``). This
    is the one, single place that mapping happens -- both the model
    bridge (building a ``FunctionCall``) and the tool-function builder
    (naming the Python callable ADK introspects) call it, so the two
    sides can never drift apart.
    """

    return tool_name.replace(".", "__")


def _adk_node_name(agent_id: str) -> str:
    """ADK requires an ``Agent.name`` that is a valid Python identifier;
    CAIRN's own ``agent_id`` convention (``design-proposer``, with
    hyphens) is not one. The run's real identity stays ``spec.agent_id``
    everywhere else (``AgentRun.agent_id``, every step, every log) --
    this is purely cosmetic, ADK-internal node naming.
    """

    return agent_id.replace("-", "_")


def _apply_steps(run: AgentRun, steps: Sequence[AgentStep]) -> AgentRun:
    for step in steps:
        run = run.with_step(step)
    return run


def _render_inputs(inputs: Mapping[str, object]) -> str:
    import json

    return json.dumps(dict(inputs), sort_keys=True)


__all__ = ["AdkAgentLoop", "sanitize_tool_name"]
