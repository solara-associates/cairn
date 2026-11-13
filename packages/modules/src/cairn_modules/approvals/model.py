"""Immutable revision and approval-binding domain model (ADR-009).

This module is the application-layer mirror of the database constraints in
``packages/adapters/src/cairn_adapters/persistence_postgres/migrations/
0005_revision_approval_execution.up.sql``. Both layers enforce the same
invariants independently: the database is the source of truth (a bug here
cannot create an illegal row), and this layer gives callers a fast,
dependency-free way to reject an illegal operation before it reaches the
database, with an error type the caller can act on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from cairn_kernel.errors import (
    InvalidStateTransitionError,
    RevisionMismatchError,
    SeparationOfDutiesError,
)
from cairn_kernel.hex.primitives import MutationClass


class ApprovalState(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


# ADR-009 "State transitions" section, approval half.
ALLOWED_APPROVAL_TRANSITIONS: dict[ApprovalState, frozenset[ApprovalState]] = {
    ApprovalState.DRAFT: frozenset({ApprovalState.PENDING_APPROVAL, ApprovalState.CANCELLED}),
    ApprovalState.PENDING_APPROVAL: frozenset(
        {ApprovalState.APPROVED, ApprovalState.REJECTED, ApprovalState.CANCELLED}
    ),
    ApprovalState.APPROVED: frozenset({ApprovalState.CONSUMED, ApprovalState.EXPIRED}),
    ApprovalState.REJECTED: frozenset(),
    ApprovalState.CANCELLED: frozenset(),
    ApprovalState.CONSUMED: frozenset(),
    ApprovalState.EXPIRED: frozenset(),
}


def validate_approval_transition(current: ApprovalState, target: ApprovalState) -> None:
    """Reject any transition not named in ``ALLOWED_APPROVAL_TRANSITIONS``.

    A self-transition (``current == target``) is always rejected: every
    transition in ADR-009's diagram moves to a distinct state, and silently
    accepting a no-op transition would hide a caller bug that thinks it
    changed state when it did not.
    """

    allowed = ALLOWED_APPROVAL_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidStateTransitionError(
            f"approval cannot move from {current.value} to {target.value}"
        )


@dataclass(frozen=True, slots=True)
class RevisionRecord:
    """A ``subject_revision`` row (ADR-009): append-only, never mutated."""

    revision_id: str
    tenant_id: str
    project_id: str
    subject_kind: str
    subject_id: str
    revision_number: int
    content_hash: str
    input_versions: tuple[tuple[str, str], ...]
    created_by: str
    created_at: datetime

    def __post_init__(self) -> None:
        if self.revision_number < 1:
            raise ValueError("revision_number must start at 1 and increase monotonically")
        if not self.content_hash.strip():
            raise ValueError("content_hash must not be blank")


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    """An ``approval`` row (ADR-009), bound to one exact revision and hash."""

    approval_id: str
    tenant_id: str
    project_id: str
    subject_kind: str
    subject_id: str
    revision_id: str
    revision_hash: str
    mutation_class: MutationClass
    risk_tier: str
    state: ApprovalState
    proposer_actor_id: str
    approver_actor_id: str | None = None


def bind_approval_to_revision(approval: ApprovalRecord, revision: RevisionRecord) -> None:
    """Enforce ADR-009's binding: the approval must name the exact revision and hash.

    Raises ``RevisionMismatchError`` (fail closed, no external effect) when the
    approval's ``revision_id``/``revision_hash`` do not match the revision row
    it claims to bind to, or when the subject identity differs — the database
    composite foreign key enforces the same rule at rest; this is the
    application-layer check that can run before any write is attempted.
    """

    if approval.revision_id != revision.revision_id:
        raise RevisionMismatchError(
            f"approval {approval.approval_id} names revision {approval.revision_id},"
            f" not {revision.revision_id}"
        )
    if approval.revision_hash != revision.content_hash:
        raise RevisionMismatchError(
            f"approval {approval.approval_id} revision_hash does not match"
            f" subject_revision {revision.revision_id} content_hash"
        )
    if (approval.tenant_id, approval.project_id, approval.subject_kind, approval.subject_id) != (
        revision.tenant_id,
        revision.project_id,
        revision.subject_kind,
        revision.subject_id,
    ):
        raise RevisionMismatchError(
            f"approval {approval.approval_id} subject identity does not match"
            f" revision {revision.revision_id}"
        )


def check_separation_of_duties(proposer_actor_id: str, approver_actor_id: str) -> None:
    """ADR-009 "Separation of duties": the proposer cannot be the sole approver.

    Admin role does not bypass this (ADR-009): callers must pass the actor id
    that will actually record the decision, not a role name, so a tenant
    admin approving their own proposal is rejected the same as anyone else.
    """

    if proposer_actor_id == approver_actor_id:
        raise SeparationOfDutiesError(
            f"actor {proposer_actor_id!r} proposed this change and cannot also approve it"
        )
