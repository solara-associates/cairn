"""R4-01: the risk-tier policy engine (ADR-010).

ADR-010 defines three external mutation classes (``REVERSIBLE_EXTERNAL_
MUTATION``, ``COMPENSATABLE_EXTERNAL_MUTATION``, ``IRREVERSIBLE_EXTERNAL_
MUTATION``) and their recovery preconditions. R1-21
(``cairn_modules.execution.model.authorize_execution``) and the R-MUT-01/
R-MUT-02 conformance rules already enforce, at authorization time, that the
declared mutation class and operation class agree and that a complete
compensation contract with the matching recovery strategy exists before an
external mutation can be authorized.

This module is the policy layer that sits in front of that enforcement: it
decides *which risk tier applies* to a mutation class, and it adds the
tier's own approver-role and field requirements — requirements R1-21's
state machines know nothing about, because they operate on one proposer and
one decider, not a tier-sized roster of named sign-offs. It never
re-implements the compensation-contract or revision-binding checks R1-21
already owns; it calls into the same kernel primitives
(``cairn_kernel.classification.model.STRATEGY_BY_MUTATION`` and
``CompensationContract``) so the two layers cannot silently drift apart.

Tiers (the plan's proposed defaults, ADR-010 Class C rule 8):

====  ===============================  ========================================  =========================================================
Tier  Mutation class                   Required roles                           Notes
====  ===============================  ========================================  =========================================================
1     REVERSIBLE_EXTERNAL_MUTATION     one approver holding ``EXECUTION_ROLE``  rollback reference validated before authorization
2     COMPENSATABLE_EXTERNAL_MUTATION  two approvers (separation of duties),    compensation contract (trigger + scope + validation)
                                        one holding ``EXECUTION_ROLE``           complete before authorization
3     IRREVERSIBLE_EXTERNAL_MUTATION   the accountable approver (holding        no rollback promise; preflight/dry-run required where the
                                        ``EXECUTION_ROLE``) signs the risk       provider supports one
                                        acceptance personally; a second
                                        approver confirms blast radius
====  ===============================  ========================================  =========================================================

Judgement calls (the brief: "if you think a detail is genuinely
underspecified, make the most honest reading ... name the judgement call"):

* "The execution role" is not a role the tier table defines. The spec's API
  table (``CAIRN-TECHNICAL-IMPLEMENTATION-SPEC.md``, "POST /v1/executions ...
  Request Class C execution of an approved revision ... PROJECT_OWNER ... C
  ... R4") is the only place the spec binds a named role to triggering Class
  C execution, so ``EXECUTION_ROLE`` is read as ``Role.PROJECT_OWNER``. The
  same role table also makes PROJECT_OWNER the natural reading of tier 3's
  "accountable approver" (PROJECT_OWNER: "Create/manage project, members,
  submit approvals" -- the role accountable for the project's approvals).
* Tier 3's "a second approver confirms blast radius" names no role either.
  ARCHITECT ("Run assessments, edit workloads, generate designs/plans") is
  the role positioned to actually assess blast radius, so the second
  approver must hold ``ARCHITECT`` specifically, distinct from the
  accountable PROJECT_OWNER.
* AUDITOR ("Read evidence, audit, provenance; no mutation") and VIEWER carry
  no mutation rights per the spec's role table, so neither may ever stand in
  as an approver sign-off, at any tier -- allowing one through would be a
  silent policy defect, not a legitimate approval.
* The explicit "risk-acceptance field" tier 3 requires is modelled as its
  own ``RiskAcceptance`` record, signed by name by the accountable approver,
  rather than reusing ``CompensationContract.preconditions`` free text --
  the brief calls it out as a field this unit must enforce is *populated*,
  which only means something if it is a distinct, structured field rather
  than prose folded into an existing one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from cairn_kernel.classification.model import (
    STRATEGY_BY_MUTATION,
    CompensationContract,
    RecoveryStrategy,
)
from cairn_kernel.errors import (
    RequiredApproverRoleMissingError,
    RiskAcceptanceRequiredError,
    RiskTierMismatchError,
    SeparationOfDutiesError,
)
from cairn_kernel.hex.primitives import MutationClass
from cairn_kernel.security.roles import Role

from cairn_modules.approvals.model import ApprovalRecord


class RiskTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


# ADR-010's three external mutation classes map onto the plan's three
# tiers, in the same order the recovery precondition escalates
# (rollback -> compensation -> explicit, no-rollback risk acceptance).
# READ_ONLY and INTERNAL_MUTATION never require a tier (ADR-010: "No
# external recovery required").
TIER_BY_MUTATION_CLASS: dict[MutationClass, RiskTier] = {
    MutationClass.REVERSIBLE_EXTERNAL_MUTATION: RiskTier.TIER_1,
    MutationClass.COMPENSATABLE_EXTERNAL_MUTATION: RiskTier.TIER_2,
    MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION: RiskTier.TIER_3,
}

# See module docstring "Judgement calls" for why PROJECT_OWNER/ARCHITECT.
EXECUTION_ROLE: Role = Role.PROJECT_OWNER
BLAST_RADIUS_CONFIRMER_ROLE: Role = Role.ARCHITECT

# Roles that may never stand in as an approver sign-off, at any tier.
NON_APPROVER_ROLES: frozenset[Role] = frozenset({Role.AUDITOR, Role.VIEWER})


def tier_for_mutation_class(mutation_class: MutationClass) -> RiskTier | None:
    """The risk tier ADR-010 assigns to ``mutation_class``, or ``None`` for
    ``READ_ONLY``/``INTERNAL_MUTATION``, which carry no tier at all."""

    return TIER_BY_MUTATION_CLASS.get(mutation_class)


def tier_for_approval(approval: ApprovalRecord) -> RiskTier | None:
    """Validate ``approval.risk_tier`` against the tier CAIRN computes for
    its mutation class, rather than trusting the caller-supplied string.

    Raises ``RiskTierMismatchError`` (fail closed) on any disagreement --
    a proposer declaring ``risk_tier="TIER_1"`` for an
    ``IRREVERSIBLE_EXTERNAL_MUTATION`` must never be silently honoured.
    """

    expected = tier_for_mutation_class(approval.mutation_class)
    declared = approval.risk_tier.strip()

    if expected is None:
        # READ_ONLY/INTERNAL_MUTATION carry no tier; reject anything that
        # claims one of the two tiers reserved for an external mutation.
        if declared in (RiskTier.TIER_2.value, RiskTier.TIER_3.value):
            raise RiskTierMismatchError(
                f"approval {approval.approval_id} declares risk_tier {declared!r}"
                f" but {approval.mutation_class.value} carries no risk tier"
            )
        return None

    if declared != expected.value:
        raise RiskTierMismatchError(
            f"approval {approval.approval_id} declares risk_tier {declared!r}, but"
            f" {approval.mutation_class.value} requires {expected.value}"
        )
    return expected


@dataclass(frozen=True, slots=True)
class ApproverSignOff:
    """One named approver's sign-off: who, and in what role."""

    actor_id: str
    role: Role

    def __post_init__(self) -> None:
        if not self.actor_id.strip():
            raise RequiredApproverRoleMissingError("an approver sign-off needs a named actor_id")


class PreflightStatus(str, Enum):
    RAN = "RAN"
    NOT_SUPPORTED_BY_PROVIDER = "NOT_SUPPORTED_BY_PROVIDER"


@dataclass(frozen=True, slots=True)
class PreflightResult:
    """ADR-010 tier 3: "preflight/dry-run required where the provider
    supports one". ``NOT_SUPPORTED_BY_PROVIDER`` is an explicit, recorded
    declaration that no preflight exists for this provider/operation, never
    an implicit default for an omitted field."""

    status: PreflightStatus
    detail: str

    def __post_init__(self) -> None:
        if not self.detail.strip():
            raise RiskAcceptanceRequiredError(
                "a preflight/dry-run result must record its detail, not be left blank"
            )


@dataclass(frozen=True, slots=True)
class BlastRadiusConfirmation:
    """Tier 3's second approver, confirming blast radius by name."""

    actor_id: str
    role: Role
    statement: str

    def __post_init__(self) -> None:
        if not self.statement.strip():
            raise RiskAcceptanceRequiredError(
                "a blast-radius confirmation must record its statement, not be left blank"
            )


@dataclass(frozen=True, slots=True)
class RiskAcceptance:
    """ADR-010 tier 3's explicit risk-acceptance field: the accountable
    approver's personal sign-off, the second approver's blast-radius
    confirmation, and the preflight/dry-run result -- populated, never
    silently defaulted, before an irreversible mutation can be authorized.
    """

    accepted_by: ApproverSignOff
    statement: str
    blast_radius: BlastRadiusConfirmation
    preflight: PreflightResult

    def __post_init__(self) -> None:
        if not self.statement.strip():
            raise RiskAcceptanceRequiredError(
                "risk acceptance requires a non-blank statement personally signed by"
                " the accountable approver"
            )


def _reject_duplicate_or_proposer_actors(
    proposer_actor_id: str, approvers: tuple[ApproverSignOff, ...]
) -> None:
    if any(a.actor_id == proposer_actor_id for a in approvers):
        raise SeparationOfDutiesError(
            f"actor {proposer_actor_id!r} proposed this mutation and cannot also approve it"
        )
    seen: set[str] = set()
    for a in approvers:
        if a.actor_id in seen:
            raise SeparationOfDutiesError(
                f"actor {a.actor_id!r} cannot hold more than one approver sign-off"
                " on the same mutation"
            )
        seen.add(a.actor_id)


def _reject_non_approver_roles(approvers: tuple[ApproverSignOff, ...]) -> None:
    for a in approvers:
        if a.role in NON_APPROVER_ROLES:
            raise RequiredApproverRoleMissingError(
                f"{a.role.value} may not act as an approver (actor {a.actor_id!r})"
            )


def _require_recovery_strategy(
    mutation_class: MutationClass, compensation: CompensationContract | None
) -> None:
    """Delegate strategy-matching to the same kernel mapping R1-21 uses
    (``STRATEGY_BY_MUTATION``) -- a presence/strategy check only; the
    contract's own ``__post_init__`` already guarantees every element is
    populated, and R-MUT-01/R-MUT-02 own re-validating that at
    authorization time. This function only confirms the tier's recovery
    precondition exists before approver-role enforcement proceeds."""

    if compensation is None:
        raise RiskAcceptanceRequiredError(
            f"{mutation_class.value} requires a compensation contract before"
            " its risk tier can be authorized"
        )
    expected = STRATEGY_BY_MUTATION[mutation_class]
    if compensation.strategy is not expected:
        raise RiskAcceptanceRequiredError(
            f"{mutation_class.value} requires recovery strategy {expected.value},"
            f" got {compensation.strategy.value}"
        )


def authorize_tier(
    mutation_class: MutationClass,
    *,
    proposer_actor_id: str,
    approvers: tuple[ApproverSignOff, ...],
    compensation: CompensationContract | None,
    risk_acceptance: RiskAcceptance | None = None,
) -> RiskTier | None:
    """Enforce the risk tier's approver-role and field requirements for
    ``mutation_class``. Returns the tier that was enforced (``None`` for a
    mutation class that carries no tier). Raises -- fails closed, no silent
    default -- when a required approver role, approver count, or field is
    missing.
    """

    tier = tier_for_mutation_class(mutation_class)
    if tier is None:
        return None

    _reject_duplicate_or_proposer_actors(proposer_actor_id, approvers)
    _reject_non_approver_roles(approvers)

    if tier is RiskTier.TIER_1:
        _authorize_tier_1(mutation_class, approvers, compensation)
    elif tier is RiskTier.TIER_2:
        _authorize_tier_2(mutation_class, approvers, compensation)
    else:
        _authorize_tier_3(mutation_class, approvers, compensation, risk_acceptance)

    return tier


def _authorize_tier_1(
    mutation_class: MutationClass,
    approvers: tuple[ApproverSignOff, ...],
    compensation: CompensationContract | None,
) -> None:
    if len(approvers) != 1:
        raise RequiredApproverRoleMissingError(
            f"tier 1 ({mutation_class.value}) requires exactly one approver, got {len(approvers)}"
        )
    if approvers[0].role is not EXECUTION_ROLE:
        raise RequiredApproverRoleMissingError(
            f"tier 1 ({mutation_class.value}) requires an approver holding"
            f" {EXECUTION_ROLE.value}, got {approvers[0].role.value}"
        )
    _require_recovery_strategy(mutation_class, compensation)
    if compensation is not None and not compensation.plan_ref.strip():
        # Unreachable via the dataclass's own __post_init__, but named
        # explicitly: ADR-010 tier 1's "rollback reference validated"
        # is this field.
        raise RiskAcceptanceRequiredError(
            "tier 1 requires a validated rollback reference (plan_ref)"
        )


def _authorize_tier_2(
    mutation_class: MutationClass,
    approvers: tuple[ApproverSignOff, ...],
    compensation: CompensationContract | None,
) -> None:
    if len(approvers) != 2:
        raise RequiredApproverRoleMissingError(
            f"tier 2 ({mutation_class.value}) requires exactly two approvers"
            f" (separation of duties), got {len(approvers)}"
        )
    if not any(a.role is EXECUTION_ROLE for a in approvers):
        raise RequiredApproverRoleMissingError(
            f"tier 2 ({mutation_class.value}) requires at least one approver holding"
            f" {EXECUTION_ROLE.value}"
        )
    _require_recovery_strategy(mutation_class, compensation)
    if compensation is not None and not compensation.preconditions.strip():
        raise RiskAcceptanceRequiredError(
            "tier 2 requires a complete compensation contract (trigger, scope and"
            " validation in preconditions)"
        )


def _authorize_tier_3(
    mutation_class: MutationClass,
    approvers: tuple[ApproverSignOff, ...],
    compensation: CompensationContract | None,
    risk_acceptance: RiskAcceptance | None,
) -> None:
    if len(approvers) != 2:
        raise RequiredApproverRoleMissingError(
            f"tier 3 ({mutation_class.value}) requires the accountable approver and a"
            f" second approver confirming blast radius, got {len(approvers)}"
        )

    accountable = next((a for a in approvers if a.role is EXECUTION_ROLE), None)
    if accountable is None:
        raise RequiredApproverRoleMissingError(
            f"tier 3 ({mutation_class.value}) requires the accountable approver to hold"
            f" {EXECUTION_ROLE.value}"
        )
    confirmer = next((a for a in approvers if a.actor_id != accountable.actor_id), None)
    if confirmer is None or confirmer.role is not BLAST_RADIUS_CONFIRMER_ROLE:
        raise RequiredApproverRoleMissingError(
            f"tier 3 ({mutation_class.value}) requires a second approver holding"
            f" {BLAST_RADIUS_CONFIRMER_ROLE.value} to confirm blast radius"
        )

    # ADR-010: irreversible mutations carry no rollback promise.
    _require_recovery_strategy(mutation_class, compensation)
    if compensation is not None and compensation.strategy is RecoveryStrategy.ROLLBACK:
        raise RiskAcceptanceRequiredError(
            "an IRREVERSIBLE_EXTERNAL_MUTATION must not carry a rollback promise"
        )

    if risk_acceptance is None:
        raise RiskAcceptanceRequiredError(
            f"{mutation_class.value} cannot proceed without the explicit"
            " risk-acceptance field populated"
        )
    if risk_acceptance.accepted_by.actor_id != accountable.actor_id:
        raise RiskAcceptanceRequiredError(
            "the accountable approver must sign the risk acceptance personally"
            f" (expected {accountable.actor_id!r}, got"
            f" {risk_acceptance.accepted_by.actor_id!r})"
        )
    if risk_acceptance.blast_radius.actor_id != confirmer.actor_id:
        raise RequiredApproverRoleMissingError(
            "the second approver who confirms blast radius must be the one who"
            " signs the risk acceptance's blast-radius confirmation"
            f" (expected {confirmer.actor_id!r}, got"
            f" {risk_acceptance.blast_radius.actor_id!r})"
        )
    if risk_acceptance.preflight.status is PreflightStatus.NOT_SUPPORTED_BY_PROVIDER:
        # Explicitly recorded as unsupported -- a valid, non-blocking
        # declaration (ADR-010: "where the provider supports one"), never
        # an implicit default.
        return


__all__ = [
    "BLAST_RADIUS_CONFIRMER_ROLE",
    "EXECUTION_ROLE",
    "NON_APPROVER_ROLES",
    "TIER_BY_MUTATION_CLASS",
    "ApproverSignOff",
    "BlastRadiusConfirmation",
    "PreflightResult",
    "PreflightStatus",
    "RiskAcceptance",
    "RiskTier",
    "authorize_tier",
    "tier_for_approval",
    "tier_for_mutation_class",
]
