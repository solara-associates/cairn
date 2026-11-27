"""R6-14: the modernize agent (design §3.3, ADR-019).

Proposes a transformation plan, runs the existing clean-room Rust engine
through its existing service, and explains every diff hunk so a reviewer
can accept or reject it on the merits.

**What the agent does not do.** `transformation.run` produces a manifest
and a unified diff in CAIRN's own store. It writes nothing to a customer
repository, and applying a diff anywhere is a separate Class C operation
behind the execution gate -- the agent has no tool for it, and the
toolset is asserted to contain none.

**The agent reports the engine's verdict; it does not grade it.** That
is the thread through all six rules: the manifest is the record, and
every field of every explanation is checked against the manifest and the
mapping release rather than taken on the model's word.

1. ``manifest_hash`` equals the hash of the manifest actually stored for
   ``run_id``. The check that stops a plausible explanation attaching to
   the wrong artefact.
2. Exactly one explanation per manifest entry: no entry unexplained, no
   explanation without an entry.
3. ``outcome`` equals the engine's own ``ManifestOutcome``.
4. ``unsupported[].engine_reason`` is the reason the engine gave,
   reproduced; a reason that is not the manifest's recorded one is a hard
   fail.
5. ``equivalence`` and ``caveat`` are what the mapping release actually
   resolves for that entry's rule, verbatim. A dropped caveat is a
   failure, and so is an ``APPROXIMATE`` described as ``EXACT``
   (R-MAP-01).
6. ``validation_summary`` is the existing static-validation result for
   the run, not a model summary of it.

**Two documented judgement calls**, both forced by types this unit does
not own and does not change:

*Entry identity.* ``ManifestEntry`` carries no id of its own, and design
§3.3's schema sketch wants an ``entry_id`` per explanation. Rather than
add a field to the manifest type (R6-11's, and persisted through
``TransformationRunRecord``), this module derives a deterministic id
from the entry's position and identity: ``<index>:<source_file_id>:
<rule_id>``. Deterministic over the same manifest, which is what
matters, since rule 1 already pins the manifest itself.

*Manifest hashing.* ``TransformationManifest`` has no ``content_hash``
property. ``manifest_hash`` here builds one over a canonical projection
of every field, the same canonical-JSON-then-sha256 construction
``TargetModel.content_hash`` and ``AgentRun.content_hash`` already use.
Declared here, once, rather than left to each caller.

**The approval point.** Explanations are posted onto the existing
transformation review thread as ``COMMENT``, attributed and marked
model-drafted. The thread's existing blocking semantics are unchanged
and this agent cannot clear a block: it never posts ``APPROVE`` or
``REQUEST_CHANGES``, so ``RunReviewThread.blocked`` reads exactly the
same before and after.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cairn_contracts.estate import Equivalence
from cairn_contracts.mapping.model import MappingRelease
from cairn_kernel.errors import ForbiddenError, MappingUnavailableError, TenantScopeViolationError
from cairn_kernel.errors import ValidationError as CairnValidationError
from cairn_kernel.evidence.hashing import payload_hash
from cairn_kernel.hex.ports import Clock, IdGenerator
from cairn_kernel.model.ports import StructuredOutputExpectation
from cairn_kernel.security import Principal, Role
from cairn_kits.loop import (
    AgentLoopPort,
    AgentRun,
    AgentRunContext,
    AgentRunState,
    AgentSpec,
    BudgetLedger,
    PromptRegistry,
    RunBudget,
    StepRecorder,
)
from cairn_kits.mcp import McpRegistry
from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError

from cairn_modules.mappings.resolver import resolve_mapping
from cairn_modules.transformation.engine import (
    MAPPING_RULE_IDS,
    ManifestEntry,
    ManifestOutcome,
    TransformationManifest,
)
from cairn_modules.transformation.review import (
    ReviewComment,
    ReviewDecisionKind,
    RunReviewThread,
    add_review_comment,
)
from cairn_modules.transformation.runs import TransformationRunRecord
from cairn_modules.transformation.validation import ValidationRun

AGENT_ID = "modernize-proposer"
AGENT_VERSION = 1

#: Design §3.3's table, exactly: five ``READ`` tools and the two
#: ``PROPOSE`` tools. Deliberately absent, and asserted absent: anything
#: that applies, publishes, approves or executes.
TOOLSET: tuple[str, ...] = (
    "transformation.list_source_files",
    "transformation.get_run",
    "transformation.get_diff",
    "transformation.get_manifest",
    "mappings.resolve",
    "transformation.run",
    "transformation.validate",
)

PROMPT_REFERENCES: tuple[tuple[str, int], ...] = (
    ("modernize-proposer/system", 1),
    ("modernize-proposer/scope-transformation", 1),
    ("modernize-proposer/explain-diff", 1),
)

#: Design §3's role rule: ``transformation.run``/``validate`` require
#: ``ENGINEER``, which is also the "at least ENGINEER to start any run"
#: floor.
REQUIRED_ROLE = Role.ENGINEER

#: Design §3.3's initial numbers -- bounds chosen to be safe, not
#: measurements (run sheet open question 2).
DEFAULT_BUDGET = RunBudget(
    max_steps=80,
    max_model_calls=40,
    max_total_tokens=600_000,
    max_cost_micro_usd=5_000_000,
    max_wall_clock_seconds=1_200,
)

PROPOSAL_SCHEMA = StructuredOutputExpectation(
    schema_name="transformation_plan_proposal.v1",
    schema={
        "type": "object",
        "required": [
            "plan_revision_id",
            "run_id",
            "manifest_hash",
            "scope",
            "explanations",
            "unsupported",
            "validation_summary",
        ],
        "properties": {
            "plan_revision_id": {"type": "string"},
            "run_id": {"type": "string"},
            "manifest_hash": {"type": "string"},
            "scope": {"type": "object"},
            "explanations": {"type": "array"},
            "unsupported": {"type": "array"},
            "validation_summary": {"type": "object"},
        },
    },
)


class ModernizeContractError(CairnValidationError):
    """A transformation plan proposal failed this agent's domain
    contract. Raised before anything is posted to a review thread, so a
    rejected proposal leaves no trace but the agent run's own recorded
    failure."""

    title = "Transformation plan proposal rejected"


def entry_id_for(index: int, entry: ManifestEntry) -> str:
    """This module's deterministic identity for one manifest entry --
    see the module docstring for why it is derived rather than carried
    on ``ManifestEntry``."""

    return f"{index}:{entry.source_file_id}:{entry.rule_id}"


def manifest_hash(manifest: TransformationManifest) -> str:
    """A stable fingerprint of ``manifest``'s full content, built the
    same way ``TargetModel.content_hash`` is."""

    return payload_hash(
        {
            "source_file_ids": list(manifest.source_file_ids),
            "entries": [
                {
                    "source_file_id": entry.source_file_id,
                    "rule_id": entry.rule_id,
                    "outcome": entry.outcome.value,
                    "reason": entry.reason,
                    "edits": [
                        {
                            "start_byte": edit.start_byte,
                            "end_byte": edit.end_byte,
                            "start_line": edit.start_line,
                            "end_line": edit.end_line,
                            "replacement": edit.replacement,
                        }
                        for edit in entry.edits
                    ],
                    "detector_version": entry.detector_version,
                    "pattern_version": entry.pattern_version,
                    "patcher_version": entry.patcher_version,
                    "mapping_release_version": entry.mapping_release_version,
                }
                for entry in manifest.entries
            ],
        }
    )


class ExcludedPath(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    reason: str


class ProposalScope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    file_paths: tuple[str, ...]
    excluded: tuple[ExcludedPath, ...] = ()


class HunkExplanation(BaseModel):
    """One manifest entry, explained. ``outcome``, ``mapping_version``,
    ``equivalence`` and ``caveat`` are all reproduced from the record,
    never the model's own judgement -- see this module's rules 3 and 5."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entry_id: str
    file_path: str
    hunk_ref: str
    outcome: ManifestOutcome
    mapping_version: str | None = None
    equivalence: Equivalence | None = None
    caveat: str | None = None
    explanation: str
    reviewer_attention: bool = False


class UnsupportedEntry(BaseModel):
    """One ``UNSUPPORTED`` entry's engine reason, reproduced, plus the
    manual step the agent suggests instead. The suggestion is the
    agent's own; the reason is not."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entry_id: str
    engine_reason: str
    suggested_manual_step: str


class TransformationPlanProposal(BaseModel):
    """Design §3.3's ``TransformationPlanProposal``, as a validated
    value."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_revision_id: str
    run_id: str
    manifest_hash: str
    scope: ProposalScope
    explanations: tuple[HunkExplanation, ...]
    unsupported: tuple[UnsupportedEntry, ...]
    validation_summary: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ModernizeInputs:
    """Everything this agent's domain contract is checked against.

    ``run_record`` is the stored ``transformation_run`` row (its
    ``manifest`` is the record rule 1 pins); ``validation_run`` is the
    existing static-validation result for that run; ``review_thread`` is
    the run's existing review thread, which this agent appends to and
    never clears.
    """

    tenant_id: str
    project_id: str
    plan_revision_id: str
    run_record: TransformationRunRecord
    validation_run: ValidationRun
    review_thread: RunReviewThread
    mapping_release: MappingRelease | None = None
    source_file_paths: tuple[str, ...] = ()


def build_spec(
    *,
    prompt_registry: PromptRegistry,
    mcp_registry: McpRegistry,
    tool_roles: Mapping[str, Role],
    budget: RunBudget = DEFAULT_BUDGET,
) -> AgentSpec:
    return AgentSpec.build(
        agent_id=AGENT_ID,
        version=AGENT_VERSION,
        toolset=TOOLSET,
        required_role=REQUIRED_ROLE,
        prompt_references=PROMPT_REFERENCES,
        budget=budget,
        output_schema=PROPOSAL_SCHEMA,
        prompt_registry=prompt_registry,
        mcp_registry=mcp_registry,
        tool_roles=tool_roles,
    )


def validation_summary_of(validation_run: ValidationRun) -> dict[str, Any]:
    """The canonical projection of ``validation_run`` a proposal must
    carry (rule 6). Computed here so a proposal is compared against the
    real validation result rather than a model's prose about it."""

    return {
        "run_id": validation_run.run_id,
        "approved": validation_run.approved,
        "results": [
            {
                "check_id": result.check_id,
                "passed": result.passed,
                "reason": result.reason,
            }
            for result in validation_run.results
        ],
    }


# --- rule 1: the proposal explains the manifest on record -------------------


def _check_manifest_hash(
    proposal: TransformationPlanProposal, inputs: ModernizeInputs
) -> TransformationManifest:
    if proposal.run_id != inputs.run_record.run_id:
        raise ModernizeContractError(
            f"proposal names transformation run {proposal.run_id!r} but was produced"
            f" for {inputs.run_record.run_id!r}"
        )
    if proposal.plan_revision_id != inputs.plan_revision_id:
        raise ModernizeContractError(
            f"proposal names plan revision {proposal.plan_revision_id!r} but was"
            f" produced for {inputs.plan_revision_id!r}"
        )
    manifest = inputs.run_record.manifest
    actual = manifest_hash(manifest)
    if proposal.manifest_hash != actual:
        raise ModernizeContractError(
            f"proposal declares manifest_hash {proposal.manifest_hash!r}, but the"
            f" manifest stored for run {inputs.run_record.run_id!r} hashes to"
            f" {actual!r}: the agent may not explain a diff that is not the one on"
            " record"
        )
    return manifest


# --- rule 2: one explanation per entry, no more, no fewer -------------------


def _entries_by_id(manifest: TransformationManifest) -> dict[str, ManifestEntry]:
    return {entry_id_for(index, entry): entry for index, entry in enumerate(manifest.entries)}


def _check_explanation_coverage(
    proposal: TransformationPlanProposal, entries: dict[str, ManifestEntry]
) -> None:
    explained = [explanation.entry_id for explanation in proposal.explanations]
    duplicates = sorted({eid for eid in explained if explained.count(eid) > 1})
    if duplicates:
        raise ModernizeContractError(
            f"manifest entr(ies) {duplicates} are explained more than once; exactly one"
            " explanation per entry"
        )
    orphans = sorted(set(explained) - set(entries))
    if orphans:
        raise ModernizeContractError(
            f"explanation(s) {orphans} name no entry in this run's manifest: an"
            " explanation without an entry is rejected"
        )
    unexplained = sorted(set(entries) - set(explained))
    if unexplained:
        raise ModernizeContractError(
            f"manifest entr(ies) {unexplained} have no explanation: a reviewer is never"
            " shown a diff hunk nobody explained"
        )


# --- rule 3: the engine's outcome, reproduced -------------------------------


def _check_outcomes(
    proposal: TransformationPlanProposal, entries: dict[str, ManifestEntry]
) -> None:
    for explanation in proposal.explanations:
        entry = entries[explanation.entry_id]
        if explanation.outcome is not entry.outcome:
            raise ModernizeContractError(
                f"explanation {explanation.entry_id!r} says the outcome is"
                f" {explanation.outcome.value}, but the engine recorded"
                f" {entry.outcome.value}: this agent reports the engine's verdict, it"
                " does not grade it"
            )
        if explanation.file_path != entry.source_file_id:
            raise ModernizeContractError(
                f"explanation {explanation.entry_id!r} names file"
                f" {explanation.file_path!r}, but that entry is against"
                f" {entry.source_file_id!r}"
            )


# --- rule 4: the engine's reason, reproduced --------------------------------


def _check_unsupported(
    proposal: TransformationPlanProposal, entries: dict[str, ManifestEntry]
) -> None:
    unsupported_ids = {
        entry_id
        for entry_id, entry in entries.items()
        if entry.outcome is ManifestOutcome.UNSUPPORTED
    }
    declared = [item.entry_id for item in proposal.unsupported]
    duplicates = sorted({eid for eid in declared if declared.count(eid) > 1})
    if duplicates:
        raise ModernizeContractError(f"unsupported entr(ies) {duplicates} are listed twice")
    extras = sorted(set(declared) - unsupported_ids)
    if extras:
        raise ModernizeContractError(
            f"unsupported lists {extras}, which the engine did not record as UNSUPPORTED"
        )
    missing = sorted(unsupported_ids - set(declared))
    if missing:
        raise ModernizeContractError(
            f"the engine recorded {missing} as UNSUPPORTED, but the proposal's"
            " unsupported list omits them"
        )
    for item in proposal.unsupported:
        entry = entries[item.entry_id]
        if item.engine_reason != entry.reason:
            raise ModernizeContractError(
                f"unsupported entry {item.entry_id!r} gives engine_reason"
                f" {item.engine_reason!r}, but the engine recorded {entry.reason!r}: the"
                " reason is the engine's, reproduced, never invented"
            )
        if not item.suggested_manual_step.strip():
            raise ModernizeContractError(
                f"unsupported entry {item.entry_id!r} suggests no manual step; an"
                " unsupported change with no next step tells a reviewer nothing"
            )


# --- rule 5: the mapping resolution, verbatim (R-MAP-01) --------------------


def _expected_resolution(
    entry: ManifestEntry, mapping_release: MappingRelease | None
) -> tuple[str | None, Equivalence | None, str | None]:
    """What the mapping release actually resolves for this entry's rule:
    ``(mapping_version, equivalence, caveat)``.

    ``(None, None, None)`` when the entry's rule needs no mapping lookup
    at all, when no release was supplied, or when the resolver itself
    says the mapping is unavailable -- in all three cases there is no
    equivalence judgement to reproduce, and inventing one is exactly
    what R-MAP-01 forbids. ``cairn_modules.transformation.engine`` takes
    the same three-way view of the same lookup.
    """

    lookup = MAPPING_RULE_IDS.get(entry.rule_id)
    if lookup is None or mapping_release is None:
        return None, None, None
    source_provider, source_service, target_provider = lookup
    try:
        resolved = resolve_mapping(
            mapping_release,
            source_provider=source_provider,
            source_service=source_service,
            target_provider=target_provider,
        )
    except MappingUnavailableError:
        return mapping_release.version, None, None
    return resolved.mapping_version, resolved.equivalence, resolved.caveat


def _check_mapping_fidelity(
    proposal: TransformationPlanProposal,
    entries: dict[str, ManifestEntry],
    inputs: ModernizeInputs,
) -> None:
    for explanation in proposal.explanations:
        entry = entries[explanation.entry_id]
        version, equivalence, caveat = _expected_resolution(entry, inputs.mapping_release)
        if explanation.mapping_version != version:
            raise ModernizeContractError(
                f"explanation {explanation.entry_id!r} states mapping_version"
                f" {explanation.mapping_version!r}, but this entry resolves against"
                f" {version!r}"
            )
        if explanation.equivalence is not equivalence:
            raise ModernizeContractError(
                f"explanation {explanation.entry_id!r} states equivalence"
                f" {explanation.equivalence}, but the mapping release resolves"
                f" {equivalence}: an APPROXIMATE equivalence may not be described as"
                " exact (R-MAP-01)"
            )
        if explanation.caveat != caveat:
            raise ModernizeContractError(
                f"explanation {explanation.entry_id!r} states caveat"
                f" {explanation.caveat!r}, but the mapping release records"
                f" {caveat!r}: a caveat is copied verbatim and may not be dropped"
                " (R-MAP-01)"
            )


# --- rule 6: the real validation result -------------------------------------


def _check_validation_summary(
    proposal: TransformationPlanProposal, inputs: ModernizeInputs
) -> None:
    expected = validation_summary_of(inputs.validation_run)
    if proposal.validation_summary != expected:
        raise ModernizeContractError(
            "validation_summary is not this run's static-validation result; it must be"
            " the existing result, not a model summary of it"
        )


def _check_scope(proposal: TransformationPlanProposal, inputs: ModernizeInputs) -> None:
    manifest_files = set(inputs.run_record.manifest.source_file_ids)
    declared = set(proposal.scope.file_paths)
    if declared != manifest_files:
        raise ModernizeContractError(
            f"scope.file_paths {sorted(declared)} is not the set of files this run's"
            f" manifest actually covers, {sorted(manifest_files)}"
        )
    for excluded in proposal.scope.excluded:
        if excluded.path in manifest_files:
            raise ModernizeContractError(
                f"scope excludes {excluded.path!r}, which the manifest does cover"
            )
        if inputs.source_file_paths and excluded.path not in inputs.source_file_paths:
            raise ModernizeContractError(
                f"scope excludes {excluded.path!r}, which is not a source file in this project"
            )
        if not excluded.reason.strip():
            raise ModernizeContractError(
                f"scope excludes {excluded.path!r} with no reason; an unexplained"
                " exclusion is how scope quietly shrinks"
            )


def validate_proposal(proposal: TransformationPlanProposal, *, inputs: ModernizeInputs) -> None:
    """Design §3.3's six validation rules, in order, every one a hard
    fail. Raises ``ModernizeContractError``; the caller posts nothing
    when it does."""

    manifest = _check_manifest_hash(proposal, inputs)
    entries = _entries_by_id(manifest)
    _check_scope(proposal, inputs)
    _check_explanation_coverage(proposal, entries)
    _check_outcomes(proposal, entries)
    _check_unsupported(proposal, entries)
    _check_mapping_fidelity(proposal, entries, inputs)
    _check_validation_summary(proposal, inputs)


def render_review_comment(
    proposal: TransformationPlanProposal,
    *,
    run_id: str,
    actor_id: str,
    agent_id: str,
    agent_version: int,
    created_at: datetime,
) -> ReviewComment:
    """One ``COMMENT`` carrying the proposal's explanations, attributed
    and marked model-drafted.

    ``ReviewDecisionKind.COMMENT`` is not a choice this agent gets to
    make differently: a ``COMMENT`` carries no decision of its own, so
    it can neither clear a standing ``REQUEST_CHANGES`` nor stand in for
    an ``APPROVE`` (``RunReviewThread.blocked``'s own rule). That is the
    whole reason this is the only kind it ever posts.
    """

    header = (
        f"Model-drafted by agent {agent_id} v{agent_version}, run {run_id}."
        " Unapproved: a human reviewer decides on each hunk."
    )
    lines = [header, ""]
    for explanation in proposal.explanations:
        attention = " [reviewer attention]" if explanation.reviewer_attention else ""
        caveat = f" Caveat: {explanation.caveat}" if explanation.caveat else ""
        equivalence = (
            f" Equivalence: {explanation.equivalence.value}."
            if explanation.equivalence is not None
            else ""
        )
        lines.append(
            f"- {explanation.file_path} {explanation.hunk_ref}"
            f" ({explanation.outcome.value}){attention}:"
            f" {explanation.explanation}{equivalence}{caveat}"
        )
    for item in proposal.unsupported:
        lines.append(
            f"- unsupported {item.entry_id}: engine said {item.engine_reason!r}."
            f" Suggested manual step: {item.suggested_manual_step}"
        )
    return ReviewComment(
        run_id=run_id,
        reviewer_actor_id=actor_id,
        decision=ReviewDecisionKind.COMMENT,
        body="\n".join(lines),
        created_at=created_at,
    )


@dataclass(frozen=True, slots=True)
class ModernizeProposerResult:
    """What one run of this agent produced.

    ``thread`` is the review thread after the agent's comment was
    appended, and is the input thread unchanged when the proposal was
    rejected.
    """

    run: AgentRun
    thread: RunReviewThread
    proposal: TransformationPlanProposal | None = None
    comment: ReviewComment | None = None
    rejection: str | None = None

    @property
    def accepted(self) -> bool:
        return self.proposal is not None


class ModernizeProposerService:
    """The application service ``apps/api``/``apps/worker`` call. No
    SDK, no framework type, no SQL (ADR-019 §2)."""

    def __init__(
        self,
        *,
        agent_loop: AgentLoopPort,
        prompt_registry: PromptRegistry,
        mcp_registry: McpRegistry,
        tool_roles: Mapping[str, Role],
        step_recorder: StepRecorder,
        clock: Clock,
        id_generator: IdGenerator,
        budget_ledger: BudgetLedger | None = None,
        budget: RunBudget = DEFAULT_BUDGET,
    ) -> None:
        self._agent_loop = agent_loop
        self._prompt_registry = prompt_registry
        self._mcp_registry = mcp_registry
        self._tool_roles = dict(tool_roles)
        self._step_recorder = step_recorder
        self._clock = clock
        self._ids = id_generator
        self._budget_ledger = budget_ledger if budget_ledger is not None else BudgetLedger()
        self._budget = budget

    def propose(
        self,
        *,
        inputs: ModernizeInputs,
        principal: Principal,
        correlation_id: str,
        agent_run_id: str | None = None,
    ) -> ModernizeProposerResult:
        """Run this agent over ``inputs`` and return what it produced.

        ``principal`` is required and never defaulted (A7.actor): it is
        the run's actor and the author the review comment is attributed
        to.
        """

        if inputs.tenant_id != principal.tenant_id.value:
            raise TenantScopeViolationError(
                f"transformation run {inputs.run_record.run_id} belongs to tenant"
                f" {inputs.tenant_id!r}, not the caller's"
                f" {principal.tenant_id.value!r}"
            )
        if not principal.has_role(REQUIRED_ROLE):
            raise ForbiddenError(
                f"agent {AGENT_ID!r} requires role {REQUIRED_ROLE.value!r}, principal"
                f" {principal.subject!r} holds {principal.role_values()!r}"
            )

        spec = build_spec(
            prompt_registry=self._prompt_registry,
            mcp_registry=self._mcp_registry,
            tool_roles=self._tool_roles,
            budget=self._budget,
        )
        run_id = agent_run_id or self._ids.new_id()
        context = AgentRunContext(
            run_id=run_id,
            tenant_id=inputs.tenant_id,
            actor=principal.subject,
            correlation_id=correlation_id,
            budget_ledger=self._budget_ledger,
            step_recorder=self._step_recorder,
            project_id=inputs.project_id,
        )
        agent_run = self._agent_loop.run(
            spec,
            {
                "tenant_id": inputs.tenant_id,
                "project_id": inputs.project_id,
                "plan_revision_id": inputs.plan_revision_id,
                "run_id": inputs.run_record.run_id,
            },
            context=context,
        )

        if agent_run.state is not AgentRunState.COMPLETED or agent_run.proposal is None:
            return ModernizeProposerResult(
                run=agent_run,
                thread=inputs.review_thread,
                rejection=agent_run.terminal_reason or f"agent run ended {agent_run.state.value}",
            )

        try:
            proposal = TransformationPlanProposal.model_validate(dict(agent_run.proposal))
        except PydanticValidationError as exc:
            return ModernizeProposerResult(
                run=agent_run, thread=inputs.review_thread, rejection=str(exc)
            )

        try:
            validate_proposal(proposal, inputs=inputs)
        except CairnValidationError as exc:
            return ModernizeProposerResult(
                run=agent_run, thread=inputs.review_thread, rejection=str(exc)
            )

        comment = render_review_comment(
            proposal,
            run_id=inputs.run_record.run_id,
            actor_id=principal.subject,
            agent_id=spec.agent_id,
            agent_version=spec.version,
            created_at=self._clock.now(),
        )
        thread = add_review_comment(inputs.review_thread, comment)
        return ModernizeProposerResult(
            run=agent_run, thread=thread, proposal=proposal, comment=comment
        )


__all__ = [
    "AGENT_ID",
    "AGENT_VERSION",
    "DEFAULT_BUDGET",
    "PROMPT_REFERENCES",
    "PROPOSAL_SCHEMA",
    "REQUIRED_ROLE",
    "TOOLSET",
    "ExcludedPath",
    "HunkExplanation",
    "ModernizeContractError",
    "ModernizeInputs",
    "ModernizeProposerResult",
    "ModernizeProposerService",
    "ProposalScope",
    "TransformationPlanProposal",
    "UnsupportedEntry",
    "build_spec",
    "entry_id_for",
    "manifest_hash",
    "render_review_comment",
    "validate_proposal",
    "validation_summary_of",
]
