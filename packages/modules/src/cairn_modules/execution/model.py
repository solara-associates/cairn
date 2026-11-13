"""Execution state machine, mutation-class authorization and the
compensation contract (ADR-010).

``CompensationContract`` and ``RecoveryStrategy`` are the same types R0-19's
classification matrix already defined in
``cairn_kernel.classification.model`` (the matrix classifies *what a
surface declares*; this module enforces the same contract *at authorization
time*, against a specific proposed execution) — reused rather than
redefined, so the two can never silently drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from cairn_kernel.classification.model import (
    EXTERNAL_MUTATION_CLASSES,
    STRATEGY_BY_MUTATION,
    CompensationContract,
    RecoveryStrategy,
)
from cairn_kernel.errors import (
    InvalidStateTransitionError,
    RecoveryPlanRequiredError,
    RevisionMismatchError,
    RiskAcceptanceRequiredError,
)
from cairn_kernel.hex.primitives import MutationClass

from cairn_modules.approvals.model import ApprovalRecord, ApprovalState


class ExecutionState(str, Enum):
    PROPOSED = "PROPOSED"
    AUTHORIZED = "AUTHORIZED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"
    CANCELLED = "CANCELLED"


# ADR-009 "State transitions" section, execution half. An irreversible
# mutation cannot transition to ROLLED_BACK (ADR-010 Class C rule 8) — that
# is enforced per-record in ``validate_execution_transition`` because it
# depends on the record's mutation class, not on state alone.
ALLOWED_EXECUTION_TRANSITIONS: dict[ExecutionState, frozenset[ExecutionState]] = {
    ExecutionState.PROPOSED: frozenset({ExecutionState.AUTHORIZED, ExecutionState.CANCELLED}),
    ExecutionState.AUTHORIZED: frozenset(
        {ExecutionState.EXECUTING, ExecutionState.CANCELLED}
    ),
    ExecutionState.EXECUTING: frozenset(
        {ExecutionState.SUCCEEDED, ExecutionState.FAILED, ExecutionState.ROLLED_BACK}
    ),
    ExecutionState.SUCCEEDED: frozenset({ExecutionState.ROLLED_BACK}),
    ExecutionState.FAILED: frozenset(),
    ExecutionState.ROLLED_BACK: frozenset(),
    ExecutionState.CANCELLED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    """An ``execution_record`` row (ADR-009), bound to one approval and revision."""

    execution_id: str
    tenant_id: str
    project_id: str
    approval_id: str
    revision_id: str
    approved_hash: str
    mutation_class: MutationClass
    state: ExecutionState
    actor_id: str
    correlation_id: str


def validate_execution_transition(
    mutation_class: MutationClass, current: ExecutionState, target: ExecutionState
) -> None:
    """Reject any transition not in ``ALLOWED_EXECUTION_TRANSITIONS``, and
    reject ``ROLLED_BACK`` for an irreversible mutation regardless (ADR-010:
    "An irreversible mutation cannot transition to ``ROLLED_BACK``")."""

    allowed = ALLOWED_EXECUTION_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidStateTransitionError(
            f"execution cannot move from {current.value} to {target.value}"
        )
    if (
        target is ExecutionState.ROLLED_BACK
        and mutation_class is MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION
    ):
        raise InvalidStateTransitionError(
            "an IRREVERSIBLE_EXTERNAL_MUTATION execution cannot transition to ROLLED_BACK"
        )


def authorize_execution(
    approval: ApprovalRecord,
    *,
    revision_id: str,
    revision_hash: str,
    compensation: CompensationContract | None,
) -> None:
    """Authorize a proposed execution against its approval (ADR-009/ADR-010).

    Fails closed (raises, no external effect) when:
      - the approval is not ``APPROVED`` (``InvalidStateTransitionError``),
      - the revision the execution names does not match the approval's bound
        revision/hash (``RevisionMismatchError`` -> ``REVISION_MISMATCH``),
      - the mutation class is external and the recovery precondition for
        that class — a compensation contract with the matching strategy and
        every element populated — is absent (``RecoveryPlanRequiredError``),
      - the mutation class is irreversible and the contract was not built
        with ``ACCEPT_IRREVERSIBLE`` (``RiskAcceptanceRequiredError``).

    ``READ_ONLY`` and ``INTERNAL_MUTATION`` never require a compensation
    contract (ADR-010: "No external recovery required") and are authorized
    once the approval and revision checks pass.
    """

    if approval.state is not ApprovalState.APPROVED:
        raise InvalidStateTransitionError(
            f"approval {approval.approval_id} is {approval.state.value}, not APPROVED"
        )
    if approval.revision_id != revision_id or approval.revision_hash != revision_hash:
        raise RevisionMismatchError(
            f"execution names revision {revision_id}/{revision_hash}, approval"
            f" {approval.approval_id} is bound to {approval.revision_id}/{approval.revision_hash}"
        )

    if approval.mutation_class not in EXTERNAL_MUTATION_CLASSES:
        return

    if compensation is None:
        if approval.mutation_class is MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION:
            raise RiskAcceptanceRequiredError(
                "an irreversible mutation requires explicit risk acceptance"
                " before authorization"
            )
        raise RecoveryPlanRequiredError(
            f"{approval.mutation_class.value} requires a compensation contract"
            " before authorization"
        )

    expected_strategy = STRATEGY_BY_MUTATION[approval.mutation_class]
    if compensation.strategy is not expected_strategy:
        if approval.mutation_class is MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION:
            # ADR-010: irreversible mutations carry no rollback promise; the
            # only valid precondition is an explicit, recorded risk
            # acceptance. A strategy mismatch here specifically means that
            # acceptance is missing, not merely that a plan is incomplete.
            raise RiskAcceptanceRequiredError(
                "an irreversible mutation requires explicit risk acceptance"
                f" (strategy {RecoveryStrategy.ACCEPT_IRREVERSIBLE.value}) before"
                f" authorization, got {compensation.strategy.value}"
            )
        raise RecoveryPlanRequiredError(
            f"{approval.mutation_class.value} requires recovery strategy"
            f" {expected_strategy.value}, got {compensation.strategy.value}"
        )
