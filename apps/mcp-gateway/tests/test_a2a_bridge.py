"""R5-04b: unit tests for the A2A bridge's own pieces -- agent-card
derivation and MCP<->A2A message translation -- independent of the
conformance suite in ``test_a2a_bridge_conformance.py``.
"""

from __future__ import annotations

from cairn_kits.mcp import BoundedContextServer
from cairn_mcp_gateway.a2a_bridge import (
    A2AMessage,
    A2AResult,
    AgentCard,
    a2a_message_to_mcp_call,
    a2a_result_to_mcp_result,
    agent_card_for,
    mcp_call_to_a2a_message,
    mcp_result_to_a2a_result,
)


def _server() -> BoundedContextServer:
    return BoundedContextServer(
        context_id="posture",
        name="posture",
        tools=("posture.get_control", "posture.list_controls"),
        handle=lambda tool_name, arguments: None,
    )


def test_agent_card_mirrors_the_bounded_context_server_it_is_derived_from() -> None:
    card = agent_card_for(_server())

    assert card == AgentCard(
        agent_id="posture",
        name="posture",
        skills=("posture.get_control", "posture.list_controls"),
    )


def test_mcp_call_translates_to_an_equivalent_a2a_message() -> None:
    message = mcp_call_to_a2a_message("posture.get_control", {"control_id": "gcp-cis-5.1"})

    assert message == A2AMessage(skill="posture.get_control", input={"control_id": "gcp-cis-5.1"})


def test_mcp_call_translation_defaults_missing_arguments_to_empty() -> None:
    message = mcp_call_to_a2a_message("posture.get_control", None)

    assert message.input == {}


def test_a2a_message_translates_back_to_an_equivalent_mcp_call() -> None:
    message = A2AMessage(skill="posture.get_control", input={"control_id": "gcp-cis-5.1"})

    tool_name, arguments = a2a_message_to_mcp_call(message)

    assert tool_name == "posture.get_control"
    assert arguments == {"control_id": "gcp-cis-5.1"}


def test_translation_round_trips_mcp_to_a2a_and_back() -> None:
    tool_name, arguments = "posture.get_control", {"control_id": "gcp-cis-5.1"}

    message = mcp_call_to_a2a_message(tool_name, arguments)
    round_tripped_tool_name, round_tripped_arguments = a2a_message_to_mcp_call(message)

    assert round_tripped_tool_name == tool_name
    assert round_tripped_arguments == arguments


def test_result_translates_both_directions() -> None:
    result = {"ok": True}

    a2a_result = mcp_result_to_a2a_result(result)
    assert a2a_result == A2AResult(output=result)
    assert a2a_result_to_mcp_result(a2a_result) == result
