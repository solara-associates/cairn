"""R3-07: ``cairn_modules.transformation.review`` -- the engineer's
review/comment/request-changes annotation thread for a transformation
run."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from cairn_modules.transformation.review import (
    ReviewComment,
    ReviewDecisionKind,
    RunReviewThread,
    add_review_comment,
)

RUN_ID = "run-1"
AT = datetime(2026, 1, 1, tzinfo=UTC)


def _comment(decision: ReviewDecisionKind, body: str = "looks fine") -> ReviewComment:
    return ReviewComment(
        run_id=RUN_ID,
        reviewer_actor_id="reviewer-1",
        decision=decision,
        body=body,
        created_at=AT,
    )


def test_a_plain_comment_requires_no_decision_and_never_blocks() -> None:
    thread = RunReviewThread(run_id=RUN_ID)
    thread = add_review_comment(thread, _comment(ReviewDecisionKind.COMMENT, "nit: naming"))
    assert len(thread.comments) == 1
    assert thread.blocked is False
    assert thread.reviewed is False


def test_a_request_changes_comment_visibly_blocks_further_progress() -> None:
    thread = RunReviewThread(run_id=RUN_ID)
    thread = add_review_comment(
        thread, _comment(ReviewDecisionKind.REQUEST_CHANGES, "this breaks the dependency check")
    )
    assert thread.blocked is True
    assert thread.reviewed is True


def test_an_approve_after_request_changes_clears_the_block() -> None:
    thread = RunReviewThread(run_id=RUN_ID)
    thread = add_review_comment(thread, _comment(ReviewDecisionKind.REQUEST_CHANGES, "fix this"))
    assert thread.blocked is True
    thread = add_review_comment(
        thread, _comment(ReviewDecisionKind.COMMENT, "fixed in the latest run")
    )
    # a plain comment never clears (or re-raises) a standing decision
    assert thread.blocked is True
    thread = add_review_comment(thread, _comment(ReviewDecisionKind.APPROVE, "looks good now"))
    assert thread.blocked is False
    assert thread.reviewed is True


def test_a_later_request_changes_re_blocks_an_approved_run() -> None:
    thread = RunReviewThread(run_id=RUN_ID)
    thread = add_review_comment(thread, _comment(ReviewDecisionKind.APPROVE))
    assert thread.blocked is False
    thread = add_review_comment(
        thread, _comment(ReviewDecisionKind.REQUEST_CHANGES, "actually this regressed")
    )
    assert thread.blocked is True


def test_an_empty_thread_is_neither_blocked_nor_reviewed() -> None:
    thread = RunReviewThread(run_id=RUN_ID)
    assert thread.blocked is False
    assert thread.reviewed is False


def test_comments_are_recorded_in_order() -> None:
    thread = RunReviewThread(run_id=RUN_ID)
    thread = add_review_comment(thread, _comment(ReviewDecisionKind.COMMENT, "first"))
    thread = add_review_comment(thread, _comment(ReviewDecisionKind.COMMENT, "second"))
    assert [comment.body for comment in thread.comments] == ["first", "second"]


def test_a_comment_requires_a_non_empty_body() -> None:
    with pytest.raises(ValueError, match="non-empty body"):
        ReviewComment(
            run_id=RUN_ID,
            reviewer_actor_id="reviewer-1",
            decision=ReviewDecisionKind.COMMENT,
            body="   ",
            created_at=AT,
        )


def test_a_comment_requires_a_timezone_aware_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone"):
        ReviewComment(
            run_id=RUN_ID,
            reviewer_actor_id="reviewer-1",
            decision=ReviewDecisionKind.COMMENT,
            body="hello",
            created_at=datetime(2026, 1, 1),
        )


def test_a_comment_requires_a_reviewer_actor_id() -> None:
    with pytest.raises(ValueError, match="reviewer"):
        ReviewComment(
            run_id=RUN_ID,
            reviewer_actor_id="   ",
            decision=ReviewDecisionKind.COMMENT,
            body="hello",
            created_at=AT,
        )


def test_adding_a_comment_for_a_different_run_to_a_thread_is_rejected() -> None:
    thread = RunReviewThread(run_id=RUN_ID)
    other_run_comment = ReviewComment(
        run_id="run-2",
        reviewer_actor_id="reviewer-1",
        decision=ReviewDecisionKind.COMMENT,
        body="wrong thread",
        created_at=AT,
    )
    with pytest.raises(ValueError, match="cannot be added"):
        add_review_comment(thread, other_run_comment)


def test_add_review_comment_never_mutates_the_original_thread() -> None:
    thread = RunReviewThread(run_id=RUN_ID)
    new_thread = add_review_comment(thread, _comment(ReviewDecisionKind.COMMENT))
    assert thread.comments == ()
    assert len(new_thread.comments) == 1
