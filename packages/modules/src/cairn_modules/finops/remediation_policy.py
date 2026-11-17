"""R5-01a: FinOps graded remediation policy (unit 812).

This is the FinOps-specific policy layer on top of two things that already
exist and must not be duplicated:

* ``cairn_modules.finops`` (R1-12/R1-13): the cost-baseline and TCO model
  this policy decides *what to do about*. This module takes no dependency
  on that cost model's internals -- it only grades an already-proposed
  remediation action and decides what governance it must pass through.
* ``cairn_modules.risk_policy`` (783, ADR-010): the three risk tiers and
  ``authorize_tier`` -- the only place approver-role, separation-of-duties
  and recovery-precondition enforcement for an external mutation lives.
  This module calls into it; it never re-implements any of that machinery.

ADR-010's operation classes map directly onto FinOps's five remediation
grades:

====  =========  ===============  ===========================================
Grade Operation  Mutation class   Why
====  =========  ===============  ===========================================
ALERT   A (read)      None        Notifies only; no state changes anywhere.
THROTTLE B (workspace) None        Records a rate-limit decision in CAIRN's
                                   own workspace (e.g. flags the budget as
                                   throttled); does not itself touch the
                                   customer's cloud environment.
CAP     C (external)  see below
STOP    C (external)  see below
DISABLE C (external)  see below
====  =========  ===============  ===========================================

``ALERT``/``THROTTLE`` are Class A/B: no external mutation, so they carry no
risk tier and need no approval beyond the read/workspace rules ADR-010
already assigns those classes (authN/authZ, tenant isolation, audit trail --
enforced elsewhere, not re-implemented here).

``CAP``/``STOP``/``DISABLE`` are Class C and each needs a mutation-class
judgement call, made explicitly here rather than invented silently at call
sites:

* ``CAP`` (lower a budget/quota limit on a resource): the cap itself can
  always be raised back to its prior value by the same mechanism that set
  it, with no data or in-flight work lost. Modelled as
  ``REVERSIBLE_EXTERNAL_MUTATION`` (tier 1) -- a straightforward rollback.
* ``DISABLE`` (turn a resource or feature off): per the brief, "a disable is
  usually reversible" -- re-enabling restores the prior state and, for the
  resources this policy targets (a budget alert integration, an autoscaler,
  a non-stateful feature flag), there is nothing in flight to lose by
  disabling it. Modelled as ``REVERSIBLE_EXTERNAL_MUTATION`` (tier 1) as
  well, on the same reasoning as ``CAP``.
* ``STOP`` (stop a running resource, e.g. a VM or job): unlike a disable,
  stopping a running resource can drop in-flight work (an in-progress
  request, an unflushed buffer, a batch job's partial output) that a simple
  "start it again" does not restore -- restarting gets the resource running
  again but not necessarily back to the state it was in when stopped.
  Modelled as ``COMPENSATABLE_EXTERNAL_MUTATION`` (tier 2): recovering from
  a bad stop needs a compensating action (e.g. re-run the dropped job, or
  reconcile from a checkpoint), not just a rollback.

No remediation grade in this unit is modelled as
``IRREVERSIBLE_EXTERNAL_MUTATION`` (tier 3) -- the brief's five grades are
all actions FinOps can undo or compensate for by construction (that is what
makes them "remediation" rather than, say, a destructive delete). A future
grade that can't be undone (e.g. permanently deleting a resource) would need
its own judgement call against tier 3, not a silent reuse of this mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from cairn_kernel.classification.model import CompensationContract
from cairn_kernel.errors import ValidationError
from cairn_kernel.hex.primitives import MutationClass

from cairn_modules.risk_policy.model import (
    ApproverSignOff,
    RiskAcceptance,
    RiskTier,
    authorize_tier,
)


class RemediationGrade(str, Enum):
    """FinOps's five graded remediation actions, ordered least to most
    severe."""

    ALERT = "ALERT"
    THROTTLE = "THROTTLE"
    CAP = "CAP"
    STOP = "STOP"
    DISABLE = "DISABLE"


# See module docstring for the judgement call behind each Class C mapping.
# ALERT/THROTTLE map to None: no external mutation, so no risk tier applies
# (ADR-010: "READ_ONLY"/"INTERNAL_MUTATION" carry no tier at all).
MUTATION_CLASS_BY_GRADE: dict[RemediationGrade, MutationClass | None] = {
    RemediationGrade.ALERT: None,
    RemediationGrade.THROTTLE: None,
    RemediationGrade.CAP: MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
    RemediationGrade.DISABLE: MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
    RemediationGrade.STOP: MutationClass.COMPENSATABLE_EXTERNAL_MUTATION,
}

# The grades that reach a customer environment (ADR-010 Class C) and must
# therefore pass through risk_policy.authorize_tier before proceeding.
CLASS_C_GRADES: frozenset[RemediationGrade] = frozenset(
    {RemediationGrade.CAP, RemediationGrade.STOP, RemediationGrade.DISABLE}
)


def mutation_class_for_grade(grade: RemediationGrade) -> MutationClass | None:
    """The mutation class this policy assigns ``grade``, or ``None`` for a
    grade (``ALERT``/``THROTTLE``) that carries no external mutation."""

    return MUTATION_CLASS_BY_GRADE[grade]


def tier_for_grade(grade: RemediationGrade) -> RiskTier | None:
    """The risk tier a Class C grade's mutation class resolves to, via
    ``risk_policy.tier_for_mutation_class`` -- never a tier computed or
    stored independently here, so the two layers cannot drift apart."""

    from cairn_modules.risk_policy.model import tier_for_mutation_class

    mutation_class = mutation_class_for_grade(grade)
    if mutation_class is None:
        return None
    return tier_for_mutation_class(mutation_class)


@dataclass(frozen=True, slots=True)
class RemediationAction:
    """One proposed FinOps remediation action, prior to authorization.

    ``resource_ref`` identifies the budget/resource/account the action
    targets (provenance for the eventual Class C executor -- unit 813 -- to
    bind a ``ProviderExecutionPort`` call to); ``reason`` is the
    human-readable justification (e.g. "budget exceeded 120% of forecast")
    this grade was chosen for.
    """

    grade: RemediationGrade
    resource_ref: str
    reason: str

    def __post_init__(self) -> None:
        for field_name, value in (("resource ref", self.resource_ref), ("reason", self.reason)):
            if not value.strip():
                raise ValidationError(f"remediation action {field_name} is required")

    @property
    def mutation_class(self) -> MutationClass | None:
        return mutation_class_for_grade(self.grade)

    @property
    def is_class_c(self) -> bool:
        return self.grade in CLASS_C_GRADES


def authorize_remediation(
    action: RemediationAction,
    *,
    proposer_actor_id: str,
    approvers: tuple[ApproverSignOff, ...] = (),
    compensation: CompensationContract | None = None,
    risk_acceptance: RiskAcceptance | None = None,
) -> RiskTier | None:
    """Authorize ``action`` for execution.

    ``ALERT``/``THROTTLE`` (no mutation class) return ``None`` immediately:
    there is nothing for risk_policy to enforce beyond the read/workspace
    rules that already apply to Class A/B operations, and this function
    does not duplicate those.

    ``CAP``/``STOP``/``DISABLE`` delegate entirely to
    ``risk_policy.authorize_tier`` for their mapped mutation class -- the
    same approver-role, separation-of-duties, and recovery-precondition
    enforcement every other external mutation in CAIRN goes through.
    ``authorize_tier`` fails closed (raises) when a requirement is unmet;
    this function never catches that to substitute a default allow.
    """

    mutation_class = mutation_class_for_grade(action.grade)
    if mutation_class is None:
        return None

    return authorize_tier(
        mutation_class,
        proposer_actor_id=proposer_actor_id,
        approvers=approvers,
        compensation=compensation,
        risk_acceptance=risk_acceptance,
    )


__all__ = [
    "CLASS_C_GRADES",
    "MUTATION_CLASS_BY_GRADE",
    "RemediationAction",
    "RemediationGrade",
    "authorize_remediation",
    "mutation_class_for_grade",
    "tier_for_grade",
]
