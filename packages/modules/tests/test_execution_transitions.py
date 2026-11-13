"""R1-21: execution state machine, authorized only when the recovery
precondition for the declared mutation class is present (ADR-010).

Synthetic/fixture mutations of each class exercise the gate, the same
pattern R0-19 used for the classification matrix
(packages/kernel/tests/test_classification_model.py) — no real Class C
adapter exists or may be added here (ADR-010: R1 validates the gate against
a deterministic test adapter only).
"""

import pytest
from cairn_kernel.classification.model import CompensationContract, RecoveryStrategy
from cairn_kernel.errors import (
    InvalidStateTransitionError,
    RecoveryPlanRequiredError,
    RevisionMismatchError,
    RiskAcceptanceRequiredError,
)
from cairn_kernel.hex.primitives import MutationClass
from cairn_modules.approvals.model import ApprovalRecord, ApprovalState
from cairn_modules.execution.model import (
    ALLOWED_EXECUTION_TRANSITIONS,
    ExecutionState,
    authorize_execution,
    validate_execution_transition,
)

TENANT = "11111111-1111-1111-1111-111111111111"
PROJECT = "22222222-2222-2222-2222-222222222222"
REVISION_ID = "33333333-3333-3333-3333-333333333333"
REVISION_HASH = "sha256:abc123"


def _approval(mutation_class: MutationClass, **overrides: object) -> ApprovalRecord:
    fields: dict[str, object] = {
        "approval_id": "55555555-5555-5555-5555-555555555555",
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "subject_kind": "MIGRATION_PLAN",
        "subject_id": "44444444-4444-4444-4444-444444444444",
        "revision_id": REVISION_ID,
        "revision_hash": REVISION_HASH,
        "mutation_class": mutation_class,
        "risk_tier": "LOW",
        "state": ApprovalState.APPROVED,
        "proposer_actor_id": "bob",
        "approver_actor_id": "alice",
    }
    fields.update(overrides)
    return ApprovalRecord(**fields)  # type: ignore[arg-type]


def _contract(strategy: RecoveryStrategy) -> CompensationContract:
    return CompensationContract(
        strategy=strategy,
        plan_ref="recovery-plan://example/plan-1",
        preconditions="target resource identified, scoped and validated",
        authority="PROJECT_OWNER",
        evidence="before/after state capture",
        failure_handling="escalate to incident; execution stays FAILED",
    )


# --- authorization blocked when the recovery precondition is absent,
# per synthetic fixture of each mutation class -----------------------------


def test_read_only_authorizes_without_any_compensation_contract() -> None:
    authorize_execution(
        _approval(MutationClass.READ_ONLY),
        revision_id=REVISION_ID,
        revision_hash=REVISION_HASH,
        compensation=None,
    )  # does not raise


def test_internal_mutation_authorizes_without_any_compensation_contract() -> None:
    authorize_execution(
        _approval(MutationClass.INTERNAL_MUTATION),
        revision_id=REVISION_ID,
        revision_hash=REVISION_HASH,
        compensation=None,
    )  # does not raise


def test_reversible_mutation_blocked_when_recovery_precondition_absent() -> None:
    with pytest.raises(RecoveryPlanRequiredError):
        authorize_execution(
            _approval(MutationClass.REVERSIBLE_EXTERNAL_MUTATION),
            revision_id=REVISION_ID,
            revision_hash=REVISION_HASH,
            compensation=None,
        )


def test_reversible_mutation_authorizes_with_rollback_contract() -> None:
    authorize_execution(
        _approval(MutationClass.REVERSIBLE_EXTERNAL_MUTATION),
        revision_id=REVISION_ID,
        revision_hash=REVISION_HASH,
        compensation=_contract(RecoveryStrategy.ROLLBACK),
    )  # does not raise


def test_reversible_mutation_rejects_the_wrong_strategy() -> None:
    with pytest.raises(RecoveryPlanRequiredError):
        authorize_execution(
            _approval(MutationClass.REVERSIBLE_EXTERNAL_MUTATION),
            revision_id=REVISION_ID,
            revision_hash=REVISION_HASH,
            compensation=_contract(RecoveryStrategy.COMPENSATE),
        )


def test_compensatable_mutation_blocked_when_recovery_precondition_absent() -> None:
    with pytest.raises(RecoveryPlanRequiredError):
        authorize_execution(
            _approval(MutationClass.COMPENSATABLE_EXTERNAL_MUTATION),
            revision_id=REVISION_ID,
            revision_hash=REVISION_HASH,
            compensation=None,
        )


def test_compensatable_mutation_authorizes_with_compensate_contract() -> None:
    authorize_execution(
        _approval(MutationClass.COMPENSATABLE_EXTERNAL_MUTATION),
        revision_id=REVISION_ID,
        revision_hash=REVISION_HASH,
        compensation=_contract(RecoveryStrategy.COMPENSATE),
    )  # does not raise


def test_irreversible_mutation_blocked_when_risk_acceptance_absent() -> None:
    with pytest.raises(RiskAcceptanceRequiredError):
        authorize_execution(
            _approval(MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION),
            revision_id=REVISION_ID,
            revision_hash=REVISION_HASH,
            compensation=None,
        )


def test_irreversible_mutation_rejects_a_rollback_promise() -> None:
    with pytest.raises(RiskAcceptanceRequiredError):
        authorize_execution(
            _approval(MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION),
            revision_id=REVISION_ID,
            revision_hash=REVISION_HASH,
            compensation=_contract(RecoveryStrategy.ROLLBACK),
        )


def test_irreversible_mutation_authorizes_with_explicit_risk_acceptance() -> None:
    authorize_execution(
        _approval(MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION),
        revision_id=REVISION_ID,
        revision_hash=REVISION_HASH,
        compensation=_contract(RecoveryStrategy.ACCEPT_IRREVERSIBLE),
    )  # does not raise


# --- revision binding is re-checked at authorization time -----------------


def test_authorization_blocked_when_approval_not_approved() -> None:
    with pytest.raises(InvalidStateTransitionError):
        authorize_execution(
            _approval(MutationClass.INTERNAL_MUTATION, state=ApprovalState.PENDING_APPROVAL),
            revision_id=REVISION_ID,
            revision_hash=REVISION_HASH,
            compensation=None,
        )


def test_authorization_blocked_on_revision_hash_mismatch() -> None:
    with pytest.raises(RevisionMismatchError):
        authorize_execution(
            _approval(MutationClass.INTERNAL_MUTATION),
            revision_id=REVISION_ID,
            revision_hash="sha256:tampered",
            compensation=None,
        )


# --- every legal and illegal execution transition --------------------------


LEGAL_EXECUTION_TRANSITIONS = [
    (ExecutionState.PROPOSED, ExecutionState.AUTHORIZED),
    (ExecutionState.PROPOSED, ExecutionState.CANCELLED),
    (ExecutionState.AUTHORIZED, ExecutionState.EXECUTING),
    (ExecutionState.AUTHORIZED, ExecutionState.CANCELLED),
    (ExecutionState.EXECUTING, ExecutionState.SUCCEEDED),
    (ExecutionState.EXECUTING, ExecutionState.FAILED),
    (ExecutionState.EXECUTING, ExecutionState.ROLLED_BACK),
    (ExecutionState.SUCCEEDED, ExecutionState.ROLLED_BACK),
]


@pytest.mark.parametrize(("current", "target"), LEGAL_EXECUTION_TRANSITIONS)
def test_legal_execution_transition_is_accepted_for_a_reversible_mutation(
    current: ExecutionState, target: ExecutionState
) -> None:
    validate_execution_transition(
        MutationClass.REVERSIBLE_EXTERNAL_MUTATION, current, target
    )  # does not raise


def _all_illegal_execution_transitions() -> list[tuple[ExecutionState, ExecutionState]]:
    pairs = []
    for current in ExecutionState:
        for target in ExecutionState:
            if (current, target) in LEGAL_EXECUTION_TRANSITIONS:
                continue
            pairs.append((current, target))
    return pairs


@pytest.mark.parametrize(("current", "target"), _all_illegal_execution_transitions())
def test_illegal_execution_transition_is_rejected(
    current: ExecutionState, target: ExecutionState
) -> None:
    with pytest.raises(InvalidStateTransitionError):
        validate_execution_transition(MutationClass.INTERNAL_MUTATION, current, target)


def test_self_transition_is_always_rejected() -> None:
    for state in ExecutionState:
        with pytest.raises(InvalidStateTransitionError):
            validate_execution_transition(MutationClass.INTERNAL_MUTATION, state, state)


def test_terminal_states_have_no_outgoing_transitions() -> None:
    for state in (ExecutionState.FAILED, ExecutionState.ROLLED_BACK, ExecutionState.CANCELLED):
        assert ALLOWED_EXECUTION_TRANSITIONS[state] == frozenset()


def test_irreversible_mutation_cannot_transition_to_rolled_back_from_executing() -> None:
    with pytest.raises(InvalidStateTransitionError):
        validate_execution_transition(
            MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION,
            ExecutionState.EXECUTING,
            ExecutionState.ROLLED_BACK,
        )


def test_irreversible_mutation_cannot_transition_to_rolled_back_from_succeeded() -> None:
    with pytest.raises(InvalidStateTransitionError):
        validate_execution_transition(
            MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION,
            ExecutionState.SUCCEEDED,
            ExecutionState.ROLLED_BACK,
        )


def test_reversible_mutation_can_roll_back_after_success() -> None:
    validate_execution_transition(
        MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
        ExecutionState.SUCCEEDED,
        ExecutionState.ROLLED_BACK,
    )  # does not raise
