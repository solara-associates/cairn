"""R6-13: the design agent (design §3.2, ADR-019).

Proposes a target pattern and migration waves from the estate model and
the accepted dispositions, with reasons an architect can argue with.

**The split that makes this reviewable.** The agent chooses the pattern
and the parameters and states why; the existing deterministic generators
(``generate_target_model``, ``generate_roadmap``) do the generating. The
model does not write a target model or a roadmap by hand -- it selects
inputs for code that already produces a validated one. So the artefact
stays deterministic and the model's contribution is reviewable as a
judgement rather than as output nobody can diff against anything
(design §3.2).

That split is also how validation works here, and it is worth being
explicit about: **every rule is checked against what the generators
actually produce, never against what the proposal says about itself.**
Rule 2 re-runs ``generate_target_model`` with the proposal's own pattern
and parameters and rejects the proposal if the generator rejects them.
Rules 3 and 4 re-run ``generate_roadmap`` and compare. A proposal cannot
talk its way past any of them.

**Wave ordering is "does not contradict", not "is identical"** (design
§3.2 rule 4: "the agent may propose constraints, not violate
dependencies"). The agent is allowed to group workloads more coarsely
than the generator's own topological result -- merging two of the
generator's waves into one, or splitting a wave -- but it may never put
a workload earlier than something it depends on. So the check is on
relative order: if the generator puts ``a`` strictly before ``b``, the
proposal may put them in the same wave or keep ``a`` first, and is
rejected if it puts ``b`` first.

**The approval point.** The proposal becomes a candidate plan revision
through the existing ``PlanRevisionRepository`` (``subject_revision``,
``subject_kind="plan"``, ADR-009) -- an immutable, append-only row like
any other, recording the generator's roadmap rather than the agent's
wave list. The agent is not a party to the approval:
``check_separation_of_duties`` treats the run's starting principal as
the proposer, so the same person cannot start a run and approve its
output.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from cairn_contracts.estate import (
    DecisionStatus,
    Dependency,
    DispositionDecision,
    Resource,
    Workload,
)
from cairn_contracts.mapping.model import MappingRelease
from cairn_contracts.mapping.pattern import Pattern, PatternCatalogueRelease
from cairn_kernel.errors import ForbiddenError, TenantScopeViolationError
from cairn_kernel.errors import ValidationError as CairnValidationError
from cairn_kernel.hex import ProjectId, TenantId
from cairn_kernel.hex.ports import IdGenerator
from cairn_kernel.model.ports import StructuredOutputExpectation
from cairn_kernel.security import Principal, Role
from cairn_kernel.tenancy import TenantContext, tenant_scope
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

from cairn_modules.approvals.model import ApprovalRecord, RevisionRecord, check_separation_of_duties
from cairn_modules.design.target_model import TargetModel, generate_target_model
from cairn_modules.planning.roadmap import (
    MigrationRoadmap,
    PlanRevisionRepository,
    generate_roadmap,
)

AGENT_ID = "design-proposer"
AGENT_VERSION = 1

#: Design §3.2's table, exactly: six ``READ`` tools and the two
#: ``PROPOSE`` generators. ``AgentSpec.build`` resolves every one
#: against a live ``McpRegistry`` and refuses anything that is not
#: ``READ``/``PROPOSE``.
TOOLSET: tuple[str, ...] = (
    "estate.list_workloads",
    "estate.get_dependencies",
    "design.list_patterns",
    "design.get_pattern",
    "mappings.resolve",
    "assessment.get_results",
    "design.generate_target_model",
    "planning.generate_roadmap",
)

PROMPT_REFERENCES: tuple[tuple[str, int], ...] = (
    ("design-proposer/system", 1),
    ("design-proposer/select-pattern", 1),
    ("design-proposer/assign-waves", 1),
)

#: Design §3's role rule: the two ``PROPOSE`` tools require
#: ``ARCHITECT``, so ``required_role`` is ``ARCHITECT``, which also
#: satisfies "at least ENGINEER to start any run" by dominating it.
#: ``AgentSpec.build`` checks the domination half against ``tool_roles``.
REQUIRED_ROLE = Role.ARCHITECT

#: Design §3.2's initial numbers -- bounds chosen to be safe, not
#: measurements (run sheet open question 2).
DEFAULT_BUDGET = RunBudget(
    max_steps=60,
    max_model_calls=30,
    max_total_tokens=400_000,
    max_cost_micro_usd=3_000_000,
    max_wall_clock_seconds=900,
)

PROPOSAL_SCHEMA = StructuredOutputExpectation(
    schema_name="design_proposal.v1",
    schema={
        "type": "object",
        "required": [
            "plan_id",
            "pattern_id",
            "pattern_catalogue_version",
            "mapping_release_version",
            "estate_model_version",
            "target_provider",
            "parameters",
            "pattern_rationale",
            "rejected_patterns",
            "waves",
            "risks",
        ],
        "properties": {
            "plan_id": {"type": "string"},
            "pattern_id": {"type": "string"},
            "pattern_catalogue_version": {"type": "string"},
            "mapping_release_version": {"type": "string"},
            "estate_model_version": {"type": "string"},
            "target_provider": {"type": "string"},
            "parameters": {"type": "object"},
            "pattern_rationale": {"type": "string"},
            "rejected_patterns": {"type": "array"},
            "waves": {"type": "array"},
            "risks": {"type": "array"},
        },
    },
)

DEPENDENCY_PREFIX = "dependency:"
CONSTRAINT_PREFIX = "constraint:"
WORKLOAD_PREFIX = "workload:"


class DesignContractError(CairnValidationError):
    """A design proposal failed this agent's domain contract. Raised
    before any revision row is written, so a rejected proposal leaves no
    trace but the agent run's own recorded failure."""

    title = "Design proposal rejected"


class RejectedPattern(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern_id: str
    reason: str


class ProposedWave(BaseModel):
    """One wave the agent proposes. ``constraints_cited`` must each
    resolve to a real dependency edge or a real roadmap constraint --
    design §3.2 rule 5."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    wave_number: int
    workload_ids: tuple[str, ...]
    rationale: str
    constraints_cited: tuple[str, ...]


class ProposedRisk(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    statement: str
    fact_refs: tuple[str, ...]


class DesignProposal(BaseModel):
    """Design §3.2's ``DesignProposal``, as a validated value."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_id: str
    pattern_id: str
    pattern_catalogue_version: str
    mapping_release_version: str
    estate_model_version: str
    target_provider: str
    parameters: dict[str, Any]
    pattern_rationale: str
    rejected_patterns: tuple[RejectedPattern, ...]
    waves: tuple[ProposedWave, ...]
    risks: tuple[ProposedRisk, ...]


@dataclass(frozen=True, slots=True)
class DesignInputs:
    """Everything this agent's domain contract is checked against, as
    one value.

    Assembled by the composition root from the real catalogue, mapping
    release and estate repositories; built directly in tests. It is a
    parameter rather than a constructor dependency because every field
    of it is per-project, not per-service.
    """

    tenant_id: str
    project_id: str
    plan_id: str
    design_id: str
    catalogue: PatternCatalogueRelease
    mapping_release: MappingRelease
    workloads: tuple[Workload, ...]
    dependencies: tuple[Dependency, ...] = ()
    resources: tuple[Resource, ...] = ()
    dispositions: Mapping[str, DispositionDecision] = field(default_factory=dict)

    def pattern(self, pattern_id: str) -> Pattern | None:
        for pattern in self.catalogue.patterns:
            if pattern.id == pattern_id:
                return pattern
        return None


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


# --- rule 1: the pattern exists at the declared catalogue version -----------


def _check_pattern(proposal: DesignProposal, inputs: DesignInputs) -> Pattern:
    if proposal.pattern_catalogue_version != inputs.catalogue.version:
        raise DesignContractError(
            f"proposal declares pattern catalogue version"
            f" {proposal.pattern_catalogue_version!r}, but the catalogue in use is"
            f" {inputs.catalogue.version!r}"
        )
    pattern = inputs.pattern(proposal.pattern_id)
    if pattern is None:
        raise DesignContractError(
            f"pattern {proposal.pattern_id!r} is not in catalogue"
            f" {inputs.catalogue.version!r}: a proposal may not name a pattern outside"
            " the declared catalogue version"
        )
    for rejected in proposal.rejected_patterns:
        if inputs.pattern(rejected.pattern_id) is None:
            raise DesignContractError(
                f"rejected_patterns names {rejected.pattern_id!r}, which is not in"
                f" catalogue {inputs.catalogue.version!r}: the agent cannot reject a"
                " pattern that does not exist"
            )
    return pattern


# --- rule 2: the generator accepts the parameters ---------------------------


def _generate_target_model(
    proposal: DesignProposal, inputs: DesignInputs, pattern: Pattern
) -> TargetModel:
    """Design §3.2 rule 2, delegated exactly as the design says: "the
    agent's proposal is rejected if the generator rejects it"."""

    try:
        return generate_target_model(
            tenant_id=inputs.tenant_id,
            project_id=inputs.project_id,
            design_id=inputs.design_id,
            estate=inputs.resources,
            pattern=pattern,
            pattern_catalogue_version=inputs.catalogue.version,
            mapping_release=inputs.mapping_release,
            target_provider=proposal.target_provider,
            parameters=dict(proposal.parameters),
        )
    except CairnValidationError as exc:
        raise DesignContractError(
            f"the target-model generator rejected this proposal's pattern/parameters: {exc}"
        ) from exc


# --- rules 3 and 4: coverage and ordering, against the generator -------------


def _accepted_workload_ids(inputs: DesignInputs) -> set[str]:
    """Every workload whose stored disposition decision is accepted --
    the same reading ``generate_roadmap`` itself applies
    (``ACCEPTED``/``AMENDED``), so the two never disagree about what
    "accepted" means."""

    return {
        workload.workload_id
        for workload in inputs.workloads
        if (decision := inputs.dispositions.get(workload.workload_id)) is not None
        and decision.status in {DecisionStatus.ACCEPTED, DecisionStatus.AMENDED}
    }


def _check_coverage(proposal: DesignProposal, inputs: DesignInputs) -> None:
    placed: dict[str, list[int]] = {}
    for wave in proposal.waves:
        for workload_id in wave.workload_ids:
            placed.setdefault(workload_id, []).append(wave.wave_number)

    accepted = _accepted_workload_ids(inputs)
    known = {workload.workload_id for workload in inputs.workloads}

    unknown = sorted(set(placed) - known)
    if unknown:
        raise DesignContractError(
            f"waves place workload(s) {unknown} that are not in this project's estate"
        )
    twice = sorted(wid for wid, waves in placed.items() if len(waves) > 1)
    if twice:
        raise DesignContractError(
            f"workload(s) {twice} appear in more than one wave; every accepted workload"
            " appears in exactly one"
        )
    missing = sorted(accepted - set(placed))
    if missing:
        raise DesignContractError(
            f"workload(s) {missing} have an accepted disposition but appear in no wave"
        )
    not_accepted = sorted(set(placed) - accepted)
    if not_accepted:
        raise DesignContractError(
            f"waves place workload(s) {not_accepted} whose disposition is rejected or"
            " still pending; only accepted workloads are scheduled"
        )


def _generator_wave_of(roadmap: MigrationRoadmap) -> dict[str, int]:
    return {
        wave_workload.workload_id: wave.wave_number
        for wave in roadmap.waves
        for wave_workload in wave.workloads
    }


def _check_ordering(proposal: DesignProposal, roadmap: MigrationRoadmap) -> None:
    """Design §3.2 rule 4, as relative order rather than equality -- see
    this module's docstring for why "does not contradict" is the right
    reading of "the agent may propose constraints, not violate
    dependencies"."""

    generator_wave = _generator_wave_of(roadmap)
    proposed_wave = {
        workload_id: wave.wave_number
        for wave in proposal.waves
        for workload_id in wave.workload_ids
    }
    for first, first_wave in generator_wave.items():
        for second, second_wave in generator_wave.items():
            if first_wave >= second_wave:
                continue
            if first not in proposed_wave or second not in proposed_wave:
                continue
            if proposed_wave[first] > proposed_wave[second]:
                raise DesignContractError(
                    f"the proposal puts {second!r} (wave {proposed_wave[second]}) before"
                    f" {first!r} (wave {proposed_wave[first]}), but the roadmap"
                    f" generator's own topological order puts {first!r} in wave"
                    f" {first_wave} and {second!r} in wave {second_wave}: the agent may"
                    " propose constraints, not violate dependencies"
                )


# --- rule 5: every wave and every risk cites something real -----------------


def _check_citations(
    proposal: DesignProposal, inputs: DesignInputs, roadmap: MigrationRoadmap
) -> None:
    dependency_ids = {dependency.dependency_id for dependency in inputs.dependencies}
    real_constraints = {
        f"{CONSTRAINT_PREFIX}{wave_workload.workload_id}/{constraint.kind.value}"
        for wave in roadmap.waves
        for wave_workload in wave.workloads
        for constraint in wave_workload.constraints
    }
    known_workloads = {workload.workload_id for workload in inputs.workloads}

    for wave in proposal.waves:
        if not wave.constraints_cited:
            raise DesignContractError(
                f"wave {wave.wave_number} cites no constraint or dependency; a wave"
                " rationale that cites nothing is not a rationale"
            )
        if not wave.rationale.strip():
            raise DesignContractError(f"wave {wave.wave_number} has an empty rationale")
        for citation in wave.constraints_cited:
            if citation.startswith(DEPENDENCY_PREFIX):
                if citation[len(DEPENDENCY_PREFIX) :] not in dependency_ids:
                    raise DesignContractError(
                        f"wave {wave.wave_number} cites {citation!r}, which is not a"
                        " dependency edge in this project"
                    )
            elif citation.startswith(CONSTRAINT_PREFIX):
                if citation not in real_constraints:
                    raise DesignContractError(
                        f"wave {wave.wave_number} cites {citation!r}, which the roadmap"
                        " generator did not raise against that workload"
                    )
            else:
                raise DesignContractError(
                    f"wave {wave.wave_number} cites {citation!r}, which names no known"
                    f" reference kind; expected {DEPENDENCY_PREFIX!r} or"
                    f" {CONSTRAINT_PREFIX!r}"
                )

    for risk in proposal.risks:
        if not risk.fact_refs:
            raise DesignContractError(
                f"risk {risk.statement!r} cites no fact; an uncited risk is rejected"
            )
        for ref in risk.fact_refs:
            if ref.startswith(WORKLOAD_PREFIX):
                if ref[len(WORKLOAD_PREFIX) :] not in known_workloads:
                    raise DesignContractError(
                        f"risk cites {ref!r}, which is not a workload in this project"
                    )
            elif ref.startswith(DEPENDENCY_PREFIX):
                if ref[len(DEPENDENCY_PREFIX) :] not in dependency_ids:
                    raise DesignContractError(
                        f"risk cites {ref!r}, which is not a dependency edge in this project"
                    )
            else:
                raise DesignContractError(
                    f"risk cites {ref!r}, which names no known reference kind; expected"
                    f" {WORKLOAD_PREFIX!r} or {DEPENDENCY_PREFIX!r}"
                )


# --- rule 6: the three versions are the ones actually used (R-VER-01) -------


def _check_versions(proposal: DesignProposal, inputs: DesignInputs) -> None:
    """The catalogue version is already checked by rule 1 (it selects
    the pattern), so this covers the other two. R-VER-01: diagram, plan
    and IaC share model, mapping and pattern versions, which only holds
    if the plan records the ones it was actually built from."""

    if proposal.mapping_release_version != inputs.mapping_release.version:
        raise DesignContractError(
            f"proposal declares mapping release version"
            f" {proposal.mapping_release_version!r}, but the release in use is"
            f" {inputs.mapping_release.version!r}"
        )
    estate_versions = {workload.model_version for workload in inputs.workloads}
    if len(estate_versions) != 1:
        raise DesignContractError(
            "the project's workloads do not agree on one estate model version, so no"
            f" proposal can claim it: {sorted(estate_versions)}"
        )
    estate_version = next(iter(estate_versions))
    if proposal.estate_model_version != estate_version:
        raise DesignContractError(
            f"proposal declares estate model version {proposal.estate_model_version!r},"
            f" but this project's estate was derived with {estate_version!r}"
        )


def validate_proposal(
    proposal: DesignProposal, *, inputs: DesignInputs
) -> tuple[TargetModel, MigrationRoadmap]:
    """Design §3.2's six validation rules, in order, every one a hard
    fail.

    Returns the generators' own outputs on success, because they are
    what gets recorded: the candidate plan revision records
    ``generate_roadmap``'s roadmap, never the agent's wave list.
    """

    if proposal.plan_id != inputs.plan_id:
        raise DesignContractError(
            f"proposal names plan {proposal.plan_id!r} but was produced for {inputs.plan_id!r}"
        )
    if not inputs.workloads:
        raise DesignContractError(
            f"project {inputs.project_id} has no workloads, so there is nothing for a"
            " design proposal to plan"
        )

    pattern = _check_pattern(proposal, inputs)
    target_model = _generate_target_model(proposal, inputs, pattern)
    roadmap = generate_roadmap(
        tenant_id=inputs.tenant_id,
        project_id=inputs.project_id,
        plan_id=inputs.plan_id,
        workloads=inputs.workloads,
        dependencies=inputs.dependencies,
        dispositions=dict(inputs.dispositions),
        target_model=target_model,
    )
    _check_coverage(proposal, inputs)
    _check_ordering(proposal, roadmap)
    _check_citations(proposal, inputs, roadmap)
    _check_versions(proposal, inputs)
    return target_model, roadmap


def check_agent_cannot_approve(
    revision: RevisionRecord, approval: ApprovalRecord, *, proposed_by: str
) -> None:
    """ADR-019 §6: the agent is not a party to the approval of its own
    output. ``proposed_by`` is the run's starting principal.

    Raises ``SeparationOfDutiesError`` when that principal is the
    approver, and ``ForbiddenError`` when the approval does not name
    this revision at all. It does not approve anything: the plan
    approval flow (``GET/POST /v1/plans/{revision_id}/approval``) is
    unchanged and this is the guard an agent-produced revision adds to
    it.
    """

    if approval.revision_id != revision.revision_id:
        raise ForbiddenError(
            f"approval {approval.approval_id} names revision"
            f" {approval.revision_id!r}, not {revision.revision_id!r}"
        )
    if approval.approver_actor_id is None:
        raise ForbiddenError(
            f"approval {approval.approval_id} records no approver; a candidate plan"
            " revision is approved by a human, never by an empty one"
        )
    check_separation_of_duties(proposed_by, approval.approver_actor_id)


@dataclass(frozen=True, slots=True)
class DesignProposerResult:
    """What one run of this agent produced.

    ``revision`` is not ``None`` if and only if the run completed with a
    proposal that passed all six rules -- the same "validated or absent"
    discipline ``AgentRun.proposal`` has one layer down.
    """

    run: AgentRun
    proposal: DesignProposal | None = None
    revision: RevisionRecord | None = None
    roadmap: MigrationRoadmap | None = None
    target_model: TargetModel | None = None
    rejection: str | None = None

    @property
    def accepted(self) -> bool:
        return self.revision is not None


class DesignProposerService:
    """The application service ``apps/api``/``apps/worker`` call. No
    SDK, no framework type, no SQL (ADR-019 §2)."""

    def __init__(
        self,
        *,
        agent_loop: AgentLoopPort,
        plan_revision_repository: PlanRevisionRepository,
        prompt_registry: PromptRegistry,
        mcp_registry: McpRegistry,
        tool_roles: Mapping[str, Role],
        step_recorder: StepRecorder,
        id_generator: IdGenerator,
        budget_ledger: BudgetLedger | None = None,
        budget: RunBudget = DEFAULT_BUDGET,
    ) -> None:
        self._agent_loop = agent_loop
        self._revisions = plan_revision_repository
        self._prompt_registry = prompt_registry
        self._mcp_registry = mcp_registry
        self._tool_roles = dict(tool_roles)
        self._step_recorder = step_recorder
        self._ids = id_generator
        self._budget_ledger = budget_ledger if budget_ledger is not None else BudgetLedger()
        self._budget = budget

    def propose(
        self,
        *,
        inputs: DesignInputs,
        principal: Principal,
        correlation_id: str,
        agent_run_id: str | None = None,
    ) -> DesignProposerResult:
        """Run this agent over ``inputs`` and return what it produced.

        ``principal`` is required and never defaulted (A7.actor). It is
        the run's actor and the proposer of the resulting revision.
        """

        if inputs.tenant_id != principal.tenant_id.value:
            raise TenantScopeViolationError(
                f"plan {inputs.plan_id} belongs to tenant {inputs.tenant_id!r}, not the"
                f" caller's {principal.tenant_id.value!r}"
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
                "plan_id": inputs.plan_id,
                "design_id": inputs.design_id,
                "pattern_catalogue_version": inputs.catalogue.version,
                "mapping_release_version": inputs.mapping_release.version,
            },
            context=context,
        )

        if agent_run.state is not AgentRunState.COMPLETED or agent_run.proposal is None:
            return DesignProposerResult(
                run=agent_run,
                rejection=agent_run.terminal_reason or f"agent run ended {agent_run.state.value}",
            )

        try:
            proposal = DesignProposal.model_validate(dict(agent_run.proposal))
        except PydanticValidationError as exc:
            return DesignProposerResult(run=agent_run, rejection=str(exc))

        try:
            target_model, roadmap = validate_proposal(proposal, inputs=inputs)
        except CairnValidationError as exc:
            return DesignProposerResult(run=agent_run, rejection=str(exc))

        scope = TenantContext(
            tenant_id=TenantId(inputs.tenant_id),
            project_id=ProjectId(inputs.project_id),
            actor_id=principal.subject,
            actor_roles=principal.role_values(),
            correlation_id=correlation_id,
        )
        with tenant_scope(scope):
            revision = self._revisions.create_revision(
                plan_id=inputs.plan_id, roadmap=roadmap, created_by=principal.subject
            )
        return DesignProposerResult(
            run=agent_run,
            proposal=proposal,
            revision=revision,
            roadmap=roadmap,
            target_model=target_model,
        )


__all__ = [
    "AGENT_ID",
    "AGENT_VERSION",
    "CONSTRAINT_PREFIX",
    "DEFAULT_BUDGET",
    "DEPENDENCY_PREFIX",
    "PROMPT_REFERENCES",
    "PROPOSAL_SCHEMA",
    "REQUIRED_ROLE",
    "TOOLSET",
    "WORKLOAD_PREFIX",
    "DesignContractError",
    "DesignInputs",
    "DesignProposal",
    "DesignProposerResult",
    "DesignProposerService",
    "ProposedRisk",
    "ProposedWave",
    "RejectedPattern",
    "build_spec",
    "check_agent_cannot_approve",
    "validate_proposal",
]
