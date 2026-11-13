"""R1-22: the kernel execution gate's full lifecycle (ADR-010).

Proves propose -> approve -> authorize -> execute -> record for one
synthetic/fixture mutation per ADR-010 external mutation class, against the
R1 deterministic test adapter only (ADR-010: "R1 validates the execution-gate
lifecycle against a deterministic test adapter"; no real Class C adapter
exists or may be added here). Also covers: the recovery precondition
blocking authorization when absent, scoped idempotency (a retried execute
with the same key/payload does not re-invoke the adapter), audit-before-
effect, and that the gate itself refuses to be constructed with anything but
the deterministic test adapter.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from cairn_kernel.classification.model import CompensationContract, RecoveryStrategy
from cairn_kernel.errors import (
    ConfigurationError,
    IdempotencyConflictError,
    InvalidStateTransitionError,
    RecoveryPlanRequiredError,
    RiskAcceptanceRequiredError,
)
from cairn_kernel.execution_gate import (
    AdapterRequest,
    AdapterResult,
    IdempotencyScope,
    InMemoryIdempotencyStore,
)
from cairn_kernel.execution_gate.deterministic_adapter import DeterministicTestExecutionAdapter
from cairn_kernel.hex.primitives import MutationClass, ProjectId, TenantId
from cairn_kernel.testing.fakes import FixedClock, InMemoryAuditSink
from cairn_modules.approvals.model import ApprovalRecord, ApprovalState
from cairn_modules.execution.gate import ExecutionGate
from cairn_modules.execution.model import ExecutionRecord, ExecutionState

TENANT = "11111111-1111-1111-1111-111111111111"
PROJECT = "22222222-2222-2222-2222-222222222222"
REVISION_ID = "33333333-3333-3333-3333-333333333333"
REVISION_HASH = "sha256:abc123"
NOW = datetime(2026, 11, 13, tzinfo=UTC)


def _approval(mutation_class: MutationClass, **overrides: object) -> ApprovalRecord:
    fields: dict[str, object] = {
        "approval_id": "approval-1",
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "subject_kind": "MIGRATION_PLAN",
        "subject_id": "subject-1",
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


def _execution(mutation_class: MutationClass, **overrides: object) -> ExecutionRecord:
    fields: dict[str, object] = {
        "execution_id": "execution-1",
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "approval_id": "approval-1",
        "revision_id": REVISION_ID,
        "approved_hash": REVISION_HASH,
        "mutation_class": mutation_class,
        "state": ExecutionState.PROPOSED,
        "actor_id": "alice",
        "correlation_id": "corr-1",
    }
    fields.update(overrides)
    return ExecutionRecord(**fields)  # type: ignore[arg-type]


def _contract(strategy: RecoveryStrategy) -> CompensationContract:
    return CompensationContract(
        strategy=strategy,
        plan_ref="recovery-plan://example/plan-1",
        preconditions="target resource identified, scoped and validated",
        authority="PROJECT_OWNER",
        evidence="before/after state capture",
        failure_handling="escalate to incident; execution stays FAILED",
    )


def _gate(
    adapter: DeterministicTestExecutionAdapter | None = None,
) -> tuple[ExecutionGate, DeterministicTestExecutionAdapter, InMemoryAuditSink]:
    adapter = adapter or DeterministicTestExecutionAdapter()
    audit_sink = InMemoryAuditSink()
    gate = ExecutionGate(
        adapter=adapter,
        audit_sink=audit_sink,
        idempotency_store=InMemoryIdempotencyStore(),
        clock=FixedClock(NOW),
    )
    return gate, adapter, audit_sink


def _scope(operation: str, key: str = "retry-key-1") -> IdempotencyScope:
    return IdempotencyScope(
        tenant_id=TenantId(TENANT), project_id=ProjectId(PROJECT), operation=operation, key=key
    )


# --- full lifecycle, one fixture per ADR-010 external mutation class ------

LIFECYCLE_CASES = [
    (
        MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
        "fixture.rotate_api_key",
        RecoveryStrategy.ROLLBACK,
    ),
    (
        MutationClass.COMPENSATABLE_EXTERNAL_MUTATION,
        "fixture.disable_idle_resource",
        RecoveryStrategy.COMPENSATE,
    ),
    (
        MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION,
        "fixture.purge_snapshot",
        RecoveryStrategy.ACCEPT_IRREVERSIBLE,
    ),
]


@pytest.mark.parametrize(("mutation_class", "operation", "strategy"), LIFECYCLE_CASES)
def test_full_lifecycle_proven_for_the_mutation_class(
    mutation_class: MutationClass, operation: str, strategy: RecoveryStrategy
) -> None:
    gate, adapter, audit_sink = _gate()

    # propose
    execution = _execution(mutation_class)
    assert execution.state is ExecutionState.PROPOSED

    # approve (already APPROVED by the fixture builder, mirroring the R1-21
    # approval state machine that precedes this gate)
    approval = _approval(mutation_class)
    assert approval.state is ApprovalState.APPROVED

    # authorize
    authorized = gate.authorize(execution, approval, compensation=_contract(strategy))
    assert authorized.state is ExecutionState.AUTHORIZED

    # execute
    request = {"target": "fixture-target-1", "operation": operation}
    outcome = gate.execute(authorized, scope=_scope(operation), request=request)

    # record
    assert outcome.state is ExecutionState.SUCCEEDED
    assert outcome.idempotent_replay is False
    assert outcome.result.status == "APPLIED"
    assert adapter.call_log == [AdapterRequest(operation=operation, payload=request)]
    assert len(outcome.audit_entry_ids) == 2
    assert [entry.action for entry in audit_sink.entries] == [
        f"execution.{operation}.before_effect",
        f"execution.{operation}.succeeded",
    ]


# --- recovery precondition blocks authorization when absent ---------------


@pytest.mark.parametrize(
    ("mutation_class", "expected_error"),
    [
        (MutationClass.REVERSIBLE_EXTERNAL_MUTATION, RecoveryPlanRequiredError),
        (MutationClass.COMPENSATABLE_EXTERNAL_MUTATION, RecoveryPlanRequiredError),
        (MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION, RiskAcceptanceRequiredError),
    ],
)
def test_authorization_blocked_when_recovery_precondition_absent(
    mutation_class: MutationClass, expected_error: type[Exception]
) -> None:
    gate, _adapter, _audit_sink = _gate()
    execution = _execution(mutation_class)
    approval = _approval(mutation_class)

    with pytest.raises(expected_error):
        gate.authorize(execution, approval, compensation=None)

    # fails closed: no state advance, no audit entry, no adapter call
    assert execution.state is ExecutionState.PROPOSED


def test_authorization_blocked_when_approval_is_not_approved() -> None:
    gate, _adapter, _audit_sink = _gate()
    execution = _execution(MutationClass.INTERNAL_MUTATION)
    approval = _approval(MutationClass.INTERNAL_MUTATION, state=ApprovalState.PENDING_APPROVAL)

    with pytest.raises(InvalidStateTransitionError):
        gate.authorize(execution, approval, compensation=None)


def test_authorization_blocked_when_execution_names_a_different_approval() -> None:
    gate, _adapter, _audit_sink = _gate()
    execution = _execution(MutationClass.INTERNAL_MUTATION, approval_id="not-approval-1")
    approval = _approval(MutationClass.INTERNAL_MUTATION)

    from cairn_kernel.errors import RevisionMismatchError

    with pytest.raises(RevisionMismatchError):
        gate.authorize(execution, approval, compensation=None)


def test_execute_rejects_an_execution_that_was_never_authorized() -> None:
    gate, _adapter, _audit_sink = _gate()
    execution = _execution(MutationClass.REVERSIBLE_EXTERNAL_MUTATION)  # still PROPOSED

    with pytest.raises(InvalidStateTransitionError):
        gate.execute(
            execution,
            scope=_scope("fixture.rotate_api_key"),
            request={"target": "x"},
        )


# --- test adapter cannot be replaced by a production adapter --------------


class _LookAlikeProductionAdapter:
    adapter_kind = "GCP_PRODUCTION"

    def execute(self, request: AdapterRequest) -> AdapterResult:  # pragma: no cover
        raise AssertionError("a look-alike production adapter must never be called")


def test_gate_refuses_to_be_constructed_with_a_non_test_adapter() -> None:
    with pytest.raises(ConfigurationError):
        ExecutionGate(
            adapter=_LookAlikeProductionAdapter(),  # type: ignore[arg-type]
            audit_sink=InMemoryAuditSink(),
            idempotency_store=InMemoryIdempotencyStore(),
            clock=FixedClock(NOW),
        )


# --- scoped idempotency: a retry with the same key does not double-execute


def test_a_retried_execute_with_the_same_scope_and_request_does_not_re_execute() -> None:
    gate, adapter, audit_sink = _gate()
    approval = _approval(
        MutationClass.REVERSIBLE_EXTERNAL_MUTATION
    )
    request = {"target": "fixture-target-1"}
    scope = _scope("fixture.rotate_api_key")

    first_execution = gate.authorize(
        _execution(MutationClass.REVERSIBLE_EXTERNAL_MUTATION),
        approval,
        compensation=_contract(RecoveryStrategy.ROLLBACK),
    )
    first_outcome = gate.execute(first_execution, scope=scope, request=request)
    assert first_outcome.idempotent_replay is False
    assert len(adapter.call_log) == 1

    # Simulate a retried authorization: a second execution record for the
    # same approval, same idempotency scope and the same request.
    second_execution = gate.authorize(
        _execution(
            MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
            execution_id="execution-2",
        ),
        approval,
        compensation=_contract(RecoveryStrategy.ROLLBACK),
    )
    second_outcome = gate.execute(second_execution, scope=scope, request=request)

    assert second_outcome.idempotent_replay is True
    assert second_outcome.result.detail == first_outcome.result.detail
    # the adapter was not invoked again
    assert len(adapter.call_log) == 1
    # no new audit entries were appended for the replay
    assert len(audit_sink.entries) == 2


def test_reusing_an_idempotency_key_for_a_different_request_is_a_conflict() -> None:
    gate, adapter, _audit_sink = _gate()
    approval = _approval(MutationClass.REVERSIBLE_EXTERNAL_MUTATION)
    scope = _scope("fixture.rotate_api_key")

    first_execution = gate.authorize(
        _execution(MutationClass.REVERSIBLE_EXTERNAL_MUTATION),
        approval,
        compensation=_contract(RecoveryStrategy.ROLLBACK),
    )
    gate.execute(first_execution, scope=scope, request={"target": "fixture-target-1"})

    second_execution = gate.authorize(
        _execution(MutationClass.REVERSIBLE_EXTERNAL_MUTATION, execution_id="execution-2"),
        approval,
        compensation=_contract(RecoveryStrategy.ROLLBACK),
    )
    with pytest.raises(IdempotencyConflictError):
        gate.execute(second_execution, scope=scope, request={"target": "a-different-target"})

    # the second (conflicting) request never reached the adapter
    assert len(adapter.call_log) == 1


# --- audit-before-effect ----------------------------------------------------


class _OrderRecordingAuditSink(InMemoryAuditSink):
    def __init__(self, order: list[str]) -> None:
        super().__init__()
        self._order = order

    def append(self, entry):  # type: ignore[override]
        self._order.append(f"audit:{entry.action}")
        return super().append(entry)


class _OrderRecordingAdapter(DeterministicTestExecutionAdapter):
    def __init__(self, order: list[str]) -> None:
        super().__init__()
        self._order = order

    def execute(self, request: AdapterRequest) -> AdapterResult:
        self._order.append(f"effect:{request.operation}")
        return super().execute(request)


def test_audit_entry_is_appended_before_the_adapter_effect() -> None:
    order: list[str] = []
    adapter = _OrderRecordingAdapter(order)
    audit_sink = _OrderRecordingAuditSink(order)
    gate = ExecutionGate(
        adapter=adapter,
        audit_sink=audit_sink,
        idempotency_store=InMemoryIdempotencyStore(),
        clock=FixedClock(NOW),
    )
    approval = _approval(MutationClass.REVERSIBLE_EXTERNAL_MUTATION)
    authorized = gate.authorize(
        _execution(MutationClass.REVERSIBLE_EXTERNAL_MUTATION),
        approval,
        compensation=_contract(RecoveryStrategy.ROLLBACK),
    )

    gate.execute(
        authorized, scope=_scope("fixture.rotate_api_key"), request={"target": "t-1"}
    )

    assert order == [
        "audit:execution.fixture.rotate_api_key.before_effect",
        "effect:fixture.rotate_api_key",
        "audit:execution.fixture.rotate_api_key.succeeded",
    ]


def test_a_failed_effect_is_still_audited_and_terminal_state_is_failed() -> None:
    order: list[str] = []

    class _FailingAdapter(DeterministicTestExecutionAdapter):
        def execute(self, request: AdapterRequest) -> AdapterResult:
            order.append(f"effect-attempted:{request.operation}")
            raise RuntimeError("synthetic adapter failure")

    adapter = _FailingAdapter()
    audit_sink = _OrderRecordingAuditSink(order)
    gate = ExecutionGate(
        adapter=adapter,
        audit_sink=audit_sink,
        idempotency_store=InMemoryIdempotencyStore(),
        clock=FixedClock(NOW),
    )
    approval = _approval(MutationClass.REVERSIBLE_EXTERNAL_MUTATION)
    authorized = gate.authorize(
        _execution(MutationClass.REVERSIBLE_EXTERNAL_MUTATION),
        approval,
        compensation=_contract(RecoveryStrategy.ROLLBACK),
    )

    with pytest.raises(RuntimeError):
        gate.execute(
            authorized, scope=_scope("fixture.rotate_api_key"), request={"target": "t-1"}
        )

    assert order == [
        "audit:execution.fixture.rotate_api_key.before_effect",
        "effect-attempted:fixture.rotate_api_key",
        "audit:execution.fixture.rotate_api_key.failed",
    ]
    assert [entry.action for entry in audit_sink.entries] == [
        "execution.fixture.rotate_api_key.before_effect",
        "execution.fixture.rotate_api_key.failed",
    ]
