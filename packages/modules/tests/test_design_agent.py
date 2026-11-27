"""R6-13 acceptance: the design agent (design §3.2).

Against ``DeterministicAgentLoop`` throughout -- no provider, no
network, no ADK. The real pattern catalogue (``patterns/*.yaml``) and
the real mapping seed (``mappings/service-map.yaml``) are loaded, not
faked, because rules 1, 2 and 6 are all about agreeing with what
actually ships.

The fixture estate has three workloads and two dependency edges:
``w-app`` depends on ``w-db``, and ``w-report`` depends on ``w-app``. So
``generate_roadmap``'s own topological order is wave 1 ``w-db``, wave 2
``w-app``, wave 3 ``w-report``, and every ordering test below is stated
against that.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from cairn_contracts.estate import (
    DecisionStatus,
    Dependency,
    DependencyDirection,
    DependencyKind,
    Disposition,
    DispositionDecision,
    FactStatus,
    FactValue,
    Workload,
)
from cairn_contracts.mapping import ReleaseStatus
from cairn_contracts.mapping.pattern import PatternReleaseStatus
from cairn_kernel.errors import ForbiddenError, SeparationOfDutiesError, TenantScopeViolationError
from cairn_kernel.hex import ProjectId, TenantId
from cairn_kernel.hex.primitives import MutationClass
from cairn_kernel.security import Principal, Role
from cairn_kernel.tenancy import TenantContext, tenant_scope
from cairn_kernel.testing.fakes import FixedClock, FixedIdGenerator
from cairn_kits.loop import (
    AgentRunState,
    AgentStep,
    DeterministicAgentLoop,
    InMemoryStepRecorder,
    PromptRegistry,
    RunBudget,
    StepKind,
)
from cairn_kits.mcp import BoundedContextServer, McpRegistry, ToolCapability
from cairn_modules.agents.design_proposer import (
    AGENT_ID,
    DEFAULT_BUDGET,
    PROPOSAL_SCHEMA,
    REQUIRED_ROLE,
    TOOLSET,
    DesignContractError,
    DesignInputs,
    DesignProposal,
    DesignProposerService,
    build_spec,
    check_agent_cannot_approve,
    validate_proposal,
)
from cairn_modules.approvals.model import ApprovalRecord, ApprovalState
from cairn_modules.design.patterns import load_pattern_catalogue
from cairn_modules.mappings import load_mapping_release
from cairn_modules.planning.roadmap import PLAN_SUBJECT_KIND, FakePlanRevisionRepository

REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPTS_DIR = REPO_ROOT / "prompts"
PATTERNS_DIR = REPO_ROOT / "patterns"
MAPPING_SEED = REPO_ROOT / "mappings" / "service-map.yaml"

TENANT = "tenant-1"
PROJECT = "project-1"
PLAN = "plan-1"
DESIGN = "design-1"
ESTATE_MODEL_VERSION = "estate-v1"
NOW = datetime(2026, 11, 27, tzinfo=UTC)

CATALOGUE_VERSION = "2026.11.1"
PATTERN_ID = "migration"
PATTERN_PARAMETERS: dict[str, object] = {
    "strategy": "rehost",
    "source_ingestion_format": "rvtools",
    "wave_number": 1,
}


# --- fixtures ---------------------------------------------------------------


def _catalogue():
    return load_pattern_catalogue(
        PATTERNS_DIR,
        version=CATALOGUE_VERSION,
        released_at=datetime(2026, 11, 15, tzinfo=UTC),
        status=PatternReleaseStatus.PUBLISHED,
    )


def _mapping_release():
    return load_mapping_release(MAPPING_SEED).model_copy(update={"status": ReleaseStatus.PUBLISHED})


def _workload(workload_id: str, *, model_version: str = ESTATE_MODEL_VERSION) -> Workload:
    return Workload(
        workload_id=workload_id,
        tenant_id=TENANT,
        project_id=PROJECT,
        name=workload_id,
        environment="prod",
        owner="team-a",
        business_context=None,
        resource_ids=(),
        dependency_ids=(),
        facts={
            "vcpu": FactValue(
                value=4,
                status=FactStatus.OBSERVED,
                source="fixture",
                observed_at=NOW,
                ingested_at=NOW,
                confidence=None,
                mapping_version=None,
                provenance_ref="prov-1",
            )
        },
        disposition=Disposition.REHOST,
        disposition_confidence=0.7,
        model_version=model_version,
        mapping_version="2026.11.2",
    )


def _dependency(dependency_id: str, *, source: str, target: str) -> Dependency:
    return Dependency(
        dependency_id=dependency_id,
        tenant_id=TENANT,
        project_id=PROJECT,
        source_workload_id=source,
        target_workload_id=target,
        kind=DependencyKind.DATA,
        direction=DependencyDirection.ONE_WAY,
        status=FactStatus.OBSERVED,
        provenance=(),
    )


def _decision(
    workload_id: str, *, status: DecisionStatus = DecisionStatus.ACCEPTED
) -> DispositionDecision:
    return DispositionDecision(
        decision_id=f"{PROJECT}:{workload_id}",
        tenant_id=TENANT,
        project_id=PROJECT,
        workload_id=workload_id,
        disposition=Disposition.REHOST,
        rationale="fixture",
        confidence=0.7,
        status=status,
        decided_by="reviewer-1" if status is not DecisionStatus.PROPOSED else None,
        decided_at=NOW if status is not DecisionStatus.PROPOSED else None,
        model_version=ESTATE_MODEL_VERSION,
        mapping_version="2026.11.2",
    )


def _inputs(
    *,
    workloads: tuple[Workload, ...] | None = None,
    dispositions: dict[str, DispositionDecision] | None = None,
    tenant_id: str = TENANT,
) -> DesignInputs:
    """``w-app`` depends on ``w-db``; ``w-report`` depends on ``w-app``.
    The generator's topological order is therefore db, app, report."""

    return DesignInputs(
        tenant_id=tenant_id,
        project_id=PROJECT,
        plan_id=PLAN,
        design_id=DESIGN,
        catalogue=_catalogue(),
        mapping_release=_mapping_release(),
        workloads=(
            workloads
            if workloads is not None
            else (_workload("w-db"), _workload("w-app"), _workload("w-report"))
        ),
        dependencies=(
            _dependency("dep-1", source="w-app", target="w-db"),
            _dependency("dep-2", source="w-report", target="w-app"),
        ),
        resources=(),
        dispositions=(
            dispositions
            if dispositions is not None
            else {
                "w-db": _decision("w-db"),
                "w-app": _decision("w-app"),
                "w-report": _decision("w-report"),
            }
        ),
    )


def _proposal(**overrides: object) -> dict[str, object]:
    """A proposal that satisfies all six rules against the default
    fixture. Every failing case is this, with one thing wrong."""

    payload: dict[str, object] = {
        "plan_id": PLAN,
        "pattern_id": PATTERN_ID,
        "pattern_catalogue_version": CATALOGUE_VERSION,
        "mapping_release_version": "2026.11.2",
        "estate_model_version": ESTATE_MODEL_VERSION,
        "target_provider": "gcp",
        "parameters": dict(PATTERN_PARAMETERS),
        "pattern_rationale": "a 6R migration wave fits an estate with no refactor work",
        "rejected_patterns": [
            {"pattern_id": "web-app", "reason": "no application rewrite is in scope"}
        ],
        "waves": [
            {
                "wave_number": 1,
                "workload_ids": ["w-db"],
                "rationale": "the database has no upstream dependency of its own",
                "constraints_cited": ["dependency:dep-1"],
            },
            {
                "wave_number": 2,
                "workload_ids": ["w-app"],
                "rationale": "the application reads the database migrated in wave 1",
                "constraints_cited": ["dependency:dep-1"],
            },
            {
                "wave_number": 3,
                "workload_ids": ["w-report"],
                "rationale": "reporting reads the application migrated in wave 2",
                "constraints_cited": ["dependency:dep-2"],
            },
        ],
        "risks": [
            {
                "statement": "the reporting workload's cutover window is the narrowest",
                "fact_refs": ["workload:w-report"],
            }
        ],
    }
    payload.update(overrides)
    return payload


def _prompt_registry() -> PromptRegistry:
    return PromptRegistry.load(PROMPTS_DIR)


def _mcp_registry(*, propose_capability: ToolCapability = ToolCapability.PROPOSE) -> McpRegistry:
    """This agent's eight tools: six ``READ``, two ``PROPOSE``.
    ``cairn_modules`` cannot import ``cairn_mcp_gateway``
    (``domain-purity``), so the capabilities and roles the real servers
    declare are reproduced here."""

    registry = McpRegistry()
    capabilities: dict[str, ToolCapability] = dict.fromkeys(TOOLSET, ToolCapability.READ)
    capabilities["design.generate_target_model"] = propose_capability
    capabilities["planning.generate_roadmap"] = propose_capability
    registry.register(
        BoundedContextServer(
            context_id="agent-toolset",
            name="agent-toolset",
            tools=TOOLSET,
            capabilities=capabilities,
            handle=lambda tool_name, arguments, principal: None,
        )
    )
    return registry


def _tool_roles() -> dict[str, Role]:
    roles = dict.fromkeys(TOOLSET, Role.VIEWER)
    roles["design.generate_target_model"] = Role.ARCHITECT
    roles["planning.generate_roadmap"] = Role.ARCHITECT
    return roles


def _principal(
    *, roles: tuple[Role, ...] = (Role.ARCHITECT,), subject: str = "architect-1"
) -> Principal:
    return Principal(subject=subject, tenant_id=TenantId(TENANT), roles=roles)


def _steps() -> tuple[AgentStep, ...]:
    return (
        AgentStep(
            index=0,
            kind=StepKind.MODEL_CALL,
            detail={"prompt_id": "design-proposer/select-pattern", "prompt_version": 1},
        ),
        AgentStep(
            index=1,
            kind=StepKind.TOOL_CALL,
            detail={"tool_name": "design.generate_target_model"},
        ),
    )


def _service(
    *, proposal: dict[str, object] | None, budget: RunBudget = DEFAULT_BUDGET
) -> tuple[DesignProposerService, FakePlanRevisionRepository]:
    repo = FakePlanRevisionRepository(clock=FixedClock(NOW), id_generator=FixedIdGenerator())
    loop = DeterministicAgentLoop(_steps(), clock=FixedClock(NOW), scripted_proposal=proposal)
    service = DesignProposerService(
        agent_loop=loop,
        plan_revision_repository=repo,
        prompt_registry=_prompt_registry(),
        mcp_registry=_mcp_registry(),
        tool_roles=_tool_roles(),
        step_recorder=InMemoryStepRecorder(),
        id_generator=FixedIdGenerator(start=100),
        budget=budget,
    )
    return service, repo


def _propose(
    *,
    proposal: dict[str, object] | None,
    inputs: DesignInputs | None = None,
    budget: RunBudget = DEFAULT_BUDGET,
):
    service, repo = _service(proposal=proposal, budget=budget)
    result = service.propose(
        inputs=inputs if inputs is not None else _inputs(),
        principal=_principal(),
        correlation_id="corr-1",
    )
    return result, repo


def _validate(proposal: dict[str, object], inputs: DesignInputs | None = None) -> None:
    validate_proposal(
        DesignProposal.model_validate(proposal),
        inputs=inputs if inputs is not None else _inputs(),
    )


def _scope(actor: str = "architect-1") -> TenantContext:
    """Reading ``FakePlanRevisionRepository`` needs an ambient tenant
    context, same as writing it does (ADR-012) -- these tests bind one
    rather than reaching past the isolation the repository enforces."""

    return TenantContext(
        tenant_id=TenantId(TENANT),
        project_id=ProjectId(PROJECT),
        actor_id=actor,
        actor_roles=(Role.ARCHITECT.value,),
        correlation_id="corr-read",
    )


def _revisions(repo: FakePlanRevisionRepository) -> tuple[object, ...]:
    with tenant_scope(_scope()):
        return repo.list_revisions(tenant_id=TENANT, project_id=PROJECT, plan_id=PLAN)


def _latest(repo: FakePlanRevisionRepository) -> object | None:
    with tenant_scope(_scope()):
        return repo.latest_revision(tenant_id=TENANT, project_id=PROJECT, plan_id=PLAN)


# --- the spec ---------------------------------------------------------------


def test_the_spec_declares_six_read_tools_and_two_propose_tools() -> None:
    spec = build_spec(
        prompt_registry=_prompt_registry(),
        mcp_registry=_mcp_registry(),
        tool_roles=_tool_roles(),
    )

    assert spec.agent_id == AGENT_ID
    assert len(spec.toolset) == 8
    assert spec.output_schema is PROPOSAL_SCHEMA
    assert spec.required_role is REQUIRED_ROLE is Role.ARCHITECT


def test_the_spec_is_refused_if_a_propose_tool_is_registered_as_something_else() -> None:
    """R-AGENT-03 at construction: this agent cannot be built at all if
    one of its generators is ever registered as a mutating tool."""

    with pytest.raises(Exception, match="neither READ nor PROPOSE"):
        build_spec(
            prompt_registry=_prompt_registry(),
            mcp_registry=_mcp_registry(propose_capability="WRITE"),  # type: ignore[arg-type]
            tool_roles=_tool_roles(),
        )


def test_every_prompt_reference_resolves_against_the_shipped_prompts() -> None:
    build_spec(
        prompt_registry=_prompt_registry(),
        mcp_registry=_mcp_registry(),
        tool_roles=_tool_roles(),
    )


def test_the_toolset_contains_no_apply_publish_approve_or_execute_tool() -> None:
    forbidden = ("apply", "publish", "approve", "execute", "delete")
    assert not [tool for tool in TOOLSET if any(word in tool for word in forbidden)]


# --- the happy path ---------------------------------------------------------


def test_a_valid_proposal_becomes_a_candidate_plan_revision() -> None:
    result, repo = _propose(proposal=_proposal())

    assert result.accepted
    assert result.run.state is AgentRunState.COMPLETED
    revision = result.revision
    assert revision is not None
    assert revision.subject_kind == PLAN_SUBJECT_KIND
    assert revision.subject_id == PLAN
    assert revision.revision_number == 1
    assert revision.created_by == "architect-1"
    assert _latest(repo) == revision


def test_the_revision_records_the_generators_roadmap_not_the_agents_wave_list() -> None:
    """Design §3.2: "the generators do the generating". The row's
    ``content_hash`` is the generator's roadmap's, so a reviewer diffs a
    deterministic artefact, not model prose."""

    result, _ = _propose(proposal=_proposal())

    assert result.roadmap is not None
    assert result.revision is not None
    assert result.revision.content_hash == result.roadmap.content_hash


def test_a_second_run_appends_a_revision_and_never_mutates_the_first() -> None:
    """ADR-009: a revision is immutable once created."""

    service, repo = _service(proposal=_proposal())
    first = service.propose(
        inputs=_inputs(), principal=_principal(), correlation_id="corr-1"
    ).revision
    second = service.propose(
        inputs=_inputs(), principal=_principal(), correlation_id="corr-2"
    ).revision

    assert first is not None
    assert second is not None
    assert (first.revision_number, second.revision_number) == (1, 2)
    revisions = _revisions(repo)
    assert revisions[0] == first


def test_a_coarser_wave_grouping_than_the_generators_is_accepted() -> None:
    """Rule 4 is "does not contradict", not "is identical": merging the
    generator's waves 2 and 3 keeps every dependency satisfied, so the
    agent may propose it."""

    proposal = _proposal(
        waves=[
            {
                "wave_number": 1,
                "workload_ids": ["w-db"],
                "rationale": "no upstream dependency",
                "constraints_cited": ["dependency:dep-1"],
            },
            {
                "wave_number": 2,
                "workload_ids": ["w-app", "w-report"],
                "rationale": "both read the database migrated in wave 1",
                "constraints_cited": ["dependency:dep-1", "dependency:dep-2"],
            },
        ]
    )

    result, _ = _propose(proposal=proposal)

    assert result.accepted


# --- rule 1: the pattern catalogue ------------------------------------------


def test_rule_1_a_pattern_outside_the_declared_catalogue_version_is_rejected() -> None:
    result, repo = _propose(proposal=_proposal(pattern_id="invented-pattern"))

    assert not result.accepted
    assert "not in catalogue" in (result.rejection or "")
    assert _revisions(repo) == ()


def test_rule_1_a_proposal_declaring_another_catalogue_version_is_rejected() -> None:
    result, repo = _propose(proposal=_proposal(pattern_catalogue_version="2025.1.0"))

    assert not result.accepted
    assert "2025.1.0" in (result.rejection or "")
    assert _revisions(repo) == ()


def test_rule_1_rejected_patterns_may_only_name_patterns_in_the_catalogue() -> None:
    proposal = _proposal(rejected_patterns=[{"pattern_id": "no-such-pattern", "reason": "made up"}])

    result, repo = _propose(proposal=proposal)

    assert not result.accepted
    assert "cannot reject a pattern that does not exist" in (result.rejection or "")
    assert _revisions(repo) == ()


# --- rule 2: the generator's own parameter contract -------------------------


def test_rule_2_a_parameter_set_the_generator_rejects_rejects_the_proposal() -> None:
    """Design §3.2 rule 2, delegated: ``strategy`` is an enum with six
    allowed values and ``teleport`` is not one of them. The agent's
    proposal is rejected because the generator rejects it."""

    proposal = _proposal(parameters={**PATTERN_PARAMETERS, "strategy": "teleport"})

    result, repo = _propose(proposal=proposal)

    assert not result.accepted
    assert "generator rejected" in (result.rejection or "")
    assert _revisions(repo) == ()


def test_rule_2_a_missing_required_parameter_rejects_the_proposal() -> None:
    proposal = _proposal(parameters={"strategy": "rehost", "source_ingestion_format": "rvtools"})

    result, repo = _propose(proposal=proposal)

    assert not result.accepted
    assert "generator rejected" in (result.rejection or "")
    assert _revisions(repo) == ()


# --- rule 3: coverage -------------------------------------------------------


def test_rule_3_an_accepted_workload_in_no_wave_is_rejected() -> None:
    proposal = _proposal(
        waves=[
            {
                "wave_number": 1,
                "workload_ids": ["w-db"],
                "rationale": "no upstream dependency",
                "constraints_cited": ["dependency:dep-1"],
            },
            {
                "wave_number": 2,
                "workload_ids": ["w-app"],
                "rationale": "reads the database",
                "constraints_cited": ["dependency:dep-1"],
            },
        ]
    )

    result, repo = _propose(proposal=proposal)

    assert not result.accepted
    assert "w-report" in (result.rejection or "")
    assert "appear in no wave" in (result.rejection or "")
    assert _revisions(repo) == ()


def test_rule_3_a_workload_in_two_waves_is_rejected() -> None:
    proposal = _proposal(
        waves=[
            {
                "wave_number": 1,
                "workload_ids": ["w-db", "w-app"],
                "rationale": "no upstream dependency",
                "constraints_cited": ["dependency:dep-1"],
            },
            {
                "wave_number": 2,
                "workload_ids": ["w-app", "w-report"],
                "rationale": "reads the database",
                "constraints_cited": ["dependency:dep-2"],
            },
        ]
    )

    result, repo = _propose(proposal=proposal)

    assert not result.accepted
    assert "more than one wave" in (result.rejection or "")
    assert _revisions(repo) == ()


def test_rule_3_a_workload_whose_disposition_is_still_pending_may_not_be_scheduled() -> None:
    inputs = _inputs(
        dispositions={
            "w-db": _decision("w-db"),
            "w-app": _decision("w-app"),
            "w-report": _decision("w-report", status=DecisionStatus.PROPOSED),
        }
    )

    result, repo = _propose(proposal=_proposal(), inputs=inputs)

    assert not result.accepted
    assert "rejected or still pending" in (result.rejection or "")
    assert _revisions(repo) == ()


def test_rule_3_a_rejected_disposition_may_not_be_scheduled() -> None:
    inputs = _inputs(
        dispositions={
            "w-db": _decision("w-db"),
            "w-app": _decision("w-app"),
            "w-report": _decision("w-report", status=DecisionStatus.REJECTED),
        }
    )

    result, repo = _propose(proposal=_proposal(), inputs=inputs)

    assert not result.accepted
    assert "rejected or still pending" in (result.rejection or "")
    assert _revisions(repo) == ()


def test_rule_3_a_wave_naming_a_workload_outside_the_estate_is_rejected() -> None:
    proposal = _proposal()
    proposal["waves"][0]["workload_ids"] = ["w-db", "w-ghost"]  # type: ignore[index]

    result, repo = _propose(proposal=proposal)

    assert not result.accepted
    assert "w-ghost" in (result.rejection or "")
    assert _revisions(repo) == ()


# --- rule 4: wave ordering against generate_roadmap -------------------------


def test_rule_4_wave_numbers_contradicting_the_generators_order_are_rejected() -> None:
    """The run sheet's own bolded criterion. The generator's topological
    order is db, app, report; this proposal schedules the application
    before the database it reads."""

    proposal = _proposal(
        waves=[
            {
                "wave_number": 1,
                "workload_ids": ["w-app"],
                "rationale": "start with the application",
                "constraints_cited": ["dependency:dep-1"],
            },
            {
                "wave_number": 2,
                "workload_ids": ["w-db"],
                "rationale": "the database can follow",
                "constraints_cited": ["dependency:dep-1"],
            },
            {
                "wave_number": 3,
                "workload_ids": ["w-report"],
                "rationale": "reporting last",
                "constraints_cited": ["dependency:dep-2"],
            },
        ]
    )

    result, repo = _propose(proposal=proposal)

    assert not result.accepted
    rejection = result.rejection or ""
    assert "propose constraints, not violate dependencies" in rejection
    assert "w-db" in rejection
    assert _revisions(repo) == ()


def test_rule_4_a_transitive_inversion_is_rejected_too() -> None:
    """``w-report`` depends on ``w-app``, which depends on ``w-db``, so
    putting reporting first inverts an edge two hops away."""

    proposal = _proposal(
        waves=[
            {
                "wave_number": 1,
                "workload_ids": ["w-report"],
                "rationale": "reporting first",
                "constraints_cited": ["dependency:dep-2"],
            },
            {
                "wave_number": 2,
                "workload_ids": ["w-db", "w-app"],
                "rationale": "the rest after",
                "constraints_cited": ["dependency:dep-1"],
            },
        ]
    )

    result, repo = _propose(proposal=proposal)

    assert not result.accepted
    assert "propose constraints, not violate dependencies" in (result.rejection or "")
    assert _revisions(repo) == ()


# --- rule 5: wave rationales and risks cite something real ------------------


def test_rule_5_a_wave_citing_no_constraint_is_rejected() -> None:
    proposal = _proposal()
    proposal["waves"][1]["constraints_cited"] = []  # type: ignore[index]

    result, repo = _propose(proposal=proposal)

    assert not result.accepted
    assert "cites no constraint or dependency" in (result.rejection or "")
    assert _revisions(repo) == ()


def test_rule_5_a_wave_citing_a_dependency_that_does_not_exist_is_rejected() -> None:
    proposal = _proposal()
    proposal["waves"][1]["constraints_cited"] = ["dependency:dep-99"]  # type: ignore[index]

    result, repo = _propose(proposal=proposal)

    assert not result.accepted
    assert "dep-99" in (result.rejection or "")
    assert _revisions(repo) == ()


def test_rule_5_a_wave_citing_a_constraint_the_generator_never_raised_is_rejected() -> None:
    proposal = _proposal()
    proposal["waves"][1]["constraints_cited"] = [  # type: ignore[index]
        "constraint:w-app/UNRESOLVED_MAPPING"
    ]

    result, repo = _propose(proposal=proposal)

    assert not result.accepted
    assert "did not raise" in (result.rejection or "")
    assert _revisions(repo) == ()


def test_rule_5_a_citation_in_an_unknown_scheme_is_rejected() -> None:
    proposal = _proposal()
    proposal["waves"][1]["constraints_cited"] = ["gut-feel:w-app"]  # type: ignore[index]

    result, repo = _propose(proposal=proposal)

    assert not result.accepted
    assert "no known reference kind" in (result.rejection or "")
    assert _revisions(repo) == ()


def test_rule_5_an_empty_wave_rationale_is_rejected() -> None:
    proposal = _proposal()
    proposal["waves"][1]["rationale"] = "   "  # type: ignore[index]

    result, repo = _propose(proposal=proposal)

    assert not result.accepted
    assert "empty rationale" in (result.rejection or "")
    assert _revisions(repo) == ()


def test_rule_5_an_uncited_risk_is_rejected() -> None:
    proposal = _proposal(risks=[{"statement": "it might go wrong", "fact_refs": []}])

    result, repo = _propose(proposal=proposal)

    assert not result.accepted
    assert "uncited risk" in (result.rejection or "")
    assert _revisions(repo) == ()


def test_rule_5_a_risk_citing_an_unknown_workload_is_rejected() -> None:
    proposal = _proposal(
        risks=[{"statement": "something about w-ghost", "fact_refs": ["workload:w-ghost"]}]
    )

    result, repo = _propose(proposal=proposal)

    assert not result.accepted
    assert "w-ghost" in (result.rejection or "")
    assert _revisions(repo) == ()


def test_rule_5_a_real_generator_constraint_may_be_cited() -> None:
    """A workload with no recorded decision gets a
    ``PENDING_DISPOSITION`` constraint from the generator, and citing
    that exact constraint is legitimate -- the rule rejects invented
    citations, not real ones."""

    inputs = _inputs(dispositions={"w-db": _decision("w-db"), "w-app": _decision("w-app")})
    proposal = _proposal(
        waves=[
            {
                "wave_number": 1,
                "workload_ids": ["w-db"],
                "rationale": "no upstream dependency",
                "constraints_cited": ["constraint:w-report/PENDING_DISPOSITION"],
            },
            {
                "wave_number": 2,
                "workload_ids": ["w-app"],
                "rationale": "reads the database",
                "constraints_cited": ["dependency:dep-1"],
            },
        ]
    )

    result, _ = _propose(proposal=proposal, inputs=inputs)

    assert result.accepted


# --- rule 6: the three versions (R-VER-01) ----------------------------------


def test_rule_6_the_three_version_fields_are_carried_and_are_the_ones_used() -> None:
    result, _ = _propose(proposal=_proposal())

    assert result.proposal is not None
    assert result.target_model is not None
    assert result.proposal.pattern_catalogue_version == CATALOGUE_VERSION
    assert result.proposal.mapping_release_version == "2026.11.2"
    assert result.proposal.estate_model_version == ESTATE_MODEL_VERSION
    # and the generator recorded the same two it was actually given
    assert result.target_model.pattern_catalogue_version == CATALOGUE_VERSION
    assert result.target_model.mapping_release_version == "2026.11.2"


def test_rule_6_a_proposal_naming_another_mapping_release_is_rejected() -> None:
    result, repo = _propose(proposal=_proposal(mapping_release_version="2020.1.0"))

    assert not result.accepted
    assert "2020.1.0" in (result.rejection or "")
    assert _revisions(repo) == ()


def test_rule_6_a_proposal_naming_another_estate_model_version_is_rejected() -> None:
    result, repo = _propose(proposal=_proposal(estate_model_version="estate-v9"))

    assert not result.accepted
    assert "estate-v9" in (result.rejection or "")
    assert _revisions(repo) == ()


def test_rule_6_an_estate_that_disagrees_with_itself_can_be_claimed_by_nothing() -> None:
    workloads = (
        _workload("w-db"),
        _workload("w-app"),
        _workload("w-report", model_version="estate-v2"),
    )

    result, repo = _propose(proposal=_proposal(), inputs=_inputs(workloads=workloads))

    assert not result.accepted
    assert "do not agree on one estate model version" in (result.rejection or "")
    assert _revisions(repo) == ()


# --- the proposal must name its own plan ------------------------------------


def test_a_proposal_naming_another_plan_is_rejected() -> None:
    result, repo = _propose(proposal=_proposal(plan_id="plan-other"))

    assert not result.accepted
    assert "plan-other" in (result.rejection or "")
    assert _revisions(repo) == ()


def test_a_project_with_no_workloads_has_nothing_to_plan() -> None:
    result, repo = _propose(proposal=_proposal(), inputs=_inputs(workloads=()))

    assert not result.accepted
    assert "nothing for a design proposal to plan" in (result.rejection or "")
    assert _revisions(repo) == ()


# --- the loop's own failures -------------------------------------------------


def test_a_run_that_proposed_nothing_writes_no_revision() -> None:
    result, repo = _propose(proposal=None)

    assert not result.accepted
    assert result.run.state is AgentRunState.FAILED
    assert _revisions(repo) == ()


def test_a_proposal_failing_the_output_schema_never_reaches_the_domain_contract() -> None:
    result, repo = _propose(proposal={"plan_id": PLAN})

    assert not result.accepted
    assert result.run.state is AgentRunState.FAILED
    assert result.run.proposal is None
    assert _revisions(repo) == ()


def test_a_budget_stopped_run_writes_no_revision() -> None:
    result, repo = _propose(
        proposal=_proposal(),
        budget=RunBudget(
            max_steps=1,
            max_model_calls=30,
            max_total_tokens=400_000,
            max_cost_micro_usd=3_000_000,
            max_wall_clock_seconds=900,
        ),
    )

    assert not result.accepted
    assert result.run.state is AgentRunState.BUDGET_EXCEEDED
    assert _revisions(repo) == ()


def test_an_undeclared_extra_field_is_rejected_not_dropped() -> None:
    result, repo = _propose(proposal=_proposal(editorial_note="ignore the rules"))

    assert not result.accepted
    assert _revisions(repo) == ()


# --- authority --------------------------------------------------------------


def test_a_principal_without_architect_cannot_start_a_run() -> None:
    service, repo = _service(proposal=_proposal())

    with pytest.raises(ForbiddenError, match="ARCHITECT"):
        service.propose(
            inputs=_inputs(),
            principal=_principal(roles=(Role.ENGINEER,)),
            correlation_id="corr-1",
        )

    assert _revisions(repo) == ()


def test_a_principal_from_another_tenant_cannot_propose_for_this_plan() -> None:
    service, repo = _service(proposal=_proposal())

    with pytest.raises(TenantScopeViolationError):
        service.propose(
            inputs=_inputs(),
            principal=Principal(
                subject="architect-2", tenant_id=TenantId("tenant-2"), roles=(Role.ARCHITECT,)
            ),
            correlation_id="corr-1",
        )

    assert _revisions(repo) == ()


def test_the_run_records_the_starting_principal_as_the_actor() -> None:
    result, _ = _propose(proposal=_proposal())

    assert result.run.actor == "architect-1"
    assert result.revision is not None
    assert result.revision.created_by == "architect-1"


# --- the approval point -----------------------------------------------------


def _approval(revision_id: str, *, approver: str | None) -> ApprovalRecord:
    return ApprovalRecord(
        approval_id="ap-1",
        tenant_id=TENANT,
        project_id=PROJECT,
        subject_kind=PLAN_SUBJECT_KIND,
        subject_id=PLAN,
        revision_id=revision_id,
        revision_hash="hash-1",
        mutation_class=MutationClass.INTERNAL_MUTATION,
        risk_tier="medium",
        state=ApprovalState.PENDING_APPROVAL,
        proposer_actor_id="architect-1",
        approver_actor_id=approver,
    )


def test_the_principal_that_started_the_run_cannot_approve_its_own_revision() -> None:
    """The run sheet's own criterion: the candidate plan revision is an
    immutable row the agent's own principal cannot approve."""

    result, _ = _propose(proposal=_proposal())
    revision = result.revision
    assert revision is not None

    with pytest.raises(SeparationOfDutiesError):
        check_agent_cannot_approve(
            revision,
            _approval(revision.revision_id, approver="architect-1"),
            proposed_by="architect-1",
        )


def test_another_principal_may_approve_the_revision() -> None:
    result, _ = _propose(proposal=_proposal())
    revision = result.revision
    assert revision is not None

    check_agent_cannot_approve(
        revision,
        _approval(revision.revision_id, approver="architect-2"),
        proposed_by="architect-1",
    )


def test_an_approval_naming_another_revision_is_refused() -> None:
    result, _ = _propose(proposal=_proposal())
    revision = result.revision
    assert revision is not None

    with pytest.raises(ForbiddenError, match="not"):
        check_agent_cannot_approve(
            revision, _approval("rev-other", approver="architect-2"), proposed_by="architect-1"
        )


def test_an_approval_with_no_approver_is_refused() -> None:
    result, _ = _propose(proposal=_proposal())
    revision = result.revision
    assert revision is not None

    with pytest.raises(ForbiddenError, match="no approver"):
        check_agent_cannot_approve(
            revision, _approval(revision.revision_id, approver=None), proposed_by="architect-1"
        )


# --- validate_proposal, called directly -------------------------------------


def test_validate_proposal_raises_design_contract_error() -> None:
    _validate(_proposal())

    with pytest.raises(DesignContractError):
        _validate(_proposal(pattern_id="invented-pattern"))


def test_validate_proposal_returns_the_generators_own_outputs() -> None:
    target_model, roadmap = validate_proposal(
        DesignProposal.model_validate(_proposal()), inputs=_inputs()
    )

    assert target_model.pattern_id == PATTERN_ID
    assert [wave.wave_number for wave in roadmap.waves] == [1, 2, 3]
    assert [
        wave_workload.workload_id for wave in roadmap.waves for wave_workload in wave.workloads
    ] == ["w-db", "w-app", "w-report"]
