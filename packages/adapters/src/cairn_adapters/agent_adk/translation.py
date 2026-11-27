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
enforcement changes because the shape travelling through it is a turn.

**R6-11a: the final turn now carries the proposal.** The paragraph
above used to end "...a turn instead of a final proposal", and the
loop discarded the final turn's content accordingly -- which left an
agent's one real output with nowhere to go, and is the gap this unit
closes. ``agent_turn.v1`` is *extended*, not replaced: ``kind`` and
``tool_name``/``tool_arguments`` are unchanged, ``text`` is still
there and still optional, and a new optional ``proposal`` object
carries the structured output. So the gateway still reads a turn, the
schema name and version do not move, and a turn written against the
old shape still validates.

A ``final`` turn's proposal is read in this order, and the order is
the honest part: ``proposal`` if the model filled it in; otherwise
``text`` parsed as a JSON object, because a model asked for JSON will
sometimes put it in the text field and refusing to look there would
fail runs for a formatting reason rather than a substantive one.
Text that is not parseable JSON, or parses to something that is not an
object, yields no proposal at all -- never a half-read one -- and the
loop ends the run ``FAILED``. This function does **not** check the
proposal against the agent's own ``output_schema``: that is
``cairn_kits.loop.complete_with_proposal``'s job, so both
``AgentLoopPort`` implementations apply the identical check in the
identical place.
"""

from __future__ import annotations

import json
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
            "proposal": {"type": "object"},
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
) -> tuple[str, Mapping[str, object] | None, str | None]:
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


def final_proposal(output: Mapping[str, object]) -> Mapping[str, object] | None:
    """R6-11a: the structured proposal a ``final`` turn carries, or
    ``None`` if it carries none this function can read as an object.

    ``proposal`` is preferred; ``text`` parsed as JSON is the fallback
    (see this module's own docstring for why both are accepted and why
    neither is partially read). Returning ``None`` is not an error
    here: it is the input ``complete_with_proposal`` turns into a
    ``FAILED`` run with a recorded reason, which is where that decision
    belongs.
    """

    proposal = output.get("proposal")
    if isinstance(proposal, Mapping):
        return dict(proposal)
    if proposal is not None:
        return None

    text = output.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


__all__ = [
    "AGENT_TURN_EXPECTATION",
    "AGENT_TURN_SCHEMA_NAME",
    "TURN_KIND_FINAL",
    "TURN_KIND_TOOL_CALL",
    "final_proposal",
    "output_to_llm_parts",
    "render_prompt",
]
