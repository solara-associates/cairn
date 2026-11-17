"""R5-04a: the shared ``cairn_kits.mcp`` registry (ADR-011)."""

from __future__ import annotations

import pytest
from cairn_kits.mcp import (
    BoundedContextServer,
    DuplicateToolRegistrationError,
    McpRegistry,
    ToolNotRegisteredError,
)


def _server(
    context_id: str, tools: tuple[str, ...], calls: list[tuple[str, dict]]
) -> BoundedContextServer:
    def handle(tool_name: str, arguments: dict) -> object:
        calls.append((tool_name, dict(arguments)))
        return {"tool": tool_name, "context": context_id, "arguments": arguments}

    return BoundedContextServer(context_id=context_id, name=context_id, tools=tools, handle=handle)


def test_lookup_returns_the_correct_bounded_context_server_for_a_tool_name() -> None:
    registry = McpRegistry()
    posture_calls: list[tuple[str, dict]] = []
    finops_calls: list[tuple[str, dict]] = []
    posture = _server("posture", ("posture.get_control",), posture_calls)
    finops = _server("finops", ("finops.get_budget",), finops_calls)
    registry.register(posture)
    registry.register(finops)

    registration = registry.lookup("finops.get_budget")

    assert registration.server is finops
    assert registration.server.context_id == "finops"
    assert registration.tool_name == "finops.get_budget"

    other = registry.lookup("posture.get_control")
    assert other.server is posture


def test_invoke_calls_the_resolved_servers_own_handle_only() -> None:
    registry = McpRegistry()
    posture_calls: list[tuple[str, dict]] = []
    finops_calls: list[tuple[str, dict]] = []
    registry.register(_server("posture", ("posture.get_control",), posture_calls))
    registry.register(_server("finops", ("finops.get_budget",), finops_calls))

    result = registry.invoke("finops.get_budget", {"budget_id": "b1"})

    assert result == {
        "tool": "finops.get_budget",
        "context": "finops",
        "arguments": {"budget_id": "b1"},
    }
    assert finops_calls == [("finops.get_budget", {"budget_id": "b1"})]
    assert posture_calls == []


def test_lookup_for_an_unregistered_tool_fails_cleanly() -> None:
    registry = McpRegistry()
    registry.register(_server("posture", ("posture.get_control",), []))

    with pytest.raises(ToolNotRegisteredError):
        registry.lookup("does.not.exist")


def test_invoke_for_an_unregistered_tool_also_fails_cleanly_without_calling_anything() -> None:
    registry = McpRegistry()
    calls: list[tuple[str, dict]] = []
    registry.register(_server("posture", ("posture.get_control",), calls))

    with pytest.raises(ToolNotRegisteredError):
        registry.invoke("does.not.exist")

    assert calls == []


def test_empty_registry_rejects_every_lookup() -> None:
    registry = McpRegistry()

    with pytest.raises(ToolNotRegisteredError):
        registry.lookup("anything")


def test_registering_the_same_tool_name_under_two_contexts_is_rejected() -> None:
    registry = McpRegistry()
    registry.register(_server("posture", ("shared.tool",), []))

    with pytest.raises(DuplicateToolRegistrationError):
        registry.register(_server("finops", ("shared.tool",), []))


def test_a_server_must_expose_at_least_one_tool() -> None:
    def handle(tool_name: str, arguments: dict) -> object:
        return None

    with pytest.raises(ValueError):
        BoundedContextServer(context_id="empty", name="empty", tools=(), handle=handle)


def test_tool_names_lists_every_registered_tool_sorted() -> None:
    registry = McpRegistry()
    registry.register(_server("finops", ("finops.get_budget", "finops.list_budgets"), []))
    registry.register(_server("posture", ("posture.get_control",), []))

    assert registry.tool_names() == (
        "finops.get_budget",
        "finops.list_budgets",
        "posture.get_control",
    )
