"""R6-14 acceptance: the modernize agent (design §3.3).

Against ``DeterministicAgentLoop`` throughout -- no provider, no
network, no ADK, and no transformation subprocess: the manifest these
tests validate against is built directly, because every rule here is
about agreeing with a manifest on record rather than about producing
one.

The fixture manifest has three entries, one of each ``ManifestOutcome``,
and the ``UNSUPPORTED`` one uses the real detector rule id that needs a
mapping lookup (``tf-dynamodb-table-cross-provider-equivalence``). The
real ``mappings/service-map.yaml`` resolves that to an ``APPROXIMATE``
equivalence with a real caveat, which is what makes rule 5's tests
genuine rather than a fixture agreeing with itself.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from cairn_contracts.estate import Equivalence
from cairn_contracts.mapping import ReleaseStatus
from cairn_kernel.errors import ForbiddenError, TenantScopeViolationError
from cairn_kernel.hex import TenantId
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
from cairn_modules.agents.modernize_proposer import (
    AGENT_ID,
    DEFAULT_BUDGET,
    PROPOSAL_SCHEMA,
    REQUIRED_ROLE,
    TOOLSET,
    ModernizeContractError,
    ModernizeInputs,
    ModernizeProposerService,
    TransformationPlanProposal,
    build_spec,
    entry_id_for,
    manifest_hash,
    render_review_comment,
    validate_proposal,
    validation_summary_of,
)
from cairn_modules.mappings import load_mapping_release
from cairn_modules.transformation.engine import (
    ManifestEdit,
    ManifestEntry,
    ManifestOutcome,
    TransformationManifest,
)
from cairn_modules.transformation.review import (
    ReviewComment,
    ReviewDecisionKind,
    RunReviewThread,
)
from cairn_modules.transformation.runs import TransformationRunRecord
from cairn_modules.transformation.validation import ValidationResult, ValidationRun

REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPTS_DIR = REPO_ROOT / "prompts"
MAPPING_SEED = REPO_ROOT / "mappings" / "service-map.yaml"

TENANT = "tenant-1"
PROJECT = "project-1"
PLAN_REVISION = "rev-1"
RUN_ID = "tr-1"
NOW = datetime(2026, 11, 27, tzinfo=UTC)

APPLIED_FILE = "main.tf"
SKIPPED_FILE = "variables.tf"
UNSUPPORTED_FILE = "dynamo.tf"

MAPPING_RULE = "tf-dynamodb-table-cross-provider-equivalence"
UNSUPPORTED_REASON = "cross-provider equivalence cannot be patched automatically"

#: The real seed's own aws:dynamodb -> gcp resolution.
EXPECTED_MAPPING_VERSION = "2026.11.2"
EXPECTED_CAVEAT = (
    "Access patterns and secondary indexes require redesign; Bigtable has no native"
    " secondary-index equivalent to DynamoDB GSIs/LSIs"
)


# --- fixtures ---------------------------------------------------------------


def _mapping_release():
    return load_mapping_release(MAPPING_SEED).model_copy(update={"status": ReleaseStatus.PUBLISHED})


def _manifest() -> TransformationManifest:
    return TransformationManifest(
        source_file_ids=(APPLIED_FILE, SKIPPED_FILE, UNSUPPORTED_FILE),
        entries=(
            ManifestEntry(
                source_file_id=APPLIED_FILE,
                rule_id="tf-s3-bucket-public-access",
                outcome=ManifestOutcome.APPLIED,
                reason=None,
                edits=(
                    ManifestEdit(
                        start_byte=10,
                        end_byte=20,
                        start_line=2,
                        end_line=2,
                        replacement="false",
                    ),
                ),
                detector_version="d-1",
                pattern_version="p-1",
                patcher_version="x-1",
            ),
            ManifestEntry(
                source_file_id=SKIPPED_FILE,
                rule_id="tf-variable-default",
                outcome=ManifestOutcome.SKIPPED,
                reason="already compliant",
                edits=(),
                detector_version="d-1",
                pattern_version="p-1",
                patcher_version="x-1",
            ),
            ManifestEntry(
                source_file_id=UNSUPPORTED_FILE,
                rule_id=MAPPING_RULE,
                outcome=ManifestOutcome.UNSUPPORTED,
                reason=UNSUPPORTED_REASON,
                edits=(),
                detector_version="d-1",
                pattern_version="p-1",
                patcher_version="x-1",
                mapping_release_version=EXPECTED_MAPPING_VERSION,
            ),
        ),
    )


def _run_record(manifest: TransformationManifest | None = None) -> TransformationRunRecord:
    return TransformationRunRecord(
        run_id=RUN_ID,
        tenant_id=TENANT,
        project_id=PROJECT,
        run_number=1,
        manifest=manifest if manifest is not None else _manifest(),
        created_by="engineer-1",
        created_at=NOW,
    )


def _validation_run() -> ValidationRun:
    return ValidationRun(
        run_id=RUN_ID,
        results=(
            ValidationResult(check_id="terraform-validate", passed=True, reason=None),
            ValidationResult(
                check_id="dependency-scan", passed=False, reason="one advisory remains"
            ),
        ),
    )


def _entry_ids(manifest: TransformationManifest | None = None) -> list[str]:
    the_manifest = manifest if manifest is not None else _manifest()
    return [entry_id_for(index, entry) for index, entry in enumerate(the_manifest.entries)]


def _inputs(
    *,
    manifest: TransformationManifest | None = None,
    mapping_release_present: bool = True,
    thread: RunReviewThread | None = None,
    tenant_id: str = TENANT,
) -> ModernizeInputs:
    return ModernizeInputs(
        tenant_id=tenant_id,
        project_id=PROJECT,
        plan_revision_id=PLAN_REVISION,
        run_record=_run_record(manifest),
        validation_run=_validation_run(),
        review_thread=thread if thread is not None else RunReviewThread(run_id=RUN_ID),
        mapping_release=_mapping_release() if mapping_release_present else None,
        source_file_paths=(APPLIED_FILE, SKIPPED_FILE, UNSUPPORTED_FILE, "unused.tf"),
    )


def _proposal(**overrides: object) -> dict[str, object]:
    """A proposal that satisfies all six rules against the default
    fixture. Every failing case is this, with one thing wrong."""

    applied_id, skipped_id, unsupported_id = _entry_ids()
    payload: dict[str, object] = {
        "plan_revision_id": PLAN_REVISION,
        "run_id": RUN_ID,
        "manifest_hash": manifest_hash(_manifest()),
        "scope": {
            "file_paths": [APPLIED_FILE, SKIPPED_FILE, UNSUPPORTED_FILE],
            "excluded": [{"path": "unused.tf", "reason": "no detector rule matches it"}],
        },
        "explanations": [
            {
                "entry_id": applied_id,
                "file_path": APPLIED_FILE,
                "hunk_ref": "@@ -2,1 +2,1 @@",
                "outcome": "APPLIED",
                "mapping_version": None,
                "equivalence": None,
                "caveat": None,
                "explanation": "public access on the bucket is turned off in place",
                "reviewer_attention": False,
            },
            {
                "entry_id": skipped_id,
                "file_path": SKIPPED_FILE,
                "hunk_ref": "n/a",
                "outcome": "SKIPPED",
                "mapping_version": None,
                "equivalence": None,
                "caveat": None,
                "explanation": "the variable already carries a compliant default",
                "reviewer_attention": False,
            },
            {
                "entry_id": unsupported_id,
                "file_path": UNSUPPORTED_FILE,
                "hunk_ref": "n/a",
                "outcome": "UNSUPPORTED",
                "mapping_version": EXPECTED_MAPPING_VERSION,
                "equivalence": "APPROXIMATE",
                "caveat": EXPECTED_CAVEAT,
                "explanation": "the table has no like-for-like target and needs redesign",
                "reviewer_attention": True,
            },
        ],
        "unsupported": [
            {
                "entry_id": unsupported_id,
                "engine_reason": UNSUPPORTED_REASON,
                "suggested_manual_step": "model the access patterns against Bigtable by hand",
            }
        ],
        "validation_summary": validation_summary_of(_validation_run()),
    }
    payload.update(overrides)
    return payload


def _prompt_registry() -> PromptRegistry:
    return PromptRegistry.load(PROMPTS_DIR)


def _mcp_registry(*, propose_capability: ToolCapability = ToolCapability.PROPOSE) -> McpRegistry:
    registry = McpRegistry()
    capabilities: dict[str, ToolCapability] = dict.fromkeys(TOOLSET, ToolCapability.READ)
    capabilities["transformation.run"] = propose_capability
    capabilities["transformation.validate"] = propose_capability
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
    roles["transformation.run"] = Role.ENGINEER
    roles["transformation.validate"] = Role.ENGINEER
    return roles


def _principal(
    *, roles: tuple[Role, ...] = (Role.ENGINEER,), subject: str = "engineer-1"
) -> Principal:
    return Principal(subject=subject, tenant_id=TenantId(TENANT), roles=roles)


def _steps() -> tuple[AgentStep, ...]:
    return (
        AgentStep(
            index=0,
            kind=StepKind.MODEL_CALL,
            detail={"prompt_id": "modernize-proposer/explain-diff", "prompt_version": 1},
        ),
        AgentStep(index=1, kind=StepKind.TOOL_CALL, detail={"tool_name": "transformation.run"}),
    )


def _service(
    *, proposal: dict[str, object] | None, budget: RunBudget = DEFAULT_BUDGET
) -> ModernizeProposerService:
    loop = DeterministicAgentLoop(_steps(), clock=FixedClock(NOW), scripted_proposal=proposal)
    return ModernizeProposerService(
        agent_loop=loop,
        prompt_registry=_prompt_registry(),
        mcp_registry=_mcp_registry(),
        tool_roles=_tool_roles(),
        step_recorder=InMemoryStepRecorder(),
        clock=FixedClock(NOW),
        id_generator=FixedIdGenerator(),
        budget=budget,
    )


def _propose(
    *,
    proposal: dict[str, object] | None,
    inputs: ModernizeInputs | None = None,
    budget: RunBudget = DEFAULT_BUDGET,
):
    service = _service(proposal=proposal, budget=budget)
    return service.propose(
        inputs=inputs if inputs is not None else _inputs(),
        principal=_principal(),
        correlation_id="corr-1",
    )


# --- the spec ---------------------------------------------------------------


def test_the_spec_declares_five_read_tools_and_two_propose_tools() -> None:
    spec = build_spec(
        prompt_registry=_prompt_registry(),
        mcp_registry=_mcp_registry(),
        tool_roles=_tool_roles(),
    )

    assert spec.agent_id == AGENT_ID
    assert len(spec.toolset) == 7
    assert spec.output_schema is PROPOSAL_SCHEMA
    assert spec.required_role is REQUIRED_ROLE is Role.ENGINEER


def test_the_toolset_has_no_apply_tool_and_no_path_to_the_execution_gate() -> None:
    """Design §3.3/§11: applying a diff anywhere is a separate Class C
    operation behind the execution gate, and the agent has no tool for
    it."""

    forbidden = ("apply", "publish", "approve", "execute", "commit", "push", "delete")
    assert not [tool for tool in TOOLSET if any(word in tool for word in forbidden)]


def test_the_spec_is_refused_if_a_propose_tool_is_registered_as_something_else() -> None:
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


# --- the happy path ---------------------------------------------------------


def test_a_valid_proposal_lands_on_the_review_thread_as_model_drafted() -> None:
    result = _propose(proposal=_proposal())

    assert result.accepted
    assert result.run.state is AgentRunState.COMPLETED
    comment = result.comment
    assert comment is not None
    assert comment.decision is ReviewDecisionKind.COMMENT
    assert "Model-drafted by agent modernize-proposer" in comment.body
    assert "Unapproved" in comment.body
    assert comment.reviewer_actor_id == "engineer-1"
    assert result.thread.comments == (comment,)


def test_the_comment_reproduces_the_caveat_rather_than_summarising_it() -> None:
    result = _propose(proposal=_proposal())

    assert result.comment is not None
    assert EXPECTED_CAVEAT in result.comment.body
    assert "APPROXIMATE" in result.comment.body


def test_the_comment_names_the_engines_reason_for_an_unsupported_entry() -> None:
    result = _propose(proposal=_proposal())

    assert result.comment is not None
    assert UNSUPPORTED_REASON in result.comment.body
    assert "model the access patterns against Bigtable by hand" in result.comment.body


# --- rule 1: the manifest on record -----------------------------------------


def test_rule_1_an_explanation_set_whose_manifest_hash_does_not_match_is_rejected() -> None:
    """The run sheet's own bolded criterion, and the check design §3.3
    calls "the check that stops a plausible explanation attaching to the
    wrong artefact"."""

    result = _propose(proposal=_proposal(manifest_hash="0" * 64))

    assert not result.accepted
    assert "may not explain a diff that is not the one on record" in (result.rejection or "")
    assert result.thread.comments == ()


def test_rule_1_the_hash_moves_when_any_manifest_field_changes() -> None:
    """The hash is only a real check if it is sensitive. One edit byte
    is enough to move it."""

    original = _manifest()
    altered = TransformationManifest(
        source_file_ids=original.source_file_ids,
        entries=(
            ManifestEntry(
                source_file_id=APPLIED_FILE,
                rule_id="tf-s3-bucket-public-access",
                outcome=ManifestOutcome.APPLIED,
                reason=None,
                edits=(
                    ManifestEdit(
                        start_byte=10,
                        end_byte=20,
                        start_line=2,
                        end_line=2,
                        replacement="true",
                    ),
                ),
                detector_version="d-1",
                pattern_version="p-1",
                patcher_version="x-1",
            ),
            *original.entries[1:],
        ),
    )

    assert manifest_hash(original) != manifest_hash(altered)
    assert manifest_hash(original) == manifest_hash(_manifest())


def test_rule_1_a_proposal_for_another_run_is_rejected() -> None:
    result = _propose(proposal=_proposal(run_id="tr-other"))

    assert not result.accepted
    assert "tr-other" in (result.rejection or "")
    assert result.thread.comments == ()


def test_rule_1_a_proposal_for_another_plan_revision_is_rejected() -> None:
    result = _propose(proposal=_proposal(plan_revision_id="rev-other"))

    assert not result.accepted
    assert "rev-other" in (result.rejection or "")
    assert result.thread.comments == ()


# --- rule 2: one explanation per entry --------------------------------------


def test_rule_2_a_manifest_entry_with_no_explanation_is_rejected() -> None:
    proposal = _proposal()
    proposal["explanations"] = proposal["explanations"][:2]  # type: ignore[index]
    proposal["unsupported"] = []

    result = _propose(proposal=proposal)

    assert not result.accepted
    assert "have no explanation" in (result.rejection or "")
    assert result.thread.comments == ()


def test_rule_2_an_explanation_with_no_entry_is_rejected() -> None:
    proposal = _proposal()
    proposal["explanations"] = [  # type: ignore[index]
        *proposal["explanations"],  # type: ignore[misc]
        {
            "entry_id": "99:ghost.tf:invented-rule",
            "file_path": "ghost.tf",
            "hunk_ref": "n/a",
            "outcome": "APPLIED",
            "mapping_version": None,
            "equivalence": None,
            "caveat": None,
            "explanation": "a hunk that does not exist",
            "reviewer_attention": False,
        },
    ]

    result = _propose(proposal=proposal)

    assert not result.accepted
    assert "name no entry" in (result.rejection or "")
    assert result.thread.comments == ()


def test_rule_2_an_entry_explained_twice_is_rejected() -> None:
    proposal = _proposal()
    proposal["explanations"] = [  # type: ignore[index]
        *proposal["explanations"],  # type: ignore[misc]
        proposal["explanations"][0],  # type: ignore[index]
    ]

    result = _propose(proposal=proposal)

    assert not result.accepted
    assert "explained more than once" in (result.rejection or "")
    assert result.thread.comments == ()


# --- rule 3: the engine's outcome -------------------------------------------


def test_rule_3_an_outcome_disagreeing_with_the_engine_is_rejected() -> None:
    proposal = _proposal()
    proposal["explanations"][1]["outcome"] = "APPLIED"  # type: ignore[index]

    result = _propose(proposal=proposal)

    assert not result.accepted
    rejection = result.rejection or ""
    assert "does not grade it" in rejection
    assert "SKIPPED" in rejection
    assert result.thread.comments == ()


def test_rule_3_an_explanation_attached_to_the_wrong_file_is_rejected() -> None:
    proposal = _proposal()
    proposal["explanations"][0]["file_path"] = SKIPPED_FILE  # type: ignore[index]

    result = _propose(proposal=proposal)

    assert not result.accepted
    assert "but that entry is against" in (result.rejection or "")
    assert result.thread.comments == ()


# --- rule 4: the engine's reason --------------------------------------------


def test_rule_4_an_invented_engine_reason_is_rejected() -> None:
    proposal = _proposal()
    proposal["unsupported"][0]["engine_reason"] = (  # type: ignore[index]
        "the engine said this was too hard"
    )

    result = _propose(proposal=proposal)

    assert not result.accepted
    assert "reproduced, never invented" in (result.rejection or "")
    assert result.thread.comments == ()


def test_rule_4_an_unsupported_entry_omitted_from_the_list_is_rejected() -> None:
    result = _propose(proposal=_proposal(unsupported=[]))

    assert not result.accepted
    assert "omits them" in (result.rejection or "")
    assert result.thread.comments == ()


def test_rule_4_listing_an_entry_the_engine_did_not_call_unsupported_is_rejected() -> None:
    applied_id = _entry_ids()[0]
    proposal = _proposal(
        unsupported=[
            {
                "entry_id": applied_id,
                "engine_reason": "made up",
                "suggested_manual_step": "do something",
            }
        ]
    )

    result = _propose(proposal=proposal)

    assert not result.accepted
    assert "did not record as UNSUPPORTED" in (result.rejection or "")
    assert result.thread.comments == ()


def test_rule_4_an_unsupported_entry_with_no_suggested_step_is_rejected() -> None:
    proposal = _proposal()
    proposal["unsupported"][0]["suggested_manual_step"] = "  "  # type: ignore[index]

    result = _propose(proposal=proposal)

    assert not result.accepted
    assert "suggests no manual step" in (result.rejection or "")
    assert result.thread.comments == ()


# --- rule 5: the mapping resolution, verbatim (R-MAP-01) --------------------


def test_rule_5_a_dropped_mapping_caveat_is_rejected() -> None:
    """The run sheet's own criterion. The real seed's aws:dynamodb ->
    gcp entry carries a caveat; an explanation that leaves it out is
    rejected."""

    proposal = _proposal()
    proposal["explanations"][2]["caveat"] = None  # type: ignore[index]

    result = _propose(proposal=proposal)

    assert not result.accepted
    assert "copied verbatim and may not be dropped" in (result.rejection or "")
    assert result.thread.comments == ()


def test_rule_5_a_paraphrased_caveat_is_rejected_too() -> None:
    """Verbatim means verbatim: a shorter, friendlier caveat is a
    different caveat."""

    proposal = _proposal()
    proposal["explanations"][2]["caveat"] = "indexes need some work"  # type: ignore[index]

    result = _propose(proposal=proposal)

    assert not result.accepted
    assert "copied verbatim" in (result.rejection or "")
    assert result.thread.comments == ()


def test_rule_5_an_approximate_equivalence_described_as_exact_is_rejected() -> None:
    proposal = _proposal()
    proposal["explanations"][2]["equivalence"] = "EXACT"  # type: ignore[index]

    result = _propose(proposal=proposal)

    assert not result.accepted
    assert "R-MAP-01" in (result.rejection or "")
    assert result.thread.comments == ()


def test_rule_5_an_equivalence_claimed_where_no_mapping_was_resolved_is_rejected() -> None:
    """The ``APPLIED`` entry's rule needs no mapping lookup, so there is
    no equivalence to reproduce and claiming one is inventing it."""

    proposal = _proposal()
    proposal["explanations"][0]["equivalence"] = "EXACT"  # type: ignore[index]

    result = _propose(proposal=proposal)

    assert not result.accepted
    assert "but the mapping release resolves None" in (result.rejection or "")
    assert result.thread.comments == ()


def test_rule_5_a_wrong_mapping_version_is_rejected() -> None:
    proposal = _proposal()
    proposal["explanations"][2]["mapping_version"] = "2020.1.0"  # type: ignore[index]

    result = _propose(proposal=proposal)

    assert not result.accepted
    assert "2020.1.0" in (result.rejection or "")
    assert result.thread.comments == ()


def test_rule_5_with_no_mapping_release_no_equivalence_may_be_claimed() -> None:
    """Design's own three-way view of the same lookup: no release means
    no equivalence judgement can be rendered, so reproducing one is a
    failure rather than a pass."""

    result = _propose(proposal=_proposal(), inputs=_inputs(mapping_release_present=False))

    assert not result.accepted
    # the version is checked first, so that is the field named; either
    # way the proposal is refused for claiming a resolution that was
    # never made.
    assert "this entry resolves against None" in (result.rejection or "")
    assert result.thread.comments == ()


def test_rule_5_with_no_mapping_release_an_honest_proposal_is_accepted() -> None:
    proposal = _proposal()
    proposal["explanations"][2]["mapping_version"] = None  # type: ignore[index]
    proposal["explanations"][2]["equivalence"] = None  # type: ignore[index]
    proposal["explanations"][2]["caveat"] = None  # type: ignore[index]

    result = _propose(proposal=proposal, inputs=_inputs(mapping_release_present=False))

    assert result.accepted


# --- rule 6: the real validation result -------------------------------------


def test_rule_6_a_model_summary_of_the_validation_result_is_rejected() -> None:
    result = _propose(proposal=_proposal(validation_summary={"run_id": RUN_ID, "approved": True}))

    assert not result.accepted
    assert "not a model summary of it" in (result.rejection or "")
    assert result.thread.comments == ()


def test_rule_6_a_validation_summary_that_flips_a_failed_check_is_rejected() -> None:
    summary = validation_summary_of(_validation_run())
    summary["results"][1]["passed"] = True  # type: ignore[index]

    result = _propose(proposal=_proposal(validation_summary=summary))

    assert not result.accepted
    assert "not a model summary of it" in (result.rejection or "")
    assert result.thread.comments == ()


# --- scope ------------------------------------------------------------------


def test_a_scope_that_is_not_the_manifests_own_file_set_is_rejected() -> None:
    proposal = _proposal()
    proposal["scope"]["file_paths"] = [APPLIED_FILE]  # type: ignore[index]

    result = _propose(proposal=proposal)

    assert not result.accepted
    assert "manifest actually covers" in (result.rejection or "")
    assert result.thread.comments == ()


def test_excluding_a_file_the_manifest_does_cover_is_rejected() -> None:
    proposal = _proposal()
    proposal["scope"]["excluded"] = [  # type: ignore[index]
        {"path": APPLIED_FILE, "reason": "out of scope"}
    ]

    result = _propose(proposal=proposal)

    assert not result.accepted
    assert "which the manifest does cover" in (result.rejection or "")
    assert result.thread.comments == ()


def test_an_exclusion_with_no_reason_is_rejected() -> None:
    proposal = _proposal()
    proposal["scope"]["excluded"] = [{"path": "unused.tf", "reason": "  "}]  # type: ignore[index]

    result = _propose(proposal=proposal)

    assert not result.accepted
    assert "unexplained" in (result.rejection or "")
    assert result.thread.comments == ()


def test_excluding_a_file_outside_the_project_is_rejected() -> None:
    proposal = _proposal()
    proposal["scope"]["excluded"] = [  # type: ignore[index]
        {"path": "elsewhere.tf", "reason": "not ours"}
    ]

    result = _propose(proposal=proposal)

    assert not result.accepted
    assert "not a source file in this project" in (result.rejection or "")
    assert result.thread.comments == ()


# --- the review thread's existing semantics are unchanged -------------------


def test_a_blocked_thread_stays_blocked_after_the_agent_comments() -> None:
    """The run sheet's own criterion. A ``COMMENT`` carries no decision
    of its own, so a standing ``REQUEST_CHANGES`` survives it."""

    blocked = RunReviewThread(
        run_id=RUN_ID,
        comments=(
            ReviewComment(
                run_id=RUN_ID,
                reviewer_actor_id="reviewer-1",
                decision=ReviewDecisionKind.REQUEST_CHANGES,
                body="not until the dynamo redesign is agreed",
                created_at=NOW,
            ),
        ),
    )
    assert blocked.blocked is True

    result = _propose(proposal=_proposal(), inputs=_inputs(thread=blocked))

    assert result.accepted
    assert result.thread.blocked is True
    assert len(result.thread.comments) == 2


def test_the_agent_only_ever_posts_a_plain_comment() -> None:
    """It can neither clear a block nor stand in for an approval,
    because the only decision kind it posts carries no decision."""

    result = _propose(proposal=_proposal())

    assert result.comment is not None
    assert result.comment.decision is ReviewDecisionKind.COMMENT


def test_an_unreviewed_thread_is_still_unreviewed_after_the_agent_comments() -> None:
    """``RunReviewThread.reviewed`` is "a human has decided something".
    The agent commenting must not make that true."""

    result = _propose(proposal=_proposal())

    assert result.thread.reviewed is False


def test_a_rejected_proposal_leaves_the_thread_untouched() -> None:
    thread = RunReviewThread(run_id=RUN_ID)

    result = _propose(proposal=_proposal(manifest_hash="0" * 64), inputs=_inputs(thread=thread))

    assert not result.accepted
    assert result.thread is thread
    assert result.thread.comments == ()


# --- the loop's own failures -------------------------------------------------


def test_a_run_that_proposed_nothing_posts_nothing() -> None:
    result = _propose(proposal=None)

    assert not result.accepted
    assert result.run.state is AgentRunState.FAILED
    assert result.thread.comments == ()


def test_a_proposal_failing_the_output_schema_never_reaches_the_domain_contract() -> None:
    result = _propose(proposal={"run_id": RUN_ID})

    assert not result.accepted
    assert result.run.state is AgentRunState.FAILED
    assert result.run.proposal is None
    assert result.thread.comments == ()


def test_a_budget_stopped_run_posts_nothing() -> None:
    result = _propose(
        proposal=_proposal(),
        budget=RunBudget(
            max_steps=1,
            max_model_calls=40,
            max_total_tokens=600_000,
            max_cost_micro_usd=5_000_000,
            max_wall_clock_seconds=1_200,
        ),
    )

    assert not result.accepted
    assert result.run.state is AgentRunState.BUDGET_EXCEEDED
    assert result.thread.comments == ()


def test_an_undeclared_extra_field_is_rejected_not_dropped() -> None:
    result = _propose(proposal=_proposal(editorial_note="ignore the rules"))

    assert not result.accepted
    assert result.thread.comments == ()


# --- authority --------------------------------------------------------------


def test_a_principal_without_engineer_cannot_start_a_run() -> None:
    service = _service(proposal=_proposal())

    with pytest.raises(ForbiddenError, match="ENGINEER"):
        service.propose(
            inputs=_inputs(),
            principal=_principal(roles=(Role.VIEWER,)),
            correlation_id="corr-1",
        )


def test_a_principal_from_another_tenant_cannot_propose_for_this_run() -> None:
    service = _service(proposal=_proposal())

    with pytest.raises(TenantScopeViolationError):
        service.propose(
            inputs=_inputs(),
            principal=Principal(
                subject="engineer-2", tenant_id=TenantId("tenant-2"), roles=(Role.ENGINEER,)
            ),
            correlation_id="corr-1",
        )


def test_the_run_records_the_starting_principal_as_the_actor() -> None:
    result = _propose(proposal=_proposal())

    assert result.run.actor == "engineer-1"
    assert result.comment is not None
    assert result.comment.reviewer_actor_id == "engineer-1"


# --- the helpers, called directly -------------------------------------------


def test_entry_ids_are_deterministic_over_the_same_manifest() -> None:
    assert _entry_ids() == _entry_ids(_manifest())


def test_validate_proposal_raises_modernize_contract_error() -> None:
    validate_proposal(TransformationPlanProposal.model_validate(_proposal()), inputs=_inputs())

    with pytest.raises(ModernizeContractError):
        validate_proposal(
            TransformationPlanProposal.model_validate(_proposal(manifest_hash="0" * 64)),
            inputs=_inputs(),
        )


def test_render_review_comment_marks_every_hunk_needing_attention() -> None:
    comment = render_review_comment(
        TransformationPlanProposal.model_validate(_proposal()),
        run_id=RUN_ID,
        actor_id="engineer-1",
        agent_id=AGENT_ID,
        agent_version=1,
        created_at=NOW,
    )

    assert "[reviewer attention]" in comment.body
    assert comment.body.count("[reviewer attention]") == 1


def test_the_expected_mapping_resolution_is_the_real_seeds_own() -> None:
    """Guards the fixture: if the shipped seed's aws:dynamodb -> gcp
    entry ever changes, rule 5's tests should fail loudly here rather
    than quietly agree with a stale constant."""

    from cairn_modules.mappings.resolver import resolve_mapping

    resolved = resolve_mapping(
        _mapping_release(), source_provider="aws", source_service="dynamodb", target_provider="gcp"
    )

    assert resolved.equivalence is Equivalence.APPROXIMATE
    assert resolved.caveat == EXPECTED_CAVEAT
    assert resolved.mapping_version == EXPECTED_MAPPING_VERSION
