"""R6-12 acceptance: the assessment agent (design §3.1).

Everything runs against ``DeterministicAgentLoop`` -- no provider, no
network, no ADK. The loop replays a scripted step sequence and a
scripted narrative, so each test can hand the service exactly the
narrative a model might have produced and assert what the domain
contract does with it.

Each of design §3.1's five validation rules has a failing fixture here
that is rejected **and not persisted**, and rule 2 (a disposition
differing from the stored ``DispositionDecision``) has its own test as
the design asks, because it is the one that stops the model re-deciding
what the deterministic classifier already decided.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cairn_contracts.estate import (
    DecisionStatus,
    Disposition,
    DispositionDecision,
    FactStatus,
    FactValue,
    Workload,
)
from cairn_kernel.errors import (
    ForbiddenError,
    MissingDependencyError,
    SeparationOfDutiesError,
    TenantScopeViolationError,
)
from cairn_kernel.errors import ValidationError as CairnValidationError
from cairn_kernel.hex import TenantId
from cairn_kernel.hex.primitives import MutationClass
from cairn_kernel.outbox import InMemoryOutboxStore
from cairn_kernel.security import Principal, Role
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
from cairn_modules.agents.assessment_explainer import (
    AGENT_ID,
    DEFAULT_BUDGET,
    NARRATIVE_SCHEMA,
    REQUIRED_ROLE,
    TOOLSET,
    AssessmentExplainerService,
    AssessmentNarrative,
    InMemoryAssessmentNarrativeRepository,
    NarrativeContractError,
    build_spec,
    publish_narrative_to_evidence,
    validate_narrative,
)
from cairn_modules.approvals.model import ApprovalRecord, ApprovalState
from cairn_modules.assessment import AssessmentService
from cairn_modules.assessment.run import InMemoryCheckpointStore
from cairn_modules.posture.assessment import (
    ControlScore,
    ControlScoreStatus,
    CoverageReport,
    PostureAssessment,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPTS_DIR = REPO_ROOT / "prompts"

TENANT = "tenant-1"
PROJECT = "project-1"
ASSESSMENT_RUN = "ar-1"
MODEL_VERSION = "classifier-v1"
MAPPING_VERSION = "classifier-v1"
NOW = datetime(2026, 11, 27, tzinfo=UTC)


# --- fixtures ---------------------------------------------------------------


def _fact(status: FactStatus = FactStatus.OBSERVED, value: object = 4) -> FactValue:
    return FactValue(
        value=value,
        status=status,
        source="fixture",
        observed_at=NOW if status is FactStatus.OBSERVED else None,
        ingested_at=NOW,
        confidence=None,
        mapping_version=MAPPING_VERSION if status is FactStatus.INFERRED else None,
        provenance_ref="prov-1",
    )


def _workload(workload_id: str, *, facts: dict[str, FactValue] | None = None) -> Workload:
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
        facts=facts if facts is not None else {"vcpu": _fact()},
        disposition=Disposition.REHOST,
        disposition_confidence=0.7,
        model_version=MODEL_VERSION,
        mapping_version=MAPPING_VERSION,
    )


def _decision(
    workload_id: str,
    *,
    disposition: Disposition = Disposition.REHOST,
    confidence: float = 0.7,
    model_version: str = MODEL_VERSION,
    mapping_version: str = MAPPING_VERSION,
) -> DispositionDecision:
    return DispositionDecision(
        decision_id=f"{PROJECT}:{workload_id}",
        tenant_id=TENANT,
        project_id=PROJECT,
        workload_id=workload_id,
        disposition=disposition,
        rationale="fixture",
        confidence=confidence,
        status=DecisionStatus.PROPOSED,
        decided_by=None,
        decided_at=None,
        model_version=model_version,
        mapping_version=mapping_version,
    )


def _posture() -> PostureAssessment:
    return PostureAssessment(
        release_version="2026.11.1",
        scores=(
            ControlScore(
                control_id="CTRL-OK",
                release_version="2026.11.1",
                status=ControlScoreStatus.PASS,
                evaluated=True,
                finding_count=0,
                reason="passed",
            ),
            ControlScore(
                control_id="CTRL-UNKNOWN",
                release_version="2026.11.1",
                status=ControlScoreStatus.UNKNOWN,
                evaluated=True,
                finding_count=0,
                reason="no evidence",
            ),
            ControlScore(
                control_id="CTRL-NOT-RUN",
                release_version="2026.11.1",
                status=ControlScoreStatus.UNKNOWN,
                evaluated=False,
                finding_count=0,
                reason="not evaluated",
            ),
        ),
        coverage=CoverageReport(
            release_version="2026.11.1",
            evaluated_control_ids=("CTRL-OK", "CTRL-UNKNOWN"),
            not_evaluated_control_ids=("CTRL-NOT-RUN",),
        ),
    )


def _assessment_service(
    *,
    decisions: tuple[DispositionDecision, ...] | None = None,
    workloads: tuple[Workload, ...] | None = None,
    tenant_id: str = TENANT,
) -> AssessmentService:
    """A queued assessment run carrying the artifacts a finished one
    would, written through the module's own service."""

    service = AssessmentService(
        checkpoint_store=InMemoryCheckpointStore(), outbox=InMemoryOutboxStore()
    )
    run = service.queue_run(run_id=ASSESSMENT_RUN, tenant_id=tenant_id, project_id=PROJECT)
    the_workloads = workloads if workloads is not None else (_workload("w-1"), _workload("w-2"))
    the_decisions = decisions if decisions is not None else (_decision("w-1"), _decision("w-2"))
    context = (
        run.context.with_artifact("workloads", the_workloads)
        .with_artifact("resources", ())
        .with_artifact("posture_assessment", _posture())
        .with_artifact("cost_records", ())
        .with_artifact("disposition_decisions", the_decisions)
    )
    service._store.save(dataclasses.replace(run, context=context))
    return service


def _prompt_registry() -> PromptRegistry:
    """The repository's real ``prompts/`` tree -- this agent's prompt
    references must resolve against what actually ships, not a fixture
    (A6.prompts, R6-01)."""

    return PromptRegistry.load(PROMPTS_DIR)


def _mcp_registry() -> McpRegistry:
    """A registry exposing exactly this agent's ten tools, every one
    ``READ``. ``cairn_modules`` cannot import ``cairn_mcp_gateway``
    (``domain-purity``), so the real servers are not reachable from
    here; what matters to the spec is each tool's capability and
    required role, which this carries faithfully."""

    registry = McpRegistry()
    registry.register(
        BoundedContextServer(
            context_id="agent-toolset",
            name="agent-toolset",
            tools=TOOLSET,
            capabilities=dict.fromkeys(TOOLSET, ToolCapability.READ),
            handle=lambda tool_name, arguments, principal: None,
        )
    )
    return registry


def _tool_roles() -> dict[str, Role]:
    """The real ``REQUIRED_ROLES`` values for these ten tools:
    ``posture.get_control`` is ``AUDITOR``, the rest ``VIEWER``."""

    roles = dict.fromkeys(TOOLSET, Role.VIEWER)
    roles["posture.get_control"] = Role.AUDITOR
    return roles


def _principal(*, roles: tuple[Role, ...] = (Role.ENGINEER,), subject: str = "user-1") -> Principal:
    return Principal(subject=subject, tenant_id=TenantId(TENANT), roles=roles)


def _narrative(**overrides: object) -> dict[str, object]:
    """A narrative that satisfies all five rules against the default
    fixture run. Every failing case below is this, with one thing
    wrong."""

    payload: dict[str, object] = {
        "run_id": ASSESSMENT_RUN,
        "model_version": MODEL_VERSION,
        "mapping_version": MAPPING_VERSION,
        "dispositions": [
            {
                "workload_id": "w-1",
                "disposition": "REHOST",
                "explanation": "lift and shift, no code change needed",
                "fact_refs": ["workload:w-1/vcpu", "control:CTRL-OK"],
                "confidence_stated": 0.7,
                "not_exact_refs": [],
            },
            {
                "workload_id": "w-2",
                "disposition": "REHOST",
                "explanation": "same shape as w-1",
                "fact_refs": ["workload:w-2/vcpu"],
                "confidence_stated": 0.7,
                "not_exact_refs": [],
            },
        ],
        "anomalies": [
            {
                "kind": "UNSCORED_CONTROL",
                "subject_ref": "control:CTRL-NOT-RUN",
                "statement": "this control was never evaluated for this estate",
                "fact_refs": ["control:CTRL-NOT-RUN"],
                "not_exact_refs": ["control:CTRL-NOT-RUN"],
            }
        ],
        "summary_draft": "Two workloads, both rehost. One control was not evaluated.",
    }
    payload.update(overrides)
    return payload


def _steps() -> tuple[AgentStep, ...]:
    return (
        AgentStep(
            index=0,
            kind=StepKind.MODEL_CALL,
            detail={"prompt_id": "assessment-explainer/system", "prompt_version": 1},
        ),
        AgentStep(
            index=1,
            kind=StepKind.TOOL_CALL,
            detail={"tool_name": "assessment.get_results"},
        ),
    )


def _service(
    *,
    narrative: dict[str, object] | None,
    assessment_service: AssessmentService | None = None,
    repository: InMemoryAssessmentNarrativeRepository | None = None,
    budget: RunBudget = DEFAULT_BUDGET,
    steps: tuple[AgentStep, ...] | None = None,
) -> tuple[AssessmentExplainerService, InMemoryAssessmentNarrativeRepository]:
    repo = repository if repository is not None else InMemoryAssessmentNarrativeRepository()
    loop = DeterministicAgentLoop(
        steps if steps is not None else _steps(),
        clock=FixedClock(NOW),
        scripted_proposal=narrative,
    )
    service = AssessmentExplainerService(
        agent_loop=loop,
        assessment_service=(
            assessment_service if assessment_service is not None else _assessment_service()
        ),
        narrative_repository=repo,
        prompt_registry=_prompt_registry(),
        mcp_registry=_mcp_registry(),
        tool_roles=_tool_roles(),
        step_recorder=InMemoryStepRecorder(),
        clock=FixedClock(NOW),
        id_generator=FixedIdGenerator(),
        budget=budget,
    )
    return service, repo


def _explain(**kwargs: object):
    service, repo = _service(**kwargs)  # type: ignore[arg-type]
    result = service.explain(
        assessment_run_id=ASSESSMENT_RUN, principal=_principal(), correlation_id="corr-1"
    )
    return result, repo


# --- the spec ---------------------------------------------------------------


def test_the_spec_declares_ten_read_tools_and_its_output_schema() -> None:
    spec = build_spec(
        prompt_registry=_prompt_registry(),
        mcp_registry=_mcp_registry(),
        tool_roles=_tool_roles(),
    )

    assert spec.agent_id == AGENT_ID
    assert len(spec.toolset) == 10
    assert spec.output_schema is NARRATIVE_SCHEMA
    assert spec.required_role is REQUIRED_ROLE


def test_the_specs_required_role_dominates_its_toolsets_roles() -> None:
    """``posture.get_control`` needs ``AUDITOR``; ``ENGINEER`` is
    stronger, so the run can never fail at step 30 on a
    ``ForbiddenError`` the spec could have caught."""

    spec = build_spec(
        prompt_registry=_prompt_registry(),
        mcp_registry=_mcp_registry(),
        tool_roles=_tool_roles(),
    )

    assert spec.required_role is Role.ENGINEER


def test_every_prompt_reference_resolves_against_the_shipped_prompts() -> None:
    """``AgentSpec.build`` validates references at construction, so this
    passing means all four prompt files exist with the declared
    versions (A5.13, R6-01)."""

    build_spec(
        prompt_registry=_prompt_registry(),
        mcp_registry=_mcp_registry(),
        tool_roles=_tool_roles(),
    )


def test_a_toolset_tool_with_no_declared_required_role_is_refused() -> None:
    """``AgentSpec.build`` will not guess a role for a tool: an empty
    table is a missing dependency, not a permissive default."""

    with pytest.raises(MissingDependencyError, match="required role"):
        build_spec(
            prompt_registry=_prompt_registry(),
            mcp_registry=_mcp_registry(),
            tool_roles={},
        )


def test_the_spec_is_refused_if_one_of_its_tools_is_not_read_or_propose() -> None:
    """R-AGENT-03 at construction. The whole toolset is declared
    ``READ`` by the real servers; if one of them were ever registered as
    something else, this agent could not be built at all."""

    registry = McpRegistry()
    capabilities: dict[str, ToolCapability] = dict.fromkeys(TOOLSET, ToolCapability.READ)
    capabilities["estate.get_workload"] = "WRITE"  # type: ignore[assignment]
    registry.register(
        BoundedContextServer(
            context_id="agent-toolset",
            name="agent-toolset",
            tools=TOOLSET,
            capabilities=capabilities,
            handle=lambda tool_name, arguments, principal: None,
        )
    )

    with pytest.raises(CairnValidationError, match="neither READ nor PROPOSE"):
        build_spec(
            prompt_registry=_prompt_registry(),
            mcp_registry=registry,
            tool_roles=_tool_roles(),
        )


# --- the happy path ---------------------------------------------------------


def test_a_valid_narrative_is_persisted_as_a_model_drafted_draft() -> None:
    result, repo = _explain(narrative=_narrative())

    assert result.accepted
    assert result.run.state is AgentRunState.COMPLETED
    draft = result.draft
    assert draft is not None
    assert draft.model_drafted is True
    assert draft.agent_id == AGENT_ID
    assert draft.proposed_by == "user-1"
    assert draft.assessment_run_id == ASSESSMENT_RUN
    assert repo.drafts_for_run(ASSESSMENT_RUN) == (draft,)


def test_the_draft_carries_no_approval_state_of_its_own() -> None:
    """Design §3.1: nothing is published on the agent's authority, so
    the draft type has no field an approval could be faked in."""

    result, _ = _explain(narrative=_narrative())
    draft = result.draft
    assert draft is not None

    field_names = {field.name for field in dataclasses.fields(draft)}
    assert not {name for name in field_names if "approv" in name.lower()}


# --- rule 1: coverage -------------------------------------------------------


def test_rule_1_a_narrative_explaining_an_unknown_workload_is_rejected() -> None:
    narrative = _narrative()
    narrative["dispositions"] = [
        *narrative["dispositions"],  # type: ignore[misc]
        {
            "workload_id": "w-ghost",
            "disposition": "RETIRE",
            "explanation": "invented",
            "fact_refs": ["workload:w-1/vcpu"],
            "confidence_stated": 0.7,
            "not_exact_refs": [],
        },
    ]

    result, repo = _explain(narrative=narrative)

    assert not result.accepted
    assert "w-ghost" in (result.rejection or "")
    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()


def test_rule_1_a_narrative_omitting_a_decided_workload_is_rejected() -> None:
    narrative = _narrative()
    narrative["dispositions"] = [narrative["dispositions"][0]]  # type: ignore[index]

    result, repo = _explain(narrative=narrative)

    assert not result.accepted
    assert "w-2" in (result.rejection or "")
    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()


def test_rule_1_a_workload_explained_twice_is_rejected() -> None:
    narrative = _narrative()
    narrative["dispositions"] = [
        narrative["dispositions"][0],  # type: ignore[index]
        narrative["dispositions"][0],  # type: ignore[index]
        narrative["dispositions"][1],  # type: ignore[index]
    ]

    result, repo = _explain(narrative=narrative)

    assert not result.accepted
    assert "more than once" in (result.rejection or "")
    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()


# --- rule 2: the headline check ---------------------------------------------


def test_rule_2_a_narrative_whose_disposition_differs_from_the_stored_decision_fails_the_run() -> (
    None
):
    """Design §3.1's headline rule, in its own test: "a narrative whose
    disposition differs from the stored ``DispositionDecision`` fails
    the run and persists nothing". The stored decision for w-1 is
    ``REHOST``; the narrative claims ``REFACTOR``."""

    narrative = _narrative()
    narrative["dispositions"][0]["disposition"] = "REFACTOR"  # type: ignore[index]

    result, repo = _explain(narrative=narrative)

    assert not result.accepted
    assert result.draft is None
    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()
    rejection = result.rejection or ""
    assert "REFACTOR" in rejection
    assert "REHOST" in rejection
    assert "does not re-decide" in rejection


def test_rule_2_is_checked_against_every_workload_not_just_the_first() -> None:
    narrative = _narrative()
    narrative["dispositions"][1]["disposition"] = "RETIRE"  # type: ignore[index]

    result, repo = _explain(narrative=narrative)

    assert not result.accepted
    assert "w-2" in (result.rejection or "")
    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()


# --- rule 3: citations ------------------------------------------------------


def test_rule_3_an_uncited_explanation_is_rejected() -> None:
    narrative = _narrative()
    narrative["dispositions"][0]["fact_refs"] = []  # type: ignore[index]

    result, repo = _explain(narrative=narrative)

    assert not result.accepted
    assert "uncited explanation" in (result.rejection or "")
    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()


def test_rule_3_an_uncited_anomaly_is_rejected() -> None:
    narrative = _narrative()
    narrative["anomalies"][0]["fact_refs"] = []  # type: ignore[index]
    narrative["anomalies"][0]["not_exact_refs"] = []  # type: ignore[index]

    result, repo = _explain(narrative=narrative)

    assert not result.accepted
    assert "uncited claim" in (result.rejection or "")
    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()


def test_rule_3_a_citation_that_resolves_to_nothing_is_rejected() -> None:
    """An unresolvable citation is not a weak citation, it is no
    citation."""

    narrative = _narrative()
    narrative["dispositions"][0]["fact_refs"] = ["workload:w-1/invented_fact"]  # type: ignore[index]

    result, repo = _explain(narrative=narrative)

    assert not result.accepted
    assert "invented_fact" in (result.rejection or "")
    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()


def test_rule_3_a_citation_in_an_unknown_scheme_is_rejected() -> None:
    narrative = _narrative()
    narrative["dispositions"][0]["fact_refs"] = ["vibes:w-1"]  # type: ignore[index]

    result, repo = _explain(narrative=narrative)

    assert not result.accepted
    assert "no known reference kind" in (result.rejection or "")
    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()


# --- rule 4: confidence and exactness (R-MAP-01) ----------------------------


def test_rule_4_a_restated_confidence_that_does_not_match_the_decision_is_rejected() -> None:
    narrative = _narrative()
    narrative["dispositions"][0]["confidence_stated"] = 0.95  # type: ignore[index]

    result, repo = _explain(narrative=narrative)

    assert not result.accepted
    assert "reproduced, never" in (result.rejection or "")
    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()


def test_rule_4_a_narrative_describing_an_approximate_figure_as_exact_is_rejected() -> None:
    """R-MAP-01. The workload's ``vcpu`` fact is ``APPROXIMATE`` in this
    run, and the explanation cites it without reproducing that -- which
    is presenting an approximate figure as exact."""

    workloads = (
        _workload("w-1", facts={"vcpu": _fact(FactStatus.APPROXIMATE)}),
        _workload("w-2"),
    )
    service = _assessment_service(workloads=workloads)
    narrative = _narrative()
    narrative["dispositions"][0]["not_exact_refs"] = []  # type: ignore[index]

    result, repo = _explain(narrative=narrative, assessment_service=service)

    assert not result.accepted
    assert "R-MAP-01" in (result.rejection or "")
    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()


def test_rule_4_an_unavailable_figure_described_as_exact_is_rejected() -> None:
    workloads = (
        _workload("w-1", facts={"vcpu": _fact(FactStatus.UNAVAILABLE, value=None)}),
        _workload("w-2"),
    )
    service = _assessment_service(workloads=workloads)
    narrative = _narrative()
    narrative["dispositions"][0]["not_exact_refs"] = []  # type: ignore[index]

    result, repo = _explain(narrative=narrative, assessment_service=service)

    assert not result.accepted
    assert "R-MAP-01" in (result.rejection or "")
    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()


def test_rule_4_reproducing_the_approximation_is_accepted() -> None:
    """The same narrative, honest about the same fact, passes. The rule
    is "reproduce the caveat", not "never cite an approximate fact"."""

    workloads = (
        _workload("w-1", facts={"vcpu": _fact(FactStatus.APPROXIMATE)}),
        _workload("w-2"),
    )
    service = _assessment_service(workloads=workloads)
    narrative = _narrative()
    narrative["dispositions"][0]["not_exact_refs"] = ["workload:w-1/vcpu"]  # type: ignore[index]

    result, repo = _explain(narrative=narrative, assessment_service=service)

    assert result.accepted
    assert len(repo.drafts_for_run(ASSESSMENT_RUN)) == 1


def test_rule_4_hedging_an_established_fact_is_also_rejected() -> None:
    """Misleading in the other direction: calling a fact the run
    actually observed approximate."""

    narrative = _narrative()
    narrative["dispositions"][0]["not_exact_refs"] = ["workload:w-1/vcpu"]  # type: ignore[index]

    result, repo = _explain(narrative=narrative)

    assert not result.accepted
    assert "established facts" in (result.rejection or "")
    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()


def test_rule_4_an_unevaluated_control_must_be_reproduced_as_not_established() -> None:
    narrative = _narrative()
    narrative["anomalies"][0]["not_exact_refs"] = []  # type: ignore[index]

    result, repo = _explain(narrative=narrative)

    assert not result.accepted
    assert "CTRL-NOT-RUN" in (result.rejection or "")
    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()


def test_rule_4_an_unknown_scored_control_is_not_an_established_fact() -> None:
    """``ControlScoreStatus.UNKNOWN`` means "we did not establish this",
    so citing it as fact is the same error as citing an approximate
    figure as exact."""

    narrative = _narrative()
    narrative["dispositions"][0]["fact_refs"] = [  # type: ignore[index]
        "workload:w-1/vcpu",
        "control:CTRL-UNKNOWN",
    ]

    result, repo = _explain(narrative=narrative)

    assert not result.accepted
    assert "CTRL-UNKNOWN" in (result.rejection or "")
    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()


# --- rule 5: versions (R-VER-01) -------------------------------------------


def test_rule_5_a_narrative_naming_a_different_model_version_is_rejected() -> None:
    narrative = _narrative(model_version="classifier-v2")

    result, repo = _explain(narrative=narrative)

    assert not result.accepted
    assert "classifier-v2" in (result.rejection or "")
    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()


def test_rule_5_a_narrative_naming_a_different_mapping_version_is_rejected() -> None:
    narrative = _narrative(mapping_version="map-2026.1")

    result, repo = _explain(narrative=narrative)

    assert not result.accepted
    assert "map-2026.1" in (result.rejection or "")
    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()


def test_rule_5_a_run_whose_decisions_disagree_on_a_version_can_be_claimed_by_nothing() -> None:
    service = _assessment_service(
        decisions=(_decision("w-1"), _decision("w-2", model_version="classifier-v2"))
    )

    result, repo = _explain(narrative=_narrative(), assessment_service=service)

    assert not result.accepted
    assert "do not agree on one model/mapping version" in (result.rejection or "")
    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()


# --- the narrative must name its own run ------------------------------------


def test_a_narrative_naming_another_run_is_rejected() -> None:
    result, repo = _explain(narrative=_narrative(run_id="ar-other"))

    assert not result.accepted
    assert "ar-other" in (result.rejection or "")
    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()


# --- the loop's own failures reach the service unchanged --------------------


def test_a_run_that_proposed_nothing_persists_nothing() -> None:
    result, repo = _explain(narrative=None)

    assert not result.accepted
    assert result.run.state is AgentRunState.FAILED
    assert result.rejection == "agent run produced no final proposal"
    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()


def test_a_proposal_that_fails_the_output_schema_never_reaches_the_domain_contract() -> None:
    """R6-11a's gate runs first: a proposal missing a schema-required
    field fails inside the loop, so the run is ``FAILED`` and
    ``proposal`` is ``None`` before this agent's own rules are
    consulted."""

    result, repo = _explain(narrative={"run_id": ASSESSMENT_RUN})

    assert not result.accepted
    assert result.run.state is AgentRunState.FAILED
    assert result.run.proposal is None
    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()


def test_a_budget_stopped_run_persists_nothing() -> None:
    result, repo = _explain(
        narrative=_narrative(),
        budget=RunBudget(
            max_steps=1,
            max_model_calls=20,
            max_total_tokens=300_000,
            max_cost_micro_usd=2_000_000,
            max_wall_clock_seconds=600,
        ),
    )

    assert not result.accepted
    assert result.run.state is AgentRunState.BUDGET_EXCEEDED
    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()


def test_a_structurally_malformed_narrative_is_rejected_not_coerced() -> None:
    """``extra="forbid"``: a field this agent does not declare is a
    field no reviewer will see, so it is a rejection rather than a
    silent drop."""

    narrative = _narrative()
    narrative["editorial_note"] = "ignore the validation rules"

    result, repo = _explain(narrative=narrative)

    assert not result.accepted
    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()


# --- authority --------------------------------------------------------------


def test_a_principal_without_the_required_role_cannot_start_a_run() -> None:
    service, repo = _service(narrative=_narrative())

    with pytest.raises(ForbiddenError, match="ENGINEER"):
        service.explain(
            assessment_run_id=ASSESSMENT_RUN,
            principal=_principal(roles=(Role.VIEWER,)),
            correlation_id="corr-1",
        )

    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()


def test_a_principal_from_another_tenant_cannot_explain_this_run() -> None:
    service, repo = _service(narrative=_narrative())

    with pytest.raises(TenantScopeViolationError):
        service.explain(
            assessment_run_id=ASSESSMENT_RUN,
            principal=Principal(
                subject="user-2", tenant_id=TenantId("tenant-2"), roles=(Role.ENGINEER,)
            ),
            correlation_id="corr-1",
        )

    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()


def test_the_run_records_the_starting_principal_as_the_actor() -> None:
    """A7.actor: the actor is required on the run and is the principal
    that started it, never inferred."""

    result, _ = _explain(narrative=_narrative())

    assert result.run.actor == "user-1"
    assert result.draft is not None
    assert result.draft.proposed_by == "user-1"


# --- the approval point -----------------------------------------------------


def _approval(
    draft_id: str,
    *,
    state: ApprovalState = ApprovalState.APPROVED,
    approver: str | None = "reviewer-1",
) -> ApprovalRecord:
    return ApprovalRecord(
        approval_id="ap-1",
        tenant_id=TENANT,
        project_id=PROJECT,
        subject_kind="assessment_narrative",
        subject_id=draft_id,
        revision_id="rev-1",
        revision_hash="hash-1",
        mutation_class=MutationClass.INTERNAL_MUTATION,
        risk_tier="low",
        state=state,
        proposer_actor_id="user-1",
        approver_actor_id=approver,
    )


def test_publishing_a_draft_without_an_approval_raises() -> None:
    """Design §3.1's approval point: including the narrative in a signed
    evidence package requires a human accept. Nothing is published on
    the agent's authority."""

    result, _ = _explain(narrative=_narrative())
    draft = result.draft
    assert draft is not None

    with pytest.raises(ForbiddenError, match="unapproved"):
        publish_narrative_to_evidence(draft, approval=None)


@pytest.mark.parametrize(
    "state",
    [
        ApprovalState.DRAFT,
        ApprovalState.PENDING_APPROVAL,
        ApprovalState.REJECTED,
        ApprovalState.CANCELLED,
        ApprovalState.EXPIRED,
    ],
)
def test_publishing_a_draft_on_a_non_approved_approval_raises(state: ApprovalState) -> None:
    result, _ = _explain(narrative=_narrative())
    draft = result.draft
    assert draft is not None

    with pytest.raises(ForbiddenError, match="not APPROVED"):
        publish_narrative_to_evidence(draft, approval=_approval(draft.draft_id, state=state))


def test_publishing_a_draft_on_an_approval_for_something_else_raises() -> None:
    result, _ = _explain(narrative=_narrative())
    draft = result.draft
    assert draft is not None

    with pytest.raises(ForbiddenError, match="not narrative draft"):
        publish_narrative_to_evidence(draft, approval=_approval("some-other-draft"))


def test_publishing_a_draft_on_an_approval_with_no_approver_raises() -> None:
    result, _ = _explain(narrative=_narrative())
    draft = result.draft
    assert draft is not None

    with pytest.raises(ForbiddenError, match="no approver"):
        publish_narrative_to_evidence(draft, approval=_approval(draft.draft_id, approver=None))


def test_the_principal_that_started_the_run_cannot_approve_its_own_narrative() -> None:
    """ADR-019 §6: separation of duties treats the run's starting
    principal as the proposer."""

    result, _ = _explain(narrative=_narrative())
    draft = result.draft
    assert draft is not None

    with pytest.raises(SeparationOfDutiesError):
        publish_narrative_to_evidence(draft, approval=_approval(draft.draft_id, approver="user-1"))


def test_an_approved_draft_with_a_different_approver_publishes() -> None:
    result, _ = _explain(narrative=_narrative())
    draft = result.draft
    assert draft is not None

    assert publish_narrative_to_evidence(draft, approval=_approval(draft.draft_id)) is draft


# --- validate_narrative, called directly ------------------------------------


def test_validate_narrative_raises_narrative_contract_error() -> None:
    """The service turns this into a rejection on its result; callers
    that validate a narrative themselves get the typed error."""

    service = _assessment_service()
    narrative = AssessmentNarrative.model_validate(_narrative())
    bad = AssessmentNarrative.model_validate({**_narrative(), "model_version": "classifier-v9"})

    validate_narrative(narrative, run=service.get_run(ASSESSMENT_RUN))
    with pytest.raises(NarrativeContractError):
        validate_narrative(bad, run=service.get_run(ASSESSMENT_RUN))


def test_a_run_with_no_stored_decisions_has_nothing_to_explain() -> None:
    service = _assessment_service(decisions=())

    result, repo = _explain(narrative=_narrative(), assessment_service=service)

    assert not result.accepted
    assert "nothing" in (result.rejection or "")
    assert repo.drafts_for_run(ASSESSMENT_RUN) == ()
