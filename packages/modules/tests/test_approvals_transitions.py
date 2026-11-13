"""R1-21: approval revision binding, state transitions and separation of
duties (ADR-009). Pure domain-model tests, no database — the identical
invariants are proven at rest by
tests/integration/test_revision_approval_execution_schema.py.
"""

from datetime import UTC, datetime

import pytest
from cairn_kernel.errors import (
    InvalidStateTransitionError,
    RevisionMismatchError,
    SeparationOfDutiesError,
)
from cairn_kernel.hex.primitives import MutationClass
from cairn_modules.approvals.model import (
    ALLOWED_APPROVAL_TRANSITIONS,
    ApprovalRecord,
    ApprovalState,
    RevisionRecord,
    bind_approval_to_revision,
    check_separation_of_duties,
    validate_approval_transition,
)

TENANT = "11111111-1111-1111-1111-111111111111"
PROJECT = "22222222-2222-2222-2222-222222222222"


def _revision(**overrides: object) -> RevisionRecord:
    fields = {
        "revision_id": "33333333-3333-3333-3333-333333333333",
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "subject_kind": "MIGRATION_PLAN",
        "subject_id": "44444444-4444-4444-4444-444444444444",
        "revision_number": 1,
        "content_hash": "sha256:abc123",
        "input_versions": (("estate_model", "v1"),),
        "created_by": "alice",
        "created_at": datetime(2026, 11, 13, tzinfo=UTC),
    }
    fields.update(overrides)
    return RevisionRecord(**fields)  # type: ignore[arg-type]


def _approval(**overrides: object) -> ApprovalRecord:
    fields = {
        "approval_id": "55555555-5555-5555-5555-555555555555",
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "subject_kind": "MIGRATION_PLAN",
        "subject_id": "44444444-4444-4444-4444-444444444444",
        "revision_id": "33333333-3333-3333-3333-333333333333",
        "revision_hash": "sha256:abc123",
        "mutation_class": MutationClass.INTERNAL_MUTATION,
        "risk_tier": "LOW",
        "state": ApprovalState.DRAFT,
        "proposer_actor_id": "bob",
    }
    fields.update(overrides)
    return ApprovalRecord(**fields)  # type: ignore[arg-type]


# --- revision model -----------------------------------------------------


def test_revision_number_must_start_at_one() -> None:
    with pytest.raises(ValueError, match="revision_number"):
        _revision(revision_number=0)


def test_revision_content_hash_must_not_be_blank() -> None:
    with pytest.raises(ValueError, match="content_hash"):
        _revision(content_hash="")


# --- approval binds to an immutable revision ----------------------------


def test_approval_binds_to_the_exact_revision_and_hash() -> None:
    bind_approval_to_revision(_approval(), _revision())  # does not raise


def test_approval_bound_to_wrong_revision_id_is_rejected() -> None:
    other = _revision(revision_id="99999999-9999-9999-9999-999999999999")
    with pytest.raises(RevisionMismatchError):
        bind_approval_to_revision(_approval(), other)


def test_approval_bound_to_wrong_hash_is_rejected() -> None:
    other = _revision(content_hash="sha256:different")
    with pytest.raises(RevisionMismatchError):
        bind_approval_to_revision(_approval(), other)


def test_approval_bound_to_wrong_subject_is_rejected() -> None:
    other = _revision(subject_id="66666666-6666-6666-6666-666666666666")
    with pytest.raises(RevisionMismatchError):
        bind_approval_to_revision(_approval(), other)


# --- every legal and illegal approval transition ------------------------


LEGAL_APPROVAL_TRANSITIONS = [
    (ApprovalState.DRAFT, ApprovalState.PENDING_APPROVAL),
    (ApprovalState.DRAFT, ApprovalState.CANCELLED),
    (ApprovalState.PENDING_APPROVAL, ApprovalState.APPROVED),
    (ApprovalState.PENDING_APPROVAL, ApprovalState.REJECTED),
    (ApprovalState.PENDING_APPROVAL, ApprovalState.CANCELLED),
    (ApprovalState.APPROVED, ApprovalState.CONSUMED),
    (ApprovalState.APPROVED, ApprovalState.EXPIRED),
]


@pytest.mark.parametrize(("current", "target"), LEGAL_APPROVAL_TRANSITIONS)
def test_legal_approval_transition_is_accepted(
    current: ApprovalState, target: ApprovalState
) -> None:
    validate_approval_transition(current, target)  # does not raise


def _all_illegal_approval_transitions() -> list[tuple[ApprovalState, ApprovalState]]:
    pairs = []
    for current in ApprovalState:
        for target in ApprovalState:
            if (current, target) in LEGAL_APPROVAL_TRANSITIONS:
                continue
            pairs.append((current, target))
    return pairs


@pytest.mark.parametrize(("current", "target"), _all_illegal_approval_transitions())
def test_illegal_approval_transition_is_rejected(
    current: ApprovalState, target: ApprovalState
) -> None:
    with pytest.raises(InvalidStateTransitionError):
        validate_approval_transition(current, target)


def test_self_transition_is_always_rejected() -> None:
    for state in ApprovalState:
        with pytest.raises(InvalidStateTransitionError):
            validate_approval_transition(state, state)


def test_terminal_states_have_no_outgoing_transitions() -> None:
    for state in (
        ApprovalState.REJECTED,
        ApprovalState.CANCELLED,
        ApprovalState.CONSUMED,
        ApprovalState.EXPIRED,
    ):
        assert ALLOWED_APPROVAL_TRANSITIONS[state] == frozenset()


# --- separation of duties ------------------------------------------------


def test_separation_of_duties_allows_a_different_approver() -> None:
    check_separation_of_duties("bob", "alice")  # does not raise


def test_separation_of_duties_rejects_the_proposer_as_approver() -> None:
    with pytest.raises(SeparationOfDutiesError):
        check_separation_of_duties("bob", "bob")
