"""790 (R4-04a): the rollback/compensation engine (ADR-010's compensation-
contract table, "Failure handling" row).

Every test runs against ``FakeProviderExecutionAdapter`` (787) or a tiny,
deliberately-broken local test double -- never a real provider, no cloud
SDK, no network call. Covers all three ``RecoveryStrategy`` happy paths
(``ROLLBACK``, ``COMPENSATE``, ``ACCEPT_IRREVERSIBLE``) plus the
deliberate-break requirement: when recovery itself fails, the result is
``ExecutionState.FAILED`` with a populated ``IncidentRecord``, never a
silently reported ``SUCCEEDED`` (or ``ROLLED_BACK``).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from cairn_adapters.provider_execution.fake import FakeProviderExecutionAdapter
from cairn_adapters.provider_execution.ports import (
    ExecutionScope,
    RollbackRequest,
    RollbackResult,
)
from cairn_adapters.provider_execution.recovery import (
    EXPECTED_ROLLBACK_STATUS,
    RECOVERY_FAILURE_RUNBOOK,
    IncidentRecord,
    ReconciliationRecord,
    RecoveryEngine,
    RecoveryOutcome,
)
from cairn_kernel.classification.model import CompensationContract, RecoveryStrategy
from cairn_kernel.errors import InvalidStateTransitionError, ValidationError
from cairn_kernel.hex.primitives import MutationClass
from cairn_kernel.testing.fakes import FixedClock, FixedIdGenerator, InMemoryAuditSink
from cairn_modules.execution.model import ExecutionRecord, ExecutionState

TENANT = "11111111-1111-1111-1111-111111111111"
PROJECT = "22222222-2222-2222-2222-222222222222"
REVISION_ID = "33333333-3333-3333-3333-333333333333"
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def _execution(mutation_class: MutationClass, **overrides: object) -> ExecutionRecord:
    fields: dict[str, object] = {
        "execution_id": "execution-1",
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "approval_id": "approval-1",
        "revision_id": REVISION_ID,
        "approved_hash": "sha256:abc123",
        "mutation_class": mutation_class,
        "state": ExecutionState.EXECUTING,
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


def _scope(operation: str = "fixture.rotate_api_key") -> ExecutionScope:
    return ExecutionScope(
        tenant_id=TENANT, project_id=PROJECT, revision_id=REVISION_ID, operation=operation
    )


def _engine(
    adapter: object, audit_sink: InMemoryAuditSink | None = None
) -> tuple[RecoveryEngine, InMemoryAuditSink]:
    audit_sink = audit_sink or InMemoryAuditSink()
    engine = RecoveryEngine(
        provider_port=adapter,  # type: ignore[arg-type]
        audit_sink=audit_sink,
        clock=FixedClock(NOW),
        id_generator=FixedIdGenerator(),
    )
    return engine, audit_sink


# --- happy paths, one per RecoveryStrategy ---------------------------------


def test_rollback_strategy_happy_path_calls_adapter_rollback_and_reconciles() -> None:
    adapter = FakeProviderExecutionAdapter()
    engine, audit_sink = _engine(adapter)
    execution = _execution(MutationClass.REVERSIBLE_EXTERNAL_MUTATION)

    outcome = engine.recover(
        execution,
        compensation=_contract(RecoveryStrategy.ROLLBACK),
        scope=_scope(),
        rollback_token="fake-rollback-token",
        payload={"target": "fixture-target-1"},
    )

    assert outcome.strategy is RecoveryStrategy.ROLLBACK
    assert outcome.final_state is ExecutionState.ROLLED_BACK
    assert outcome.incident is None
    assert outcome.rollback_result is not None
    assert outcome.rollback_result.status == EXPECTED_ROLLBACK_STATUS
    assert outcome.reconciliation.reconciled is True
    assert outcome.reconciliation.expected_state is ExecutionState.ROLLED_BACK
    assert outcome.reconciliation.actual_state is ExecutionState.ROLLED_BACK
    assert len(adapter.rollback_calls) == 1
    assert adapter.rollback_calls[0] == RollbackRequest(
        scope=_scope(), rollback_token="fake-rollback-token", payload={"target": "fixture-target-1"}
    )
    assert len(outcome.audit_entry_ids) == 2
    assert [entry.action for entry in audit_sink.entries] == [
        "recovery.execution-1.attempted",
        "recovery.execution-1.rolled_back",
    ]


def test_compensate_strategy_happy_path_also_calls_adapter_rollback() -> None:
    """ADR-010 Class C rule 8 / 784's docstring: COMPENSATE is, mechanically,
    the same adapter call as ROLLBACK -- the semantic difference lives in
    the compensation contract, not the call shape."""
    adapter = FakeProviderExecutionAdapter()
    engine, _audit_sink = _engine(adapter)
    execution = _execution(MutationClass.COMPENSATABLE_EXTERNAL_MUTATION)

    outcome = engine.recover(
        execution,
        compensation=_contract(RecoveryStrategy.COMPENSATE),
        scope=_scope("fixture.disable_idle_resource"),
        rollback_token="fake-rollback-token",
        payload={"target": "fixture-target-2"},
    )

    assert outcome.strategy is RecoveryStrategy.COMPENSATE
    assert outcome.final_state is ExecutionState.ROLLED_BACK
    assert outcome.incident is None
    assert len(adapter.rollback_calls) == 1


def test_accept_irreversible_strategy_never_calls_the_adapter() -> None:
    adapter = FakeProviderExecutionAdapter()
    engine, audit_sink = _engine(adapter)
    execution = _execution(MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION)

    outcome = engine.recover(
        execution,
        compensation=_contract(RecoveryStrategy.ACCEPT_IRREVERSIBLE),
        scope=_scope("fixture.purge_snapshot"),
        rollback_token=None,
        payload={},
    )

    assert outcome.strategy is RecoveryStrategy.ACCEPT_IRREVERSIBLE
    assert outcome.final_state is ExecutionState.FAILED
    assert outcome.incident is None
    assert outcome.rollback_result is None
    assert outcome.reconciliation.reconciled is True
    assert outcome.reconciliation.expected_state is ExecutionState.FAILED
    assert outcome.reconciliation.actual_state is ExecutionState.FAILED
    assert adapter.rollback_calls == []
    assert adapter.plan_calls == []
    assert adapter.apply_calls == []
    assert [entry.action for entry in audit_sink.entries] == [
        "recovery.execution-1.risk_accepted"
    ]


# --- deliberate-break test: recovery itself fails --------------------------


class _RollbackRaisesAdapter(FakeProviderExecutionAdapter):
    """A deliberately broken fake: records the call like the real fake,
    then raises instead of returning a result -- simulating the provider's
    own rollback call itself failing."""

    def rollback(self, request: RollbackRequest) -> RollbackResult:
        self.rollback_calls.append(request)
        raise RuntimeError("synthetic provider rollback failure")


@pytest.mark.parametrize(
    "strategy",
    [RecoveryStrategy.ROLLBACK, RecoveryStrategy.COMPENSATE],
)
def test_recovery_failure_produces_failed_with_incident_never_succeeded(
    strategy: RecoveryStrategy,
) -> None:
    mutation_class = (
        MutationClass.REVERSIBLE_EXTERNAL_MUTATION
        if strategy is RecoveryStrategy.ROLLBACK
        else MutationClass.COMPENSATABLE_EXTERNAL_MUTATION
    )
    adapter = _RollbackRaisesAdapter()
    engine, audit_sink = _engine(adapter)
    execution = _execution(mutation_class)

    outcome = engine.recover(
        execution,
        compensation=_contract(strategy),
        scope=_scope(),
        rollback_token="fake-rollback-token",
        payload={"target": "fixture-target-1"},
    )

    # Never silently SUCCEEDED, and never silently ROLLED_BACK either.
    assert outcome.final_state is ExecutionState.FAILED
    assert outcome.final_state is not ExecutionState.SUCCEEDED
    assert outcome.final_state is not ExecutionState.ROLLED_BACK

    assert isinstance(outcome.incident, IncidentRecord)
    assert outcome.incident.execution_id == execution.execution_id
    assert outcome.incident.approval_id == execution.approval_id
    assert outcome.incident.strategy is strategy
    assert "synthetic provider rollback failure" in outcome.incident.reason
    assert outcome.incident.runbook_ref == RECOVERY_FAILURE_RUNBOOK

    assert isinstance(outcome.reconciliation, ReconciliationRecord)
    assert outcome.reconciliation.reconciled is False
    assert outcome.reconciliation.expected_state is ExecutionState.ROLLED_BACK
    assert outcome.reconciliation.actual_state is ExecutionState.FAILED

    assert [entry.action for entry in audit_sink.entries] == [
        "recovery.execution-1.attempted",
        "recovery.execution-1.failed",
    ]
    assert audit_sink.entries[-1].payload["incident_id"] == outcome.incident.incident_id


def test_recovery_failure_on_unexpected_adapter_status_without_exception() -> None:
    """The adapter can also fail "quietly" -- returning a result instead of
    raising, but with a status that is not the one literal a completed
    recovery promises. This must be treated exactly like an exception:
    FAILED plus an incident, never a reported success."""

    class _WrongStatusAdapter(FakeProviderExecutionAdapter):
        def rollback(self, request: RollbackRequest) -> RollbackResult:
            self.rollback_calls.append(request)
            return RollbackResult(status="ROLLBACK_PARTIAL", detail={"note": "half undone"})

    adapter = _WrongStatusAdapter()
    engine, _audit_sink = _engine(adapter)
    execution = _execution(MutationClass.REVERSIBLE_EXTERNAL_MUTATION)

    outcome = engine.recover(
        execution,
        compensation=_contract(RecoveryStrategy.ROLLBACK),
        scope=_scope(),
        rollback_token="fake-rollback-token",
        payload={"target": "fixture-target-1"},
    )

    assert outcome.final_state is ExecutionState.FAILED
    assert outcome.incident is not None
    assert "ROLLBACK_PARTIAL" in outcome.incident.reason
    assert outcome.rollback_result is not None
    assert outcome.rollback_result.status == "ROLLBACK_PARTIAL"
    assert outcome.reconciliation.reconciled is False


# --- fails closed before ever touching the adapter -------------------------


def test_recover_rejects_an_execution_that_is_not_executing() -> None:
    adapter = FakeProviderExecutionAdapter()
    engine, _audit_sink = _engine(adapter)
    execution = _execution(MutationClass.REVERSIBLE_EXTERNAL_MUTATION, state=ExecutionState.FAILED)

    with pytest.raises(InvalidStateTransitionError):
        engine.recover(
            execution,
            compensation=_contract(RecoveryStrategy.ROLLBACK),
            scope=_scope(),
            rollback_token="fake-rollback-token",
            payload={},
        )
    assert adapter.rollback_calls == []


def test_recover_rejects_a_mismatched_strategy() -> None:
    adapter = FakeProviderExecutionAdapter()
    engine, _audit_sink = _engine(adapter)
    execution = _execution(MutationClass.REVERSIBLE_EXTERNAL_MUTATION)

    with pytest.raises(ValidationError):
        engine.recover(
            execution,
            compensation=_contract(RecoveryStrategy.COMPENSATE),
            scope=_scope(),
            rollback_token="fake-rollback-token",
            payload={},
        )
    assert adapter.rollback_calls == []


def test_recover_rejects_rollback_strategy_without_a_rollback_token() -> None:
    adapter = FakeProviderExecutionAdapter()
    engine, _audit_sink = _engine(adapter)
    execution = _execution(MutationClass.REVERSIBLE_EXTERNAL_MUTATION)

    with pytest.raises(ValidationError):
        engine.recover(
            execution,
            compensation=_contract(RecoveryStrategy.ROLLBACK),
            scope=_scope(),
            rollback_token=None,
            payload={},
        )
    assert adapter.rollback_calls == []


# --- RecoveryOutcome / IncidentRecord / ReconciliationRecord construction --


def test_incident_record_rejects_blank_fields() -> None:
    with pytest.raises(ValidationError):
        IncidentRecord(
            incident_id="",
            tenant_id=TENANT,
            project_id=PROJECT,
            execution_id="execution-1",
            approval_id="approval-1",
            strategy=RecoveryStrategy.ROLLBACK,
            reason="adapter raised",
            detail={},
            runbook_ref=RECOVERY_FAILURE_RUNBOOK,
            created_at=NOW,
        )


def test_reconciliation_record_rejects_inconsistent_reconciled_flag() -> None:
    with pytest.raises(ValidationError):
        ReconciliationRecord(
            execution_id="execution-1",
            expected_state=ExecutionState.ROLLED_BACK,
            actual_state=ExecutionState.FAILED,
            reconciled=True,
            detail="inconsistent",
        )
    with pytest.raises(ValidationError):
        ReconciliationRecord(
            execution_id="execution-1",
            expected_state=ExecutionState.ROLLED_BACK,
            actual_state=ExecutionState.ROLLED_BACK,
            reconciled=False,
            detail="inconsistent",
        )


def test_recovery_outcome_is_a_plain_frozen_record() -> None:
    reconciliation = ReconciliationRecord(
        execution_id="execution-1",
        expected_state=ExecutionState.ROLLED_BACK,
        actual_state=ExecutionState.ROLLED_BACK,
        reconciled=True,
        detail="ok",
    )
    outcome = RecoveryOutcome(
        execution_id="execution-1",
        strategy=RecoveryStrategy.ROLLBACK,
        final_state=ExecutionState.ROLLED_BACK,
        rollback_result=RollbackResult(status=EXPECTED_ROLLBACK_STATUS, detail={}),
        reconciliation=reconciliation,
        incident=None,
        audit_entry_ids=("audit-1", "audit-2"),
    )
    assert outcome.final_state is ExecutionState.ROLLED_BACK
    with pytest.raises(AttributeError):
        outcome.final_state = ExecutionState.FAILED  # type: ignore[misc]
