"""R6-12: the assessment agent (design §3.1, ADR-019).

Explains a finished assessment in a reviewer's language: why each
workload got the 6R disposition it got, what looks wrong in the data,
and a draft summary a human will edit. It explains a decision the
deterministic classifier already made; it does not re-decide one.

The shape, in order: construct the ``AgentSpec``, invoke
``AgentLoopPort``, read the run's proposal (R6-11a: present only if it
satisfied ``NARRATIVE_SCHEMA``), validate it against this agent's five
domain-contract rules, persist it as a **draft** marked model-drafted,
and stop. Nothing here approves, publishes or executes.

**Failure is terminal, not a retry** (design §3). A narrative that
fails any of the five rules is not persisted, not displayed and not
retried: the service returns a result carrying the rejection, the agent
run's own terminal state stands, and ``NarrativeDraft`` never comes into
existence. A half-valid narrative in front of an approver is worse than
none.

**The five rules**, all hard fails, with rule 2 the headline one:

1. Every ``workload_id`` in ``dispositions`` exists in the run's stored
   decisions; no extras, no omissions.
2. Every ``disposition`` equals the stored
   ``DispositionDecision.disposition`` exactly. A mismatch means the
   model invented a disposition.
3. Every explanation and every anomaly cites at least one ``fact_ref``
   that resolves to a real fact in the run (``agents.facts``).
4. ``confidence_stated`` equals the stored decision's ``confidence``,
   and ``not_exact_refs`` reproduces exactly those cited facts that are
   approximate, unavailable or unverified -- dropping one is describing
   an approximate figure as exact (R-MAP-01).
5. ``model_version`` and ``mapping_version`` equal the run's own
   (R-VER-01).

**Two documented judgement calls.**

*Rule 4's "band".* Design §3.1 says ``confidence_stated`` must match the
stored "``confidence`` band", but no band type exists in this codebase:
``Confidence`` is a float in ``[0, 1]``. Rather than invent a band
taxonomy here, where it would be this module's private opinion, the
rule is equality on the number the decision actually recorded. That is
the strictest reading of the design's own "reproduced, never
paraphrased into certainty", and if a band type is ever added it
tightens to it with no change of meaning.

*Rule 4's exactness check.* Design §3.1 says the text "may not describe
an approximate or unavailable figure as exact". This is enforced
structurally, on a required ``not_exact_refs`` field the narrative must
fill in correctly, and never by scanning the prose for words like
"exactly" -- ``cairn_modules.design.diagram`` set that precedent, and a
check a model can get past by rewording is not a check.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from cairn_contracts.estate import Disposition, DispositionDecision
from cairn_kernel.errors import ForbiddenError, NotFoundError, TenantScopeViolationError
from cairn_kernel.errors import ValidationError as CairnValidationError
from cairn_kernel.hex.ports import Clock, IdGenerator
from cairn_kernel.hex.primitives import Port
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

from cairn_modules.agents.facts import not_exact_refs, resolve_fact_ref
from cairn_modules.approvals.model import (
    ApprovalRecord,
    ApprovalState,
    check_separation_of_duties,
)
from cairn_modules.assessment import AssessmentRun, AssessmentService

AGENT_ID = "assessment-explainer"
AGENT_VERSION = 1

#: Design §3.1's table, exactly: ten tools, every one ``READ``.
#: ``AgentSpec.build`` resolves each against a live ``McpRegistry`` and
#: refuses anything that is not ``READ``/``PROPOSE``, so this list being
#: right is checked, not asserted.
TOOLSET: tuple[str, ...] = (
    "assessment.get_run",
    "assessment.get_results",
    "assessment.coverage_report",
    "assessment.get_decision",
    "estate.list_workloads",
    "estate.get_workload",
    "mappings.resolve",
    "posture.get_control",
    "finops.get_baseline",
    "finops.get_tco",
)

PROMPT_REFERENCES: tuple[tuple[str, int], ...] = (
    ("assessment-explainer/system", 1),
    ("assessment-explainer/explain-disposition", 1),
    ("assessment-explainer/detect-anomalies", 1),
    ("assessment-explainer/draft-summary", 1),
)

#: Design §3's role rule: ``required_role`` must dominate every role the
#: toolset needs (here ``posture.get_control``'s ``AUDITOR`` is the
#: highest), and "starting any agent run requires at least ENGINEER,
#: because a run spends real model budget and VIEWER is a read-only
#: role". ``ENGINEER`` satisfies both; ``AgentSpec.build`` checks the
#: domination half.
REQUIRED_ROLE = Role.ENGINEER

#: Design §3.1's initial numbers. Bounds chosen to be safe, not
#: measurements -- the run sheet's own open question 2 says so, and the
#: first real runs will move them.
DEFAULT_BUDGET = RunBudget(
    max_steps=40,
    max_model_calls=20,
    max_total_tokens=300_000,
    max_cost_micro_usd=2_000_000,
    max_wall_clock_seconds=600,
)

NARRATIVE_SCHEMA = StructuredOutputExpectation(
    schema_name="assessment_narrative.v1",
    schema={
        "type": "object",
        "required": [
            "run_id",
            "model_version",
            "mapping_version",
            "dispositions",
            "anomalies",
            "summary_draft",
        ],
        "properties": {
            "run_id": {"type": "string"},
            "model_version": {"type": "string"},
            "mapping_version": {"type": "string"},
            "dispositions": {"type": "array"},
            "anomalies": {"type": "array"},
            "summary_draft": {"type": "string"},
        },
    },
)


class NarrativeContractError(CairnValidationError):
    """A narrative failed this agent's domain contract. Raised before
    anything is persisted, so a rejected narrative leaves no trace but
    the agent run's own recorded failure."""

    title = "Assessment narrative rejected"


class DispositionExplanation(BaseModel):
    """One workload's disposition, explained. ``disposition`` is the
    stored decision's, reproduced; ``confidence_stated`` is the stored
    decision's ``confidence``, reproduced; ``not_exact_refs`` names
    every cited fact that is not an established one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workload_id: str
    disposition: Disposition
    explanation: str
    fact_refs: tuple[str, ...]
    confidence_stated: float
    not_exact_refs: tuple[str, ...] = ()


class NarrativeAnomaly(BaseModel):
    """Something that looks wrong in the run's data, cited."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    subject_ref: str
    statement: str
    fact_refs: tuple[str, ...]
    not_exact_refs: tuple[str, ...] = ()


class AssessmentNarrative(BaseModel):
    """Design §3.1's ``AssessmentNarrative``, as a validated value.

    ``extra="forbid"`` throughout: a field this agent does not declare
    is not a field a reviewer will see, so accepting one silently would
    be accepting unreviewed model output into the product.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    model_version: str
    mapping_version: str
    dispositions: tuple[DispositionExplanation, ...]
    anomalies: tuple[NarrativeAnomaly, ...]
    summary_draft: str


@dataclass(frozen=True, slots=True)
class NarrativeDraft:
    """A persisted narrative draft, attached to one assessment run.

    ``model_drafted`` is ``True`` and there is no code path that sets it
    otherwise: this type exists only as the output of an agent run, so a
    field that could say "a human wrote this" would be a field that can
    lie. Every surface that displays a draft reads it (design §3.1:
    "marked as model-drafted wherever it is displayed").

    Deliberately absent: any approval state. A draft is not an approval
    and carries no field that could be mistaken for one; including it in
    an evidence package goes through ``publish_narrative_to_evidence``
    and the existing ``ApprovalRecord``, never a flag set here.
    """

    draft_id: str
    tenant_id: str
    project_id: str
    assessment_run_id: str
    agent_id: str
    agent_version: int
    agent_run_id: str
    proposed_by: str
    narrative: AssessmentNarrative
    created_at: datetime
    model_drafted: bool = True


class AssessmentNarrativeRepository(Port, Protocol):
    """Durable storage for narrative drafts. R6-15 owns the ``agent_run``
    tables; a narrative draft is this agent's own artifact, so it gets
    its own port here rather than being smuggled into that unit's
    schema."""

    def save_draft(self, draft: NarrativeDraft) -> None: ...

    def get_draft(self, draft_id: str) -> NarrativeDraft: ...

    def drafts_for_run(self, assessment_run_id: str) -> tuple[NarrativeDraft, ...]: ...


class InMemoryAssessmentNarrativeRepository:
    """Reference ``AssessmentNarrativeRepository``: a dict keyed by
    ``draft_id``, the same shape ``InMemoryCheckpointStore`` already
    uses."""

    def __init__(self) -> None:
        self._drafts: dict[str, NarrativeDraft] = {}

    def save_draft(self, draft: NarrativeDraft) -> None:
        self._drafts[draft.draft_id] = draft

    def get_draft(self, draft_id: str) -> NarrativeDraft:
        try:
            return self._drafts[draft_id]
        except KeyError:
            raise NotFoundError(f"narrative draft {draft_id} not found") from None

    def drafts_for_run(self, assessment_run_id: str) -> tuple[NarrativeDraft, ...]:
        return tuple(
            draft for draft in self._drafts.values() if draft.assessment_run_id == assessment_run_id
        )


def build_spec(
    *,
    prompt_registry: PromptRegistry,
    mcp_registry: McpRegistry,
    tool_roles: Mapping[str, Role],
    budget: RunBudget = DEFAULT_BUDGET,
) -> AgentSpec:
    """This agent's ``AgentSpec``. ``mcp_registry``/``tool_roles`` come
    from the composition root (``cairn_modules`` cannot import
    ``cairn_mcp_gateway``, so the registry is passed in, never
    reached for)."""

    return AgentSpec.build(
        agent_id=AGENT_ID,
        version=AGENT_VERSION,
        toolset=TOOLSET,
        required_role=REQUIRED_ROLE,
        prompt_references=PROMPT_REFERENCES,
        budget=budget,
        output_schema=NARRATIVE_SCHEMA,
        prompt_registry=prompt_registry,
        mcp_registry=mcp_registry,
        tool_roles=tool_roles,
    )


def _stored_decisions(run: AssessmentRun) -> dict[str, DispositionDecision]:
    decisions: Sequence[DispositionDecision] = run.context.artifacts.get(
        "disposition_decisions", ()
    )
    return {decision.workload_id: decision for decision in decisions}


def _check_coverage(narrative: AssessmentNarrative, stored: dict[str, DispositionDecision]) -> None:
    explained = [entry.workload_id for entry in narrative.dispositions]
    duplicates = sorted({wid for wid in explained if explained.count(wid) > 1})
    if duplicates:
        raise NarrativeContractError(f"narrative explains workload(s) {duplicates} more than once")
    extras = sorted(set(explained) - set(stored))
    if extras:
        raise NarrativeContractError(
            f"narrative explains workload(s) {extras} that have no stored disposition"
            " decision in this run"
        )
    omissions = sorted(set(stored) - set(explained))
    if omissions:
        raise NarrativeContractError(
            f"narrative omits workload(s) {omissions} that the run decided on"
        )


def _check_dispositions(
    narrative: AssessmentNarrative, stored: dict[str, DispositionDecision]
) -> None:
    """Design §3.1's rule 2, "the single most important check on this
    agent": the agent explains a decision the deterministic 6R
    classifier already made, so a disposition that differs from the
    stored one means the model invented it."""

    for entry in narrative.dispositions:
        decision = stored[entry.workload_id]
        if entry.disposition is not decision.disposition:
            raise NarrativeContractError(
                f"narrative says workload {entry.workload_id!r} is"
                f" {entry.disposition.value}, but the stored disposition decision"
                f" {decision.decision_id!r} says {decision.disposition.value}: this agent"
                " explains the classifier's decision, it does not re-decide it"
            )


def _check_citations(narrative: AssessmentNarrative, run: AssessmentRun) -> None:
    for entry in narrative.dispositions:
        if not entry.fact_refs:
            raise NarrativeContractError(
                f"explanation for workload {entry.workload_id!r} cites no fact; an"
                " uncited explanation is rejected"
            )
        for ref in entry.fact_refs:
            resolve_fact_ref(ref, run)
    for anomaly in narrative.anomalies:
        if not anomaly.fact_refs:
            raise NarrativeContractError(
                f"anomaly {anomaly.kind!r} on {anomaly.subject_ref!r} cites no fact; an"
                " uncited claim is rejected"
            )
        for ref in anomaly.fact_refs:
            resolve_fact_ref(ref, run)


def _check_confidence_and_exactness(
    narrative: AssessmentNarrative, run: AssessmentRun, stored: dict[str, DispositionDecision]
) -> None:
    for entry in narrative.dispositions:
        decision = stored[entry.workload_id]
        if entry.confidence_stated != decision.confidence:
            raise NarrativeContractError(
                f"explanation for workload {entry.workload_id!r} states confidence"
                f" {entry.confidence_stated}, but decision {decision.decision_id!r}"
                f" recorded {decision.confidence}: a confidence is reproduced, never"
                " paraphrased"
            )
        _check_exactness(
            declared=entry.not_exact_refs,
            cited=entry.fact_refs,
            run=run,
            subject=f"explanation for workload {entry.workload_id!r}",
        )
    for anomaly in narrative.anomalies:
        _check_exactness(
            declared=anomaly.not_exact_refs,
            cited=anomaly.fact_refs,
            run=run,
            subject=f"anomaly {anomaly.kind!r} on {anomaly.subject_ref!r}",
        )


def _check_exactness(
    *, declared: tuple[str, ...], cited: tuple[str, ...], run: AssessmentRun, subject: str
) -> None:
    """R-MAP-01, structurally: the facts the narrative says are not
    established must be exactly the cited facts that are not
    established. Dropping one is presenting an approximate or
    unverified figure as exact; inventing one is hedging a fact the run
    actually observed, which misleads in the other direction."""

    actual = set(not_exact_refs(cited, run))
    stated = set(declared)
    dropped = sorted(actual - stated)
    if dropped:
        raise NarrativeContractError(
            f"{subject} cites {dropped}, which are approximate, unavailable or"
            " unverified, without reproducing that: an approximate figure may not be"
            " described as exact (R-MAP-01)"
        )
    invented = sorted(stated - actual)
    if invented:
        raise NarrativeContractError(
            f"{subject} calls {invented} approximate, but the run records them as established facts"
        )


def _check_versions(narrative: AssessmentNarrative, stored: dict[str, DispositionDecision]) -> None:
    """R-VER-01: the narrative cannot silently describe a different
    release's results. The run's own versions are the ones its stored
    decisions carry."""

    model_versions = {decision.model_version for decision in stored.values()}
    mapping_versions = {decision.mapping_version for decision in stored.values()}
    if len(model_versions) != 1 or len(mapping_versions) != 1:
        raise NarrativeContractError(
            "the run's stored decisions do not agree on one model/mapping version, so"
            " no narrative can claim the run's own: "
            f"model={sorted(model_versions)}, mapping={sorted(mapping_versions)}"
        )
    run_model_version = next(iter(model_versions))
    run_mapping_version = next(iter(mapping_versions))
    if narrative.model_version != run_model_version:
        raise NarrativeContractError(
            f"narrative states model_version {narrative.model_version!r}, but the run's"
            f" decisions were made with {run_model_version!r}"
        )
    if narrative.mapping_version != run_mapping_version:
        raise NarrativeContractError(
            f"narrative states mapping_version {narrative.mapping_version!r}, but the"
            f" run's decisions were made with {run_mapping_version!r}"
        )


def validate_narrative(narrative: AssessmentNarrative, *, run: AssessmentRun) -> None:
    """Design §3.1's five validation rules, in order, every one a hard
    fail. Raises ``NarrativeContractError``; the caller persists nothing
    when it does."""

    if narrative.run_id != run.run_id:
        raise NarrativeContractError(
            f"narrative names run {narrative.run_id!r} but was produced for {run.run_id!r}"
        )
    stored = _stored_decisions(run)
    if not stored:
        raise NarrativeContractError(
            f"run {run.run_id} has no stored disposition decisions, so there is nothing"
            " for a narrative to explain"
        )
    _check_coverage(narrative, stored)
    _check_dispositions(narrative, stored)
    _check_citations(narrative, run)
    _check_confidence_and_exactness(narrative, run, stored)
    _check_versions(narrative, stored)


def publish_narrative_to_evidence(
    draft: NarrativeDraft, *, approval: ApprovalRecord | None
) -> NarrativeDraft:
    """Design §3.1's approval point: including a draft in a signed
    evidence package requires a human accept through the existing
    approval console. Nothing is published on the agent's authority.

    Raises ``ForbiddenError`` when ``approval`` is absent or is not an
    ``APPROVED`` record bound to this draft, and
    ``SeparationOfDutiesError`` (via ``check_separation_of_duties``)
    when the approver is the principal that started the run. Returns the
    draft unchanged on success -- publishing is the caller's write, and
    this function's whole job is to refuse it when it is unapproved.
    """

    if approval is None:
        raise ForbiddenError(
            f"narrative draft {draft.draft_id} is model-drafted and unapproved; it"
            " cannot be published into an evidence package without a human approval"
        )
    if approval.state is not ApprovalState.APPROVED:
        raise ForbiddenError(
            f"approval {approval.approval_id} is {approval.state.value}, not APPROVED;"
            f" narrative draft {draft.draft_id} cannot be published"
        )
    if approval.subject_id != draft.draft_id:
        raise ForbiddenError(
            f"approval {approval.approval_id} names subject {approval.subject_id!r},"
            f" not narrative draft {draft.draft_id!r}"
        )
    if approval.approver_actor_id is None:
        raise ForbiddenError(
            f"approval {approval.approval_id} records no approver; a narrative is"
            " published on a human's accept, never on an empty one"
        )
    check_separation_of_duties(draft.proposed_by, approval.approver_actor_id)
    return draft


@dataclass(frozen=True, slots=True)
class AssessmentExplainerResult:
    """What one run of this agent produced.

    ``draft`` is not ``None`` if and only if the agent run completed
    with a proposal that passed all five rules -- the same
    "validated or absent" discipline ``AgentRun.proposal`` itself has
    (R6-11a), one layer up.
    """

    run: AgentRun
    draft: NarrativeDraft | None = None
    rejection: str | None = None

    @property
    def accepted(self) -> bool:
        return self.draft is not None


class AssessmentExplainerService:
    """The application service ``apps/api``/``apps/worker`` call.

    No SDK, no framework type, no SQL (ADR-019 §2): an
    ``AgentLoopPort``, the assessment module's own service, a repository
    port, and the registries ``AgentSpec.build`` needs.
    """

    def __init__(
        self,
        *,
        agent_loop: AgentLoopPort,
        assessment_service: AssessmentService,
        narrative_repository: AssessmentNarrativeRepository,
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
        self._assessment_service = assessment_service
        self._narratives = narrative_repository
        self._prompt_registry = prompt_registry
        self._mcp_registry = mcp_registry
        self._tool_roles = dict(tool_roles)
        self._step_recorder = step_recorder
        self._clock = clock
        self._ids = id_generator
        self._budget_ledger = budget_ledger if budget_ledger is not None else BudgetLedger()
        self._budget = budget

    def explain(
        self,
        *,
        assessment_run_id: str,
        principal: Principal,
        correlation_id: str,
        agent_run_id: str | None = None,
    ) -> AssessmentExplainerResult:
        """Run this agent over ``assessment_run_id`` and return what it
        produced.

        ``principal`` is required and is never defaulted (A7.actor): it
        is the run's actor, and the proposer
        ``check_separation_of_duties`` will later refuse to let approve
        the output.
        """

        assessment_run = self._assessment_service.get_run(assessment_run_id)
        if assessment_run.tenant_id != principal.tenant_id.value:
            raise TenantScopeViolationError(
                f"assessment run {assessment_run_id} belongs to a different tenant than the caller"
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
            tenant_id=assessment_run.tenant_id,
            actor=principal.subject,
            correlation_id=correlation_id,
            budget_ledger=self._budget_ledger,
            step_recorder=self._step_recorder,
            project_id=assessment_run.project_id,
        )
        agent_run = self._agent_loop.run(
            spec,
            {
                "tenant_id": assessment_run.tenant_id,
                "project_id": assessment_run.project_id,
                "assessment_run_id": assessment_run_id,
            },
            context=context,
        )

        if agent_run.state is not AgentRunState.COMPLETED or agent_run.proposal is None:
            return AssessmentExplainerResult(
                run=agent_run,
                rejection=agent_run.terminal_reason or f"agent run ended {agent_run.state.value}",
            )

        try:
            narrative = AssessmentNarrative.model_validate(dict(agent_run.proposal))
        except PydanticValidationError as exc:
            return AssessmentExplainerResult(run=agent_run, rejection=str(exc))

        try:
            validate_narrative(narrative, run=assessment_run)
        except CairnValidationError as exc:
            return AssessmentExplainerResult(run=agent_run, rejection=str(exc))

        draft = NarrativeDraft(
            draft_id=self._ids.new_id(),
            tenant_id=assessment_run.tenant_id,
            project_id=assessment_run.project_id,
            assessment_run_id=assessment_run_id,
            agent_id=spec.agent_id,
            agent_version=spec.version,
            agent_run_id=run_id,
            proposed_by=principal.subject,
            narrative=narrative,
            created_at=self._clock.now(),
        )
        self._narratives.save_draft(draft)
        return AssessmentExplainerResult(run=agent_run, draft=draft)


__all__ = [
    "AGENT_ID",
    "AGENT_VERSION",
    "DEFAULT_BUDGET",
    "NARRATIVE_SCHEMA",
    "PROMPT_REFERENCES",
    "REQUIRED_ROLE",
    "TOOLSET",
    "AssessmentExplainerResult",
    "AssessmentExplainerService",
    "AssessmentNarrative",
    "AssessmentNarrativeRepository",
    "DispositionExplanation",
    "InMemoryAssessmentNarrativeRepository",
    "NarrativeAnomaly",
    "NarrativeContractError",
    "NarrativeDraft",
    "build_spec",
    "publish_narrative_to_evidence",
    "validate_narrative",
]
