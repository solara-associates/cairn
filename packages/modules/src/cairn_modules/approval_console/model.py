"""792 (R4-05): the approval and execution console's own domain pieces.

Spec §2.4 (quoted verbatim in this unit's brief): "R4-05's console shows
the approver the exact revision: the diff, the mutation class, the
recovery plan (rollback or compensation contract, ADR-010), and the
evidence that will be captured. Nothing is approved from a summary -- the
approver sees what will actually run."

This module owns the two pieces of that console that are pure domain
logic, independent of which provider adapter or API transport renders
them:

* ``ApprovalComment``/``PlanApprovalThread`` -- the approver's own
  comment/decision thread, attached to one Terraform plan revision
  (787's ``TerraformPlanRevisionPayload.revision_id``) rather than to a
  transformation run. **An existing shape was checked for first, per
  this unit's brief.** ``cairn_modules.transformation.review``'s
  ``ReviewDecisionKind`` (R3-07/732) is exactly the three-valued
  "comment / request changes / approve" decision this console also
  needs -- imported here directly, not reinvented. ``ReviewComment``/
  ``RunReviewThread`` themselves are not reused as-is: both are hard-bound
  by field name (``run_id``) and docstring to a transformation run, a
  different subject from the Terraform plan revision this console
  reviews, so renaming that field on a borrowed dataclass would read as
  reuse while actually being a silent redefinition. This module instead
  mirrors their exact shape and ``blocked``/``reviewed`` semantics one
  field for one field, under names that say what they actually hold
  (judgement call, named here rather than silently reusing a
  mismatched shape or inventing an unrelated one).

* ``ensure_recovery_plan_complete`` -- this unit's own acceptance text:
  "a deliberate-break test proves an incomplete recovery plan cannot be
  approved from the console (mirrors 783's gate, enforced again at the
  UI layer so a UI bug can't bypass the kernel constraint)". 783
  (``cairn_modules.risk_policy.model._require_recovery_strategy``)
  already enforces, at authorization time, that a ``CompensationContract``
  exists and carries the recovery strategy ``cairn_kernel.classification.
  model.STRATEGY_BY_MUTATION`` requires for the mutation class. This
  function is the same check, re-run at the console's own API layer --
  it calls into the same kernel mapping and raises the same
  ``RiskAcceptanceRequiredError`` 783 raises for the identical condition,
  so the two layers cannot silently drift apart, and a bug in this
  console's own UI/API code cannot let an incomplete recovery plan reach
  approval even if 783's own authorization step were never reached or
  were itself buggy.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime

from cairn_kernel.classification.model import STRATEGY_BY_MUTATION, CompensationContract
from cairn_kernel.errors import RiskAcceptanceRequiredError
from cairn_kernel.hex.primitives import MutationClass

# Reused directly, per this unit's brief ("reuse the existing
# ReviewDecision shape from R3-07 ... if applicable") -- not reinvented.
from cairn_modules.transformation.review import ReviewDecisionKind


@dataclass(frozen=True, slots=True)
class ApprovalComment:
    """One approver's annotation on one Terraform plan revision's
    approval console. Mirrors ``cairn_modules.transformation.
    ReviewComment`` field-for-field (actor, decision, body, timestamp),
    keyed to ``revision_id`` instead of a transformation run id -- see
    this module's own docstring for why that one field had to change
    rather than be reused unmodified.
    """

    revision_id: str
    reviewer_actor_id: str
    decision: ReviewDecisionKind
    body: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.revision_id.strip():
            raise ValueError("an approval comment must name the revision it is attached to")
        if not self.reviewer_actor_id.strip():
            raise ValueError("an approval comment must name its reviewer")
        if not self.body.strip():
            raise ValueError("an approval comment must have a non-empty body")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must include a timezone")


@dataclass(frozen=True, slots=True)
class PlanApprovalThread:
    """The full, ordered comment/decision history for one Terraform plan
    revision's approval console. Mirrors ``RunReviewThread.blocked``/
    ``.reviewed`` exactly -- see that class's own docstring for the full
    reasoning; the same reading applies here, just against a plan
    revision rather than a transformation run.
    """

    revision_id: str
    comments: tuple[ApprovalComment, ...] = ()

    @property
    def blocked(self) -> bool:
        for comment in reversed(self.comments):
            if comment.decision is ReviewDecisionKind.REQUEST_CHANGES:
                return True
            if comment.decision is ReviewDecisionKind.APPROVE:
                return False
        return False

    @property
    def reviewed(self) -> bool:
        return any(
            comment.decision is not ReviewDecisionKind.COMMENT for comment in self.comments
        )


def add_approval_comment(thread: PlanApprovalThread, comment: ApprovalComment) -> PlanApprovalThread:
    """Appends ``comment`` to ``thread``, never mutating either in place
    -- the same immutable-dataclass discipline ``cairn_modules.
    transformation.review.add_review_comment`` already follows."""

    if comment.revision_id != thread.revision_id:
        raise ValueError(
            f"comment for revision {comment.revision_id!r} cannot be added to thread for "
            f"revision {thread.revision_id!r}"
        )
    return dataclasses.replace(thread, comments=thread.comments + (comment,))


def ensure_recovery_plan_complete(
    mutation_class: MutationClass, compensation: CompensationContract | None
) -> None:
    """Re-enforce, at the console's own layer, the same recovery-plan
    completeness precondition 783's ``authorize_tier``/
    ``_require_recovery_strategy`` already enforce at authorization time
    (see this module's own docstring).

    Raises ``RiskAcceptanceRequiredError`` -- fails closed, approves
    nothing -- when ``mutation_class`` requires external recovery (i.e.
    carries a tier at all, per ``STRATEGY_BY_MUTATION``) and either no
    compensation contract has been recorded at all, or the one recorded
    does not carry the recovery strategy that mutation class requires.
    A ``CompensationContract``'s own ``__post_init__`` already refuses to
    construct one with a blank field, so a contract that reaches this
    function is already structurally complete; this function's own job
    is the one completeness question that check cannot see: whether a
    contract exists at all, and whether its strategy actually matches
    the mutation being approved.
    """

    expected_strategy = STRATEGY_BY_MUTATION.get(mutation_class)
    if expected_strategy is None:
        # READ_ONLY/INTERNAL_MUTATION carry no tier and no recovery
        # obligation (ADR-010) -- nothing to enforce.
        return

    if compensation is None:
        raise RiskAcceptanceRequiredError(
            f"{mutation_class.value} cannot be approved from this console without a"
            " recorded recovery plan (rollback or compensation contract, ADR-010)"
        )
    if compensation.strategy is not expected_strategy:
        raise RiskAcceptanceRequiredError(
            f"{mutation_class.value} requires recovery strategy {expected_strategy.value},"
            f" but the recorded recovery plan declares {compensation.strategy.value} --"
            " this console cannot approve a mismatched recovery plan"
        )


__all__ = [
    "ApprovalComment",
    "PlanApprovalThread",
    "ReviewDecisionKind",
    "add_approval_comment",
    "ensure_recovery_plan_complete",
]
