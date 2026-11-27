"""R5-04b: conformance tests proving every registered ``BoundedContextServer``
is reachable through both 818's MCP gateway path and this unit's A2A bridge
path, with identical results -- and that an unregistered tool/agent is
unreachable through *either* path, with the same failure semantics.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cairn_adapters.auth_oidc import JwtAuthenticator, OidcSettings
from cairn_kernel.errors import CairnError
from cairn_kernel.security import Role
from cairn_kits.mcp import BoundedContextServer, McpRegistry, ToolCapability, ToolNotRegisteredError
from cairn_mcp_gateway import (
    TOOL_ASSESSMENT_COVERAGE_REPORT,
    TOOL_ASSESSMENT_GET_DECISION,
    TOOL_ASSESSMENT_GET_RESULTS,
    TOOL_ASSESSMENT_GET_RUN,
    TOOL_GENERATE_ROADMAP,
    TOOL_GENERATE_TARGET_MODEL,
    TOOL_GET_BASELINE,
    TOOL_GET_CONTROL,
    TOOL_GET_COVERAGE,
    TOOL_GET_DEPENDENCIES,
    TOOL_GET_DIFF,
    TOOL_GET_MANIFEST,
    TOOL_GET_PATTERN,
    TOOL_GET_PROJECT,
    TOOL_GET_RELEASE,
    TOOL_GET_RUN,
    TOOL_GET_TARGET_MODEL,
    TOOL_GET_TCO,
    TOOL_GET_WORKLOAD,
    TOOL_LIST_PATTERNS,
    TOOL_LIST_PRICE_RELEASES,
    TOOL_LIST_PROJECT_MEMBERS,
    TOOL_LIST_RELEASES,
    TOOL_LIST_RESOURCES,
    TOOL_LIST_RUNS,
    TOOL_LIST_SOURCE_FILES,
    TOOL_LIST_WORKLOADS,
    TOOL_RESOLVE,
    TOOL_RUN,
    TOOL_TRANSFORMATION_GET_RUN,
    TOOL_VALIDATE,
    A2ABridge,
    McpGateway,
    build_default_registry,
)
from cairn_mcp_gateway.registry_factory import REQUIRED_ROLES

#: One (roles, arguments) fixture per registered tool, keyed by name --
#: R6-08's own fix to this test's original single-token/single-arguments
#: shape, which only ever worked because exactly one tool
#: (``posture.get_control``) was registered when it was written. Every
#: tool gets a role that can call it and a valid argument shape;
#: ``build_default_registry()``'s ``estate`` server is backed by a
#: fresh, empty ``AssessmentService`` (a composition root wires its own
#: real one), so its tools are fixtured against a run id that does not
#: exist -- the "identical result" this test proves for those is an
#: identical ``NotFoundError``, not a successful payload, which is
#: still a real conformance proof: both paths fail the same way.
#: Adding a tool without adding an entry here is a missing-fixture
#: failure below, not a silently-skipped tool.
_TOOL_FIXTURES: dict[str, tuple[tuple[str, ...], dict[str, object]]] = {
    TOOL_GET_CONTROL: (
        (Role.AUDITOR.value,),
        {"version": "2026.11.1", "control_id": "gcp-cis-5.1"},
    ),
    TOOL_LIST_WORKLOADS: ((Role.VIEWER.value,), {"assessment_run_id": "no-such-run"}),
    TOOL_GET_WORKLOAD: (
        (Role.VIEWER.value,),
        {"assessment_run_id": "no-such-run", "workload_id": "w-1"},
    ),
    TOOL_LIST_RESOURCES: ((Role.VIEWER.value,), {"assessment_run_id": "no-such-run"}),
    TOOL_GET_DEPENDENCIES: (
        (Role.VIEWER.value,),
        {"assessment_run_id": "no-such-run", "workload_id": "w-1"},
    ),
    TOOL_RESOLVE: (
        (Role.VIEWER.value,),
        {
            "mapping_version": "2026.11.2",
            "source_provider": "aws",
            "source_service": "s3",
            "target_provider": "gcp",
        },
    ),
    TOOL_GET_RELEASE: ((Role.VIEWER.value,), {"version": "2026.11.2"}),
    TOOL_LIST_RELEASES: ((Role.VIEWER.value,), {}),
    TOOL_GET_RUN: ((Role.VIEWER.value,), {"tenant_id": "t1", "run_id": "no-such-run"}),
    TOOL_LIST_RUNS: ((Role.VIEWER.value,), {"tenant_id": "t1", "project_id": "p1"}),
    TOOL_GET_COVERAGE: ((Role.VIEWER.value,), {"tenant_id": "t1", "run_id": "no-such-run"}),
    TOOL_ASSESSMENT_GET_RUN: (
        (Role.VIEWER.value,),
        {"tenant_id": "t1", "assessment_run_id": "no-such-run"},
    ),
    TOOL_ASSESSMENT_GET_RESULTS: (
        (Role.VIEWER.value,),
        {"tenant_id": "t1", "assessment_run_id": "no-such-run"},
    ),
    TOOL_ASSESSMENT_COVERAGE_REPORT: (
        (Role.VIEWER.value,),
        {"tenant_id": "t1", "assessment_run_id": "no-such-run"},
    ),
    TOOL_ASSESSMENT_GET_DECISION: (
        (Role.VIEWER.value,),
        {"tenant_id": "t1", "assessment_run_id": "no-such-run", "decision_id": "d-1"},
    ),
    TOOL_GET_BASELINE: (
        (Role.VIEWER.value,),
        {"tenant_id": "t1", "assessment_run_id": "no-such-run"},
    ),
    TOOL_GET_TCO: ((Role.VIEWER.value,), {"tenant_id": "t1", "assessment_run_id": "no-such-run"}),
    TOOL_LIST_PRICE_RELEASES: ((Role.VIEWER.value,), {}),
    TOOL_GET_PROJECT: ((Role.VIEWER.value,), {"tenant_id": "t1", "project_id": "no-such-project"}),
    TOOL_LIST_PROJECT_MEMBERS: (
        (Role.TENANT_ADMIN.value,),
        {"tenant_id": "t1", "project_id": "no-such-project"},
    ),
    TOOL_LIST_PATTERNS: ((Role.VIEWER.value,), {}),
    TOOL_GET_PATTERN: ((Role.VIEWER.value,), {"pattern_id": "web-app"}),
    TOOL_GET_TARGET_MODEL: ((Role.VIEWER.value,), {"design_id": "no-such-design"}),
    TOOL_GENERATE_TARGET_MODEL: (
        (Role.ARCHITECT.value,),
        {
            "tenant_id": "t1",
            "project_id": "p1",
            "design_id": "design-1",
            "pattern_id": "web-app",
            "mapping_version": "2026.11.2",
            "target_provider": "gcp",
            "resources": [],
            "parameters": {
                "compute_platform": "cloud_run",
                "database_engine": "cloud_sql_postgres",
            },
        },
    ),
    TOOL_GENERATE_ROADMAP: (
        (Role.ARCHITECT.value,),
        {
            "tenant_id": "t1",
            "project_id": "p1",
            "plan_id": "plan-1",
            "design_id": "no-such-design",
            "workloads": [],
        },
    ),
    TOOL_LIST_SOURCE_FILES: ((Role.VIEWER.value,), {"tenant_id": "t1", "project_id": "p1"}),
    TOOL_TRANSFORMATION_GET_RUN: (
        (Role.VIEWER.value,),
        {"tenant_id": "t1", "project_id": "p1", "run_id": "no-such-run"},
    ),
    TOOL_GET_MANIFEST: (
        (Role.VIEWER.value,),
        {"tenant_id": "t1", "project_id": "p1", "run_id": "no-such-run"},
    ),
    TOOL_GET_DIFF: (
        (Role.VIEWER.value,),
        {"tenant_id": "t1", "project_id": "p1", "run_id": "no-such-run"},
    ),
    TOOL_RUN: ((Role.ENGINEER.value,), {"tenant_id": "t1", "project_id": "p1", "created_by": "u1"}),
    TOOL_VALIDATE: (
        (Role.ENGINEER.value,),
        {"tenant_id": "t1", "project_id": "p1", "run_id": "no-such-run"},
    ),
}

ISSUER = "https://auth.example.cairn/"
AUDIENCE = "cairn-mcp-gateway"
SECRET = "unit-test-secret-does-not-leave-this-process"
TENANT_ID = str(uuid.uuid4())


def _settings() -> OidcSettings:
    return OidcSettings(
        issuer=ISSUER,
        audience=AUDIENCE,
        algorithms=("HS256",),
        secret=SECRET,
    )


def _token(*, roles: tuple[str, ...] = (), subject: str = "user-1") -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "tenant_id": TENANT_ID,
        "roles": list(roles),
    }
    return jwt.encode(claims, SECRET, algorithm="HS256")


@pytest.fixture
def default_gateway_and_bridge() -> tuple[McpGateway, A2ABridge]:
    """818's real registration (``posture.get_control``) wired through
    both paths, sharing the same registry/authenticator -- exactly as
    they would be in the deployed gateway."""
    registry = build_default_registry()
    authenticator = JwtAuthenticator(_settings())
    gateway = McpGateway(
        authenticator=authenticator, registry=registry, required_roles=REQUIRED_ROLES
    )
    bridge = A2ABridge(gateway=gateway)
    return gateway, bridge


def test_every_registered_server_is_reachable_through_both_paths_identically(
    default_gateway_and_bridge: tuple[McpGateway, A2ABridge],
) -> None:
    """The conformance proof: for every bounded-context server currently
    registered, calling its tool through the MCP gateway and through the
    A2A bridge (agent card -> translated task) produces an identical
    result -- generalised over whatever is registered, via
    ``_TOOL_FIXTURES`` rather than one hardcoded (role, arguments) pair.
    A registered tool with no fixture entry fails this test loudly
    (``KeyError``), rather than being silently skipped.

    ``TOOL_RUN`` (``transformation.run``) is excluded from the strict
    success-value comparison: it is a ``PROPOSE`` tool whose own job is
    to append a new, non-deterministic row (a fresh ``run_id`` and
    ``created_at`` each call, by design -- R6-15's eventual real
    repository would do the same) -- calling it twice, once per path,
    can never produce two equal rows. Both calls succeeding with the
    same *type* of result is still checked.
    """
    gateway, bridge = default_gateway_and_bridge

    checked_any = False
    for card in bridge.agent_cards():
        for tool_name in card.skills:
            roles, arguments = _TOOL_FIXTURES[tool_name]
            token = _token(roles=roles)

            mcp_error: CairnError | None = None
            try:
                mcp_result = gateway.call_tool(tool_name, token, arguments)
            except CairnError as exc:
                mcp_error = exc
                mcp_result = None

            a2a_error: CairnError | None = None
            try:
                a2a_result = bridge.send_task(
                    agent_id=card.agent_id, skill=tool_name, token=token, input=arguments
                )
                a2a_output = a2a_result.output
            except CairnError as exc:
                a2a_error = exc
                a2a_output = None

            if mcp_error is None and a2a_error is None:
                if tool_name == TOOL_RUN:
                    assert type(a2a_output) is type(mcp_result)
                else:
                    assert a2a_output == mcp_result
            else:
                assert type(mcp_error) is type(a2a_error)
                assert str(mcp_error) == str(a2a_error)
            checked_any = True

    assert checked_any, "expected at least one registered server to exercise"


def test_posture_get_control_matches_exactly_between_mcp_and_a2a_paths(
    default_gateway_and_bridge: tuple[McpGateway, A2ABridge],
) -> None:
    """Belt-and-suspenders: the specific proof registration named in the
    brief, asserted explicitly rather than only via the generalised loop
    above."""
    gateway, bridge = default_gateway_and_bridge
    token = _token(roles=(Role.AUDITOR.value,))
    arguments = {"version": "2026.11.1", "control_id": "gcp-cis-5.1"}

    mcp_control = gateway.call_tool(TOOL_GET_CONTROL, token, arguments)
    a2a_result = bridge.send_task(
        agent_id="posture", skill=TOOL_GET_CONTROL, token=token, input=arguments
    )

    assert a2a_result.output == mcp_control
    assert a2a_result.output.title.startswith("Ensure that Cloud Storage buckets")


def test_a2a_bridge_still_enforces_the_gateways_scope_check(
    default_gateway_and_bridge: tuple[McpGateway, A2ABridge],
) -> None:
    """The A2A path must not become a side door around 818's
    authorization: a wrongly-scoped token is rejected on the A2A path
    exactly as it is on the MCP path (same ``ForbiddenError``, raised by
    the shared ``McpGateway.call_tool`` underneath both)."""
    from cairn_kernel.errors import ForbiddenError

    _gateway, bridge = default_gateway_and_bridge
    token = _token(roles=(Role.VIEWER.value,))

    with pytest.raises(ForbiddenError):
        bridge.send_task(
            agent_id="posture",
            skill=TOOL_GET_CONTROL,
            token=token,
            input={"version": "2026.11.1", "control_id": "gcp-cis-5.1"},
        )


def test_unregistered_tool_is_unreachable_through_the_mcp_path(
    default_gateway_and_bridge: tuple[McpGateway, A2ABridge],
) -> None:
    gateway, _bridge = default_gateway_and_bridge
    token = _token(roles=(Role.AUDITOR.value,))

    with pytest.raises(ToolNotRegisteredError):
        gateway.call_tool("does.not.exist", token)


def test_unregistered_tool_is_unreachable_through_the_a2a_path_same_error(
    default_gateway_and_bridge: tuple[McpGateway, A2ABridge],
) -> None:
    """Deliberate-break test: an unregistered tool/agent must fail on the
    A2A path too, with the *same* ``ToolNotRegisteredError`` the MCP
    gateway raises -- not a silent default, not a different error type
    that would let a caller branch on protocol instead of on "is this
    actually registered"."""
    _gateway, bridge = default_gateway_and_bridge
    token = _token(roles=(Role.AUDITOR.value,))

    with pytest.raises(ToolNotRegisteredError):
        bridge.send_task(agent_id="does-not-exist", skill="does.not.exist", token=token, input={})


def test_unregistered_agent_with_a_real_skill_name_is_still_unreachable_via_a2a(
    default_gateway_and_bridge: tuple[McpGateway, A2ABridge],
) -> None:
    """A caller cannot sidestep agent-card identity by naming a real
    skill but claiming the wrong agent -- the bridge must check both,
    not just whether *some* agent happens to expose the skill."""
    _gateway, bridge = default_gateway_and_bridge
    token = _token(roles=(Role.AUDITOR.value,))

    with pytest.raises(ToolNotRegisteredError):
        bridge.send_task(
            agent_id="not-the-posture-context",
            skill=TOOL_GET_CONTROL,
            token=token,
            input={"version": "2026.11.1", "control_id": "gcp-cis-5.1"},
        )


def test_unregistered_server_is_unreachable_through_either_path_fresh_registry() -> None:
    """Belt-and-suspenders at the registry level, independent of the
    default registration: build a registry with exactly one server, then
    prove a *different*, never-registered tool/agent is rejected with
    the same error through both the MCP gateway and the A2A bridge built
    on top of it."""
    registry = McpRegistry()

    def handle(tool_name: str, arguments: dict) -> object:
        return {"tool": tool_name, "arguments": arguments}

    registry.register(
        BoundedContextServer(
            context_id="fixture",
            name="fixture",
            tools=("fixture.read_only_thing",),
            capabilities={"fixture.read_only_thing": ToolCapability.READ},
            handle=handle,
        )
    )
    authenticator = JwtAuthenticator(_settings())
    gateway = McpGateway(
        authenticator=authenticator,
        registry=registry,
        required_roles={"fixture.read_only_thing": Role.AUDITOR},
    )
    bridge = A2ABridge(gateway=gateway)
    token = _token(roles=(Role.AUDITOR.value,))

    with pytest.raises(ToolNotRegisteredError):
        gateway.call_tool("fixture.never_registered", token)

    with pytest.raises(ToolNotRegisteredError):
        bridge.send_task(
            agent_id="fixture", skill="fixture.never_registered", token=token, input={}
        )

    with pytest.raises(ToolNotRegisteredError):
        bridge.send_task(
            agent_id="never-registered-agent",
            skill="fixture.read_only_thing",
            token=token,
            input={},
        )
