"""R5-04b: the A2A bridge in front of 818's registry/gateway (ADR-011).

ADR-011 says the gateway "handles auth, per-tenant authorization, rate
limits and audit" for MCP traffic, and separately that "an A2A bridge
publishes agent cards and translates A2A tasks to the same application
services." This module is that bridge, built strictly as a second path
*onto* 818's existing ``McpGateway``/``McpRegistry`` -- it does not
reimplement authentication, authorization, or tool resolution. The bridge
only does two things the MCP path does not: publish an agent-card view of
each registered ``BoundedContextServer``, and translate between an MCP
tool call shape (``tool_name``, ``arguments``) and an A2A message shape
(``skill``, ``input``) in both directions.

**Scope note (judgement call):** A2A's real wire protocol (JSON-RPC over
HTTP/SSE, task lifecycle states, push notifications, signed agent cards,
etc.) is out of scope here. ADR-011 only commits to an internal bridge
until R5, and this unit's brief is explicit that guessing at external
wire-format conformance is worse than a clearly-documented minimal shape.
``AgentCard`` and ``A2AMessage``/``A2AResult`` below capture exactly the
information 818's ``BoundedContextServer`` and ``ToolHandle`` already
carry (an id/name and the skills/tools it exposes; a call's name and
arguments; a call's result) in A2A's vocabulary, nothing more. A later
unit that needs to speak to a real external A2A peer should replace this
module's wire encoding, not its shape.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from cairn_kits.mcp import BoundedContextServer, McpRegistry, ToolNotRegisteredError

from cairn_mcp_gateway.gateway import McpGateway


@dataclass(frozen=True, slots=True)
class AgentCard:
    """A minimal, internal A2A agent-card: an agent's self-description.

    ``agent_id`` is 818's ``BoundedContextServer.context_id`` -- in this
    internal-only bridge, one bounded-context server *is* one A2A agent,
    so no separate identity scheme is invented. ``skills`` mirrors
    ``BoundedContextServer.tools``: the names of the capabilities this
    agent exposes, in A2A's vocabulary.
    """

    agent_id: str
    name: str
    skills: tuple[str, ...]


def agent_card_for(server: BoundedContextServer) -> AgentCard:
    """Derive a ``BoundedContextServer``'s agent card.

    A pure projection -- the card carries no information the registry
    didn't already have, by design: this bridge must not become a second
    source of truth about which bounded context owns which capability.
    """
    return AgentCard(agent_id=server.context_id, name=server.name, skills=server.tools)


def agent_cards_for_registry(registry: McpRegistry) -> tuple[AgentCard, ...]:
    """The agent-card exchange: every registered server's card, derived
    fresh from the registry each call so a card can never drift from
    what is actually registered."""
    return tuple(agent_card_for(server) for server in registry.servers())


@dataclass(frozen=True, slots=True)
class A2AMessage:
    """An A2A task request: a ``skill`` to invoke and its ``input``.

    Equivalent in shape to an MCP tool call's ``(tool_name, arguments)``
    -- see ``mcp_call_to_a2a_message``/``a2a_message_to_mcp_call`` for the
    translation between the two.
    """

    skill: str
    input: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class A2AResult:
    """An A2A task result: the ``output`` produced by the invoked skill."""

    output: object


def mcp_call_to_a2a_message(
    tool_name: str, arguments: Mapping[str, object] | None = None
) -> A2AMessage:
    """Translate an MCP tool call into its equivalent A2A message."""
    return A2AMessage(skill=tool_name, input=dict(arguments or {}))


def a2a_message_to_mcp_call(message: A2AMessage) -> tuple[str, dict[str, object]]:
    """Translate an A2A message into its equivalent MCP tool call
    ``(tool_name, arguments)`` pair."""
    return message.skill, dict(message.input)


def mcp_result_to_a2a_result(result: object) -> A2AResult:
    """Translate an MCP tool call's return value into an A2A result."""
    return A2AResult(output=result)


def a2a_result_to_mcp_result(result: A2AResult) -> object:
    """Translate an A2A result back into an MCP tool call's return value."""
    return result.output


@dataclass(frozen=True, slots=True)
class A2ABridge:
    """The A2A path onto 818's gateway.

    Deliberately holds no registry or authenticator of its own: every
    call is routed through the same ``McpGateway.call_tool`` the MCP path
    uses, so authentication, authorization and tool resolution happen
    exactly once, in exactly one place, for both paths. The bridge's own
    job is strictly agent-card publication and message translation.
    """

    gateway: McpGateway

    def agent_cards(self) -> tuple[AgentCard, ...]:
        """Publish an agent card for every bounded-context server
        reachable through this bridge -- the "agent card exchange"."""
        return agent_cards_for_registry(self.gateway.registry)

    def _agent_card_for_skill(self, skill: str) -> AgentCard | None:
        for card in self.agent_cards():
            if skill in card.skills:
                return card
        return None

    def send_task(
        self,
        *,
        agent_id: str,
        skill: str,
        token: str,
        input: Mapping[str, object] | None = None,
    ) -> A2AResult:
        """Send an A2A task to ``agent_id`` for ``skill``.

        Translates to an MCP tool call and invokes it through the shared
        ``McpGateway`` (same auth/authorization/registry lookup as the
        MCP path), then translates the result back to A2A shape.

        Raises ``ToolNotRegisteredError`` -- the *same* error 818's
        registry/gateway raises for an unregistered MCP tool -- when
        ``agent_id`` names no known agent, or when that agent does not
        expose ``skill``. An unregistered skill never silently falls
        through to some other agent's handle.
        """
        card = self._agent_card_for_skill(skill)
        if card is None or card.agent_id != agent_id:
            raise ToolNotRegisteredError(
                f"no agent {agent_id!r} exposes skill {skill!r} through the A2A bridge"
            )

        message = A2AMessage(skill=skill, input=input or {})
        tool_name, arguments = a2a_message_to_mcp_call(message)
        result = self.gateway.call_tool(tool_name, token, arguments)
        return mcp_result_to_a2a_result(result)


__all__ = [
    "A2ABridge",
    "A2AMessage",
    "A2AResult",
    "AgentCard",
    "a2a_message_to_mcp_call",
    "a2a_result_to_mcp_result",
    "agent_card_for",
    "agent_cards_for_registry",
    "mcp_call_to_a2a_message",
    "mcp_result_to_a2a_result",
]
