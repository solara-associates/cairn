"""R3-07: diff review -- the engineer's "comment, request changes,
approve" annotation attached to a transformation run.

Spec S16's R3-07 row: "Engineer can review, comment, request changes."
This module is deliberately a thin annotation record, not a new workflow
state machine -- a transformation run has no ``DRAFT``/``IN_REVIEW``/
``APPROVED`` lifecycle of its own (unlike a mapping release, see below),
so this story's "review" is modelled as a growing, append-only thread of
comments attached to one run, each optionally carrying a decision.

**An existing comment/review model was checked for first, per this
unit's brief, before inventing a new one.** ``cairn_contracts.mapping.
model.ReviewDecision`` (ADR-004's mapping-release review step) is the
only existing "reviewer records an approve/reject decision with a
rationale" shape in this codebase -- but it is tightly coupled to
``MappingRelease``'s own ``DRAFT -> IN_REVIEW -> APPROVED -> PUBLISHED ->
RETIRED`` sequence (``ReviewDecision`` only makes sense against a release
already ``IN_REVIEW``), which a transformation run does not have and
this story does not ask for. ``cairn_modules.planning``'s disposition
accept/reject/amend actions are the other reviewer-shaped precedent in
this codebase (a reject carries a ``reason``, an amend carries a
``rationale``), but both are typed to ``Disposition``/workload decisions,
not a general-purpose annotation. This module borrows the same four
fields every one of those precedents already uses -- an actor, a body of
text, a timestamp, and (optionally) a decision -- rather than inventing
a fifth unrelated shape: ``ReviewComment.reviewer_actor_id``/``body``/
``created_at`` echo ``ReviewDecision.reviewer_actor_id``/``rationale``/
``decided_at`` by name and by role.

The one real difference from ``ReviewDecision``: this story's own
acceptance text names three actions ("review, comment, request
changes"), not two ("approve/reject"), and R3-07's brief explicitly asks
for "a lightweight annotation", not a gate. So ``ReviewDecisionKind`` has
three members (``COMMENT``, ``REQUEST_CHANGES``, ``APPROVE``) rather than
``ReviewDecision``'s bare ``approved: bool`` -- a plain comment carries
no decision at all, which a two-valued boolean cannot express without a
fabricated third state.

``RunReviewThread.blocked`` makes the "visibly blocking further
progress" half of this story's acceptance text (729/R3-05's own
"failures block approval, not advisory text" discipline, read onto
human review the same way) a real, queryable property: the most recent
decision-bearing comment -- ``REQUEST_CHANGES`` or ``APPROVE`` -- decides
whether the thread is blocked; a plain ``COMMENT`` never changes the
blocked state either way, since it carries no decision to supersede one.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ReviewDecisionKind(str, Enum):
    """The three actions R3-07's own acceptance text names by name."""

    COMMENT = "COMMENT"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    APPROVE = "APPROVE"


@dataclass(frozen=True, slots=True)
class ReviewComment:
    """One engineer's annotation on one transformation run.

    ``body`` must be non-empty (a comment with nothing said is not a
    comment) and ``created_at`` must be timezone-aware -- the same two
    invariants ``cairn_contracts.mapping.model.ReviewDecision``'s
    ``decided_at``/``MappingProposal``'s ``proposed_at`` already enforce
    for every other actor-attributed, timestamped record in this
    codebase.
    """

    run_id: str
    reviewer_actor_id: str
    decision: ReviewDecisionKind
    body: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("a review comment must name the run it is attached to")
        if not self.reviewer_actor_id.strip():
            raise ValueError("a review comment must name its reviewer")
        if not self.body.strip():
            raise ValueError("a review comment must have a non-empty body")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must include a timezone")


@dataclass(frozen=True, slots=True)
class RunReviewThread:
    """The full, ordered comment history for one transformation run."""

    run_id: str
    comments: tuple[ReviewComment, ...] = ()

    @property
    def blocked(self) -> bool:
        """True iff the most recent decision-bearing comment is
        ``REQUEST_CHANGES`` and no later ``APPROVE`` has cleared it.

        A plain ``COMMENT`` is skipped when looking for "the most recent
        decision" -- it carries no decision of its own to supersede a
        standing ``REQUEST_CHANGES``/``APPROVE``. An empty thread (no
        review has happened yet) is not blocked -- "nobody has reviewed
        this yet" is a different, honestly-reported state (see
        ``reviewed`` below), never silently read as either a pass or a
        block.
        """

        for comment in reversed(self.comments):
            if comment.decision is ReviewDecisionKind.REQUEST_CHANGES:
                return True
            if comment.decision is ReviewDecisionKind.APPROVE:
                return False
        return False

    @property
    def reviewed(self) -> bool:
        """True iff at least one comment carries a real decision
        (``REQUEST_CHANGES``/``APPROVE``) -- distinct from ``blocked``,
        so "nothing has reviewed this run yet" is never conflated with
        "this run was reviewed and approved"."""

        return any(
            comment.decision is not ReviewDecisionKind.COMMENT for comment in self.comments
        )


def add_review_comment(thread: RunReviewThread, comment: ReviewComment) -> RunReviewThread:
    """Appends ``comment`` to ``thread``, never mutating either in
    place -- the same immutable-dataclass discipline every other domain
    value in this module's siblings (``diff.py``/``validation.py``)
    already follows."""

    if comment.run_id != thread.run_id:
        raise ValueError(
            f"comment for run {comment.run_id!r} cannot be added to thread for "
            f"run {thread.run_id!r}"
        )
    return dataclasses.replace(thread, comments=thread.comments + (comment,))


__all__ = [
    "ReviewComment",
    "ReviewDecisionKind",
    "RunReviewThread",
    "add_review_comment",
]
