"""R6-05: tool capabilities and the propose-only boundary (ADR-019 §1,
R-AGENT-03)."""

from __future__ import annotations

from pathlib import Path

import pytest
from cairn_kernel.errors import MissingDependencyError, ValidationError
from cairn_kernel.model.ports import StructuredOutputExpectation
from cairn_kernel.security import Role
from cairn_kits.loop import AgentSpec, PromptRegistry, RunBudget
from cairn_kits.mcp import BoundedContextServer, McpRegistry, ToolCapability, ToolNotRegisteredError

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


def _budget() -> RunBudget:
    return RunBudget(
        max_steps=10,
        max_model_calls=10,
        max_wall_clock_seconds=300,
        max_total_tokens=100_000,
        max_cost_micro_usd=500_000,
    )


def _prompt_registry(tmp_path: Path) -> PromptRegistry:
    agent_dir = tmp_path / "demo-agent"
    agent_dir.mkdir()
    (agent_dir / "system.v1.md").write_text(
        "---\nid: demo-agent/system\nversion: 1\n---\n\nbody\n", encoding="utf-8"
    )
    return PromptRegistry.load(tmp_path)


def _registered_server(**capabilities: ToolCapability) -> BoundedContextServer:
    return BoundedContextServer(
        context_id="fixture",
        name="fixture",
        tools=tuple(capabilities),
        capabilities=capabilities,
        handle=lambda tool_name, arguments: None,
    )


# --- BoundedContextServer: a tool with no declared capability raises -------


def test_a_server_registering_a_tool_with_no_declared_capability_raises() -> None:
    with pytest.raises(ValueError):
        BoundedContextServer(
            context_id="fixture",
            name="fixture",
            tools=("fixture.read_only_thing", "fixture.undeclared_thing"),
            capabilities={"fixture.read_only_thing": ToolCapability.READ},
            handle=lambda tool_name, arguments: None,
        )


def test_a_server_declaring_a_capability_for_an_unexposed_tool_raises() -> None:
    with pytest.raises(ValueError):
        BoundedContextServer(
            context_id="fixture",
            name="fixture",
            tools=("fixture.read_only_thing",),
            capabilities={
                "fixture.read_only_thing": ToolCapability.READ,
                "fixture.not_a_real_tool": ToolCapability.READ,
            },
            handle=lambda tool_name, arguments: None,
        )


def test_mcp_registry_carries_the_capability_through_lookup() -> None:
    registry = McpRegistry()
    registry.register(
        _registered_server(
            **{
                "fixture.read_thing": ToolCapability.READ,
                "fixture.propose_thing": ToolCapability.PROPOSE,
            }
        )
    )

    assert registry.capability_of("fixture.read_thing") is ToolCapability.READ
    assert registry.capability_of("fixture.propose_thing") is ToolCapability.PROPOSE
    assert registry.lookup("fixture.read_thing").capability is ToolCapability.READ


# --- AgentSpec.build(): construction-time toolset/role checks --------------


def test_agent_spec_naming_a_mutating_tool_raises_at_construction(tmp_path: Path) -> None:
    prompt_registry = _prompt_registry(tmp_path)
    mcp_registry = McpRegistry()
    # Simulated "mutating" tool: a capability value outside the enum --
    # ToolCapability only ever has READ and PROPOSE, so the only way a
    # tool ends up with anything else is a bypass like this one, which
    # AgentSpec.build() must still catch explicitly rather than trusting
    # the type system alone.
    mcp_registry.register(
        BoundedContextServer(
            context_id="fixture",
            name="fixture",
            tools=("fixture.mutate_thing",),
            capabilities={"fixture.mutate_thing": "MUTATE"},  # type: ignore[dict-item]
            handle=lambda tool_name, arguments: None,
        )
    )

    with pytest.raises(ValidationError):
        AgentSpec.build(
            agent_id="demo-agent",
            version=1,
            toolset=("fixture.mutate_thing",),
            required_role=Role.ENGINEER,
            prompt_references=(("demo-agent/system", 1),),
            budget=_budget(),
            output_schema=_OUTPUT_SCHEMA,
            prompt_registry=prompt_registry,
            mcp_registry=mcp_registry,
            tool_roles={"fixture.mutate_thing": Role.ENGINEER},
        )


def test_agent_spec_naming_an_unregistered_tool_raises(tmp_path: Path) -> None:
    prompt_registry = _prompt_registry(tmp_path)
    mcp_registry = McpRegistry()  # nothing registered

    with pytest.raises(ToolNotRegisteredError):
        AgentSpec.build(
            agent_id="demo-agent",
            version=1,
            toolset=("fixture.never_registered",),
            required_role=Role.ENGINEER,
            prompt_references=(("demo-agent/system", 1),),
            budget=_budget(),
            output_schema=_OUTPUT_SCHEMA,
            prompt_registry=prompt_registry,
            mcp_registry=mcp_registry,
            tool_roles={"fixture.never_registered": Role.ENGINEER},
        )


def test_agent_spec_accepts_a_read_and_a_propose_tool(tmp_path: Path) -> None:
    prompt_registry = _prompt_registry(tmp_path)
    mcp_registry = McpRegistry()
    mcp_registry.register(
        _registered_server(
            **{
                "fixture.read_thing": ToolCapability.READ,
                "fixture.propose_thing": ToolCapability.PROPOSE,
            }
        )
    )

    spec = AgentSpec.build(
        agent_id="demo-agent",
        version=1,
        toolset=("fixture.read_thing", "fixture.propose_thing"),
        required_role=Role.ENGINEER,
        prompt_references=(("demo-agent/system", 1),),
        budget=_budget(),
        output_schema=_OUTPUT_SCHEMA,
        prompt_registry=prompt_registry,
        mcp_registry=mcp_registry,
        tool_roles={"fixture.read_thing": Role.VIEWER, "fixture.propose_thing": Role.ENGINEER},
    )
    assert spec.toolset == ("fixture.read_thing", "fixture.propose_thing")


# --- AgentSpec.build(): required_role must dominate the toolset's roles ----


def test_a_required_role_that_does_not_dominate_its_toolsets_role_raises(tmp_path: Path) -> None:
    prompt_registry = _prompt_registry(tmp_path)
    mcp_registry = McpRegistry()
    mcp_registry.register(_registered_server(**{"fixture.admin_thing": ToolCapability.READ}))

    with pytest.raises(ValidationError):
        AgentSpec.build(
            agent_id="demo-agent",
            version=1,
            toolset=("fixture.admin_thing",),
            required_role=Role.VIEWER,  # weaker than the tool's own TENANT_ADMIN requirement
            prompt_references=(("demo-agent/system", 1),),
            budget=_budget(),
            output_schema=_OUTPUT_SCHEMA,
            prompt_registry=prompt_registry,
            mcp_registry=mcp_registry,
            tool_roles={"fixture.admin_thing": Role.TENANT_ADMIN},
        )


def test_a_required_role_that_exactly_matches_the_toolsets_role_is_accepted(tmp_path: Path) -> None:
    prompt_registry = _prompt_registry(tmp_path)
    mcp_registry = McpRegistry()
    mcp_registry.register(_registered_server(**{"fixture.engineer_thing": ToolCapability.READ}))

    spec = AgentSpec.build(
        agent_id="demo-agent",
        version=1,
        toolset=("fixture.engineer_thing",),
        required_role=Role.ENGINEER,
        prompt_references=(("demo-agent/system", 1),),
        budget=_budget(),
        output_schema=_OUTPUT_SCHEMA,
        prompt_registry=prompt_registry,
        mcp_registry=mcp_registry,
        tool_roles={"fixture.engineer_thing": Role.ENGINEER},
    )
    assert spec.required_role is Role.ENGINEER


def test_a_required_role_stronger_than_the_toolsets_role_is_accepted(tmp_path: Path) -> None:
    prompt_registry = _prompt_registry(tmp_path)
    mcp_registry = McpRegistry()
    mcp_registry.register(_registered_server(**{"fixture.viewer_thing": ToolCapability.READ}))

    spec = AgentSpec.build(
        agent_id="demo-agent",
        version=1,
        toolset=("fixture.viewer_thing",),
        required_role=Role.TENANT_ADMIN,  # stronger than the tool's own VIEWER requirement
        prompt_references=(("demo-agent/system", 1),),
        budget=_budget(),
        output_schema=_OUTPUT_SCHEMA,
        prompt_registry=prompt_registry,
        mcp_registry=mcp_registry,
        tool_roles={"fixture.viewer_thing": Role.VIEWER},
    )
    assert spec.required_role is Role.TENANT_ADMIN


def test_a_tool_with_no_declared_required_role_raises(tmp_path: Path) -> None:
    prompt_registry = _prompt_registry(tmp_path)
    mcp_registry = McpRegistry()
    mcp_registry.register(_registered_server(**{"fixture.unroled_thing": ToolCapability.READ}))

    with pytest.raises(MissingDependencyError):
        AgentSpec.build(
            agent_id="demo-agent",
            version=1,
            toolset=("fixture.unroled_thing",),
            required_role=Role.ENGINEER,
            prompt_references=(("demo-agent/system", 1),),
            budget=_budget(),
            output_schema=_OUTPUT_SCHEMA,
            prompt_registry=prompt_registry,
            mcp_registry=mcp_registry,
            tool_roles={},
        )
