"""792 (R4-05): ``cairn_modules.approval_console`` -- the approval
console's own approver comment/decision thread, and the recovery-plan
completeness check re-enforced at this console's own layer (mirrors
783's ``risk_policy`` gate)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from cairn_kernel.classification.model import CompensationContract, RecoveryStrategy
from cairn_kernel.errors import RiskAcceptanceRequiredError
from cairn_kernel.hex.primitives import MutationClass
from cairn_modules.approval_console.model import (
    ApprovalComment,
    PlanApprovalThread,
    ReviewDecisionKind,
    add_approval_comment,
    ensure_recovery_plan_complete,
)

REVISION_ID = "revision-1"
AT = datetime(2026, 1, 1, tzinfo=UTC)


def _comment(decision: ReviewDecisionKind, body: str = "looks fine") -> ApprovalComment:
    return ApprovalComment(
        revision_id=REVISION_ID,
        reviewer_actor_id="approver-1",
        decision=decision,
        body=body,
        created_at=AT,
    )


def _compensation(strategy: RecoveryStrategy = RecoveryStrategy.ROLLBACK) -> CompensationContract:
    return CompensationContract(
        strategy=strategy,
        plan_ref="plan-ref-1",
        preconditions="preconditions",
        authority="authority",
        evidence="before/during/after capture description",
        failure_handling="failure handling",
    )


# -- PlanApprovalThread: mirrors RunReviewThread's own blocked/reviewed --


def test_a_plain_comment_requires_no_decision_and_never_blocks() -> None:
    thread = PlanApprovalThread(revision_id=REVISION_ID)
    thread = add_approval_comment(thread, _comment(ReviewDecisionKind.COMMENT, "nit"))
    assert len(thread.comments) == 1
    assert thread.blocked is False
    assert thread.reviewed is False


def test_a_request_changes_comment_visibly_blocks_further_progress() -> None:
    thread = PlanApprovalThread(revision_id=REVISION_ID)
    thread = add_approval_comment(
        thread, _comment(ReviewDecisionKind.REQUEST_CHANGES, "recovery plan is incomplete")
    )
    assert thread.blocked is True
    assert thread.reviewed is True


def test_an_approve_after_request_changes_clears_the_block() -> None:
    thread = PlanApprovalThread(revision_id=REVISION_ID)
    thread = add_approval_comment(thread, _comment(ReviewDecisionKind.REQUEST_CHANGES, "fix this"))
    thread = add_approval_comment(thread, _comment(ReviewDecisionKind.APPROVE, "fixed"))
    assert thread.blocked is False
    assert thread.reviewed is True


def test_an_empty_thread_is_neither_blocked_nor_reviewed() -> None:
    thread = PlanApprovalThread(revision_id=REVISION_ID)
    assert thread.blocked is False
    assert thread.reviewed is False


def test_adding_a_comment_for_a_different_revision_is_rejected() -> None:
    thread = PlanApprovalThread(revision_id=REVISION_ID)
    other = ApprovalComment(
        revision_id="revision-2",
        reviewer_actor_id="approver-1",
        decision=ReviewDecisionKind.COMMENT,
        body="wrong thread",
        created_at=AT,
    )
    with pytest.raises(ValueError, match="cannot be added"):
        add_approval_comment(thread, other)


def test_add_approval_comment_never_mutates_the_original_thread() -> None:
    thread = PlanApprovalThread(revision_id=REVISION_ID)
    new_thread = add_approval_comment(thread, _comment(ReviewDecisionKind.COMMENT))
    assert thread.comments == ()
    assert len(new_thread.comments) == 1


def test_an_approval_comment_requires_a_non_empty_body() -> None:
    with pytest.raises(ValueError, match="non-empty body"):
        ApprovalComment(
            revision_id=REVISION_ID,
            reviewer_actor_id="approver-1",
            decision=ReviewDecisionKind.COMMENT,
            body="   ",
            created_at=AT,
        )


# -- ensure_recovery_plan_complete: 783's gate, re-enforced here --


def test_a_complete_matching_recovery_plan_passes() -> None:
    ensure_recovery_plan_complete(
        MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
        _compensation(RecoveryStrategy.ROLLBACK),
    )


def test_a_missing_recovery_plan_is_rejected_for_an_external_mutation() -> None:
    with pytest.raises(RiskAcceptanceRequiredError, match="recovery plan"):
        ensure_recovery_plan_complete(MutationClass.REVERSIBLE_EXTERNAL_MUTATION, None)


def test_a_mismatched_recovery_strategy_is_rejected() -> None:
    with pytest.raises(RiskAcceptanceRequiredError, match="mismatched recovery plan"):
        ensure_recovery_plan_complete(
            MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION,
            _compensation(RecoveryStrategy.ROLLBACK),
        )


def test_read_only_mutations_require_no_recovery_plan() -> None:
    ensure_recovery_plan_complete(MutationClass.READ_ONLY, None)


def test_internal_mutations_require_no_recovery_plan() -> None:
    ensure_recovery_plan_complete(MutationClass.INTERNAL_MUTATION, None)
