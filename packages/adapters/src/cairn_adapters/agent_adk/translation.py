"""R6-07: translating between ADK's chat-turn shape and CAIRN's
single-shot, structured ``ModelPort`` (ADR-014).

**Judgement call (turn-schema-vs-chat-api).** ``ModelPort.generate`` is
deliberately one method taking one prompt and one declared output
schema (design §2, ADR-014: "no authority to perform irreversible
actions" starts with the port having exactly one shape). ADK's own
``BaseLlm.generate_content_async`` is a chat-turn API: a conversation
history in, optionally a tool call or a final answer out. Rather than
growing ``ModelPort`` a second, chattier method (which would widen the
one surface R-AI-02's own test asserts has exactly one method), this
module renders the ADK conversation-so-far into a single prompt string
and asks every turn for the same small, fixed, versioned structured
shape -- "did you call a tool, or are you done" -- through the one
``ModelPort`` method that already exists. ``ModelGateway`` validates
every turn against this schema exactly as it validates anything else
(R-AI-01); nothing about the propose-only boundary or the run-budget
enforcement changes because the shape travelling through it is a turn
instead of a final proposal.
"""

from __future__ import annotations

from collections.abc import Mapping

from cairn_kernel.errors import ProviderUnavailableError, ValidationError
from cairn_kernel.model.ports import StructuredOutputExpectation

AGENT_TURN_SCHEMA_NAME = "agent_turn.v1"

AGENT_TURN_EXPECTATION = StructuredOutputExpectation(
    schema_name=AGENT_TURN_SCHEMA_NAME,
    schema={
        "type": "object",
        "required": ["kind"],
        "properties": {
            "kind": {"type": "string"},
            "tool_name": {"type": "string"},
            "tool_arguments": {"type": "object"},
            "text": {"type": "string"},
        },
    },
)

TURN_KIND_TOOL_CALL = "tool_call"
TURN_KIND_FINAL = "final"


def render_prompt(*, system_instruction: str, transcript_lines: list[str]) -> str:
    """One prompt string for this turn: the resolved system instruction
    (from :class:`cairn_kits.loop.PromptRegistry`, never a literal here)
    followed by the conversation so far, one line per turn. No prompt
    text is hardcoded in this module -- only short structural labels
    (``"user:"``, ``"tool result:"``), the same shape a chat transcript
    rendering always needs, well under A6.prompts' literal-length
    threshold.
    """

    lines = [system_instruction, "", *transcript_lines]
    return "\n".join(lines)


def output_to_llm_parts(
    output: Mapping[str, object],
) -> tuple[str, Mapping[str, object] | None, Mapping[str, object] | None]:
    """Parses one turn's validated ``ModelResponse.output`` (already
    schema-checked by ``ModelGateway`` against
    :data:`AGENT_TURN_EXPECTATION`) into ``(kind, tool_call, final_text)``
    -- never trusts anything past the gateway's own validation, but
    still checks the turn-specific invariants ``validate_structured_
    output`` has no reason to know about (a ``tool_call`` turn naming a
    real ``tool_name``).
    """

    kind = output.get("kind")
    if kind == TURN_KIND_TOOL_CALL:
        tool_name = output.get("tool_name")
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise ProviderUnavailableError(
                "agent turn declared kind=tool_call but carried no tool_name"
            )
        tool_arguments = output.get("tool_arguments")
        if tool_arguments is not None and not isinstance(tool_arguments, Mapping):
            raise ProviderUnavailableError("agent turn tool_arguments must be an object")
        return kind, {"name": tool_name, "arguments": dict(tool_arguments or {})}, None
    if kind == TURN_KIND_FINAL:
        text = output.get("text")
        if not isinstance(text, str):
            text = ""
        return kind, None, text
    raise ValidationError(
        f"agent turn kind {kind!r} is neither {TURN_KIND_TOOL_CALL!r} nor {TURN_KIND_FINAL!r}"
    )


__all__ = [
    "AGENT_TURN_EXPECTATION",
    "AGENT_TURN_SCHEMA_NAME",
    "TURN_KIND_FINAL",
    "TURN_KIND_TOOL_CALL",
    "output_to_llm_parts",
    "render_prompt",
]
