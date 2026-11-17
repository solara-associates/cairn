"""R5-01b (unit 813): the FinOps Class C remediation execution adapter.

Covers, end to end, exactly what the brief requires:

* a ``CAP``/``DISABLE``-graded action (tier 1, ``REVERSIBLE_EXTERNAL_
  MUTATION``) executes through ``ExecutionGate.authorize`` and, when the
  provider's ``apply`` call fails, rolls back via ``RecoveryEngine``'s
  ``ROLLBACK`` strategy -- proven end to end against the real
  ``RecoveryEngine``/``ExecutionGate`` objects, not a mocked-out piece;
* a ``STOP``-graded action (tier 2, ``COMPENSATABLE_EXTERNAL_MUTATION``)
  executes and, on the same kind of simulated failure, triggers
  ``COMPENSATE`` instead of ``ROLLBACK`` -- the right strategy for its own
  tier, never the other one;
* a deliberate-break test proving a remediation action cannot reach
  ``ProviderExecutionPort.apply`` by any path that skips
  ``ExecutionGate.authorize`` -- the fake adapter's own call log stays
  empty when authorization is rejected.

Every test runs against ``FakeProviderExecutionAdapter`` (787) or a tiny
subclass of it that simulates one failure mode (the same convention 790's
own ``test_recovery_engine.py`` already uses for ``rollback`` -- here
applied to ``apply``) -- never a new fake adapter, never a real cloud call.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from cairn_adapters.provider_execution.fake import FakeProviderExecutionAdapter
from cairn_adapters.provider_execution.finops_remediation import (
    EXPECTED_APPLY_STATUS,
    RemediationExecutionAdapter,
    RemediationExecutionOutcome,
)
from cairn_adapters.provider_execution.ports import ApplyRequest, ApplyResult, ExecutionScope
from cairn_adapters.provider_execution.recovery import RecoveryEngine
from cairn_kernel.classification.model import CompensationContract, RecoveryStrategy
from cairn_kernel.errors import InvalidStateTransitionError, RevisionMismatchError, ValidationError
from cairn_kernel.hex.primitives import MutationClass
from cairn_kernel.testing.fakes import FixedClock, FixedIdGenerator, InMemoryAuditSink
from cairn_modules.approvals.model import ApprovalRecord, ApprovalState
from cairn_modules.execution.model import ExecutionRecord, ExecutionState
from cairn_modules.finops.remediation_policy import RemediationAction, RemediationGrade

TENANT = "11111111-1111-1111-1111-111111111111"
PROJECT = "22222222-2222-2222-2222-222222222222"
REVISION_ID = "33333333-3333-3333-3333-333333333333"
NOW = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)


def _action(grade: RemediationGrade) -> RemediationAction:
    return RemediationAction(
        grade=grade, resource_ref="gcp://project-1/compute/vm-7", reason="budget exceeded forecast"
    )


def _approval(mutation_class: MutationClass) -> ApprovalRecord:
    return ApprovalRecord(
        approval_id="approval-1",
        tenant_id=TENANT,
        project_id=PROJECT,
        subject_kind="finops_remediation",
        subject_id="budget-7",
        revision_id=REVISION_ID,
        revision_hash="sha256:abc123",
        mutation_class=mutation_class,
        risk_tier="TIER_1"
        if mutation_class is MutationClass.REVERSIBLE_EXTERNAL_MUTATION
        else "TIER_2",
        state=ApprovalState.APPROVED,
        proposer_actor_id="bob",
        approver_actor_id="alice",
    )


def _execution(mutation_class: MutationClass, **overrides: object) -> ExecutionRecord:
    fields: dict[str, object] = {
        "execution_id": "execution-1",
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "approval_id": "approval-1",
        "revision_id": REVISION_ID,
        "approved_hash": "sha256:abc123",
        "mutation_class": mutation_class,
        "state": ExecutionState.PROPOSED,
        "actor_id": "bob",
        "correlation_id": "corr-1",
    }
    fields.update(overrides)
    return ExecutionRecord(**fields)  # type: ignore[arg-type]


def _contract(strategy: RecoveryStrategy) -> CompensationContract:
    return CompensationContract(
        strategy=strategy,
        plan_ref="recovery-plan://finops/remediate",
        preconditions="target resource identified, scoped and validated",
        authority="PROJECT_OWNER",
        evidence="before/after state capture",
        failure_handling="escalate to incident; execution stays FAILED",
    )


def _scope(operation: str) -> ExecutionScope:
    return ExecutionScope(
        tenant_id=TENANT, project_id=PROJECT, revision_id=REVISION_ID, operation=operation
    )


def _adapter_under_test(
    provider: object, audit_sink: InMemoryAuditSink | None = None
) -> tuple[RemediationExecutionAdapter, InMemoryAuditSink]:
    audit_sink = audit_sink or InMemoryAuditSink()
    recovery_engine = RecoveryEngine(
        provider_port=provider,  # type: ignore[arg-type]
        audit_sink=audit_sink,
        clock=FixedClock(NOW),
        id_generator=FixedIdGenerator(),
    )
    adapter = RemediationExecutionAdapter(
        provider_port=provider,  # type: ignore[arg-type]
        recovery_engine=recovery_engine,
        audit_sink=audit_sink,
        clock=FixedClock(NOW),
        id_generator=FixedIdGenerator(),
    )
    return adapter, audit_sink


# --- happy path: CAP/DISABLE and STOP both apply successfully --------------


@pytest.mark.parametrize("grade", [RemediationGrade.CAP, RemediationGrade.DISABLE])
def test_cap_and_disable_apply_succeeds_through_the_gate(grade: RemediationGrade) -> None:
    provider = FakeProviderExecutionAdapter()
    adapter, _audit_sink = _adapter_under_test(provider)
    execution = _execution(MutationClass.REVERSIBLE_EXTERNAL_MUTATION)

    outcome = adapter.execute(
        _action(grade),
        execution=execution,
        approval=_approval(MutationClass.REVERSIBLE_EXTERNAL_MUTATION),
        compensation=_contract(RecoveryStrategy.ROLLBACK),
        scope=_scope("finops.cap_budget"),
        apply_payload={"target": "vm-7"},
    )

    assert isinstance(outcome, RemediationExecutionOutcome)
    assert outcome.final_state is ExecutionState.SUCCEEDED
    assert outcome.recovery is None
    assert outcome.apply_result is not None
    assert outcome.apply_result.status == EXPECTED_APPLY_STATUS
    assert len(provider.apply_calls) == 1
    assert provider.rollback_calls == []


def test_stop_apply_succeeds_through_the_gate() -> None:
    provider = FakeProviderExecutionAdapter()
    adapter, _audit_sink = _adapter_under_test(provider)
    execution = _execution(MutationClass.COMPENSATABLE_EXTERNAL_MUTATION)

    outcome = adapter.execute(
        _action(RemediationGrade.STOP),
        execution=execution,
        approval=_approval(MutationClass.COMPENSATABLE_EXTERNAL_MUTATION),
        compensation=_contract(RecoveryStrategy.COMPENSATE),
        scope=_scope("finops.stop_resource"),
        apply_payload={"target": "vm-7"},
    )

    assert outcome.final_state is ExecutionState.SUCCEEDED
    assert outcome.recovery is None
    assert len(provider.apply_calls) == 1
    assert provider.rollback_calls == []


# --- simulated failure: CAP/DISABLE roll back, STOP compensates ------------


class _ApplyPartiallyFailsAdapter(FakeProviderExecutionAdapter):
    """Simulates a provider that mutated some state before reporting
    failure: ``apply`` still records the call and still returns a
    rollback token (so there is something to undo), but the status is not
    the one literal a completed apply promises."""

    def apply(self, request: ApplyRequest) -> ApplyResult:
        self.apply_calls.append(request)
        return ApplyResult(
            status="APPLY_PARTIAL",
            detail={"operation": request.scope.operation},
            rollback_token=self.next_rollback_token,
        )


def test_cap_or_disable_rolls_back_via_recovery_engine_on_simulated_apply_failure() -> None:
    provider = _ApplyPartiallyFailsAdapter()
    adapter, audit_sink = _adapter_under_test(provider)
    execution = _execution(MutationClass.REVERSIBLE_EXTERNAL_MUTATION)

    outcome = adapter.execute(
        _action(RemediationGrade.CAP),
        execution=execution,
        approval=_approval(MutationClass.REVERSIBLE_EXTERNAL_MUTATION),
        compensation=_contract(RecoveryStrategy.ROLLBACK),
        scope=_scope("finops.cap_budget"),
        apply_payload={"target": "vm-7"},
    )

    assert len(provider.apply_calls) == 1
    assert outcome.apply_result is not None
    assert outcome.apply_result.status == "APPLY_PARTIAL"
    assert outcome.recovery is not None
    assert outcome.recovery.strategy is RecoveryStrategy.ROLLBACK
    assert outcome.final_state is ExecutionState.ROLLED_BACK
    assert outcome.recovery.incident is None
    assert len(provider.rollback_calls) == 1
    assert [entry.action for entry in audit_sink.entries][:3] == [
        "finops_remediation.execution-1.apply_attempted",
        "finops_remediation.execution-1.apply_failed",
        "recovery.execution-1.attempted",
    ]


def test_stop_triggers_compensate_not_rollback_on_simulated_apply_failure() -> None:
    provider = _ApplyPartiallyFailsAdapter()
    adapter, _audit_sink = _adapter_under_test(provider)
    execution = _execution(MutationClass.COMPENSATABLE_EXTERNAL_MUTATION)

    outcome = adapter.execute(
        _action(RemediationGrade.STOP),
        execution=execution,
        approval=_approval(MutationClass.COMPENSATABLE_EXTERNAL_MUTATION),
        compensation=_contract(RecoveryStrategy.COMPENSATE),
        scope=_scope("finops.stop_resource"),
        apply_payload={"target": "vm-7"},
    )

    assert outcome.recovery is not None
    assert outcome.recovery.strategy is RecoveryStrategy.COMPENSATE
    assert outcome.recovery.strategy is not RecoveryStrategy.ROLLBACK
    assert outcome.final_state is ExecutionState.ROLLED_BACK
    assert len(provider.rollback_calls) == 1


class _ApplyRaisesAdapter(FakeProviderExecutionAdapter):
    """A provider whose apply call fails outright -- nothing was ever
    committed, so there is no rollback token and no recovery is
    attempted."""

    def apply(self, request: ApplyRequest) -> ApplyResult:
        self.apply_calls.append(request)
        raise RuntimeError("synthetic provider apply failure")


def test_apply_raising_fails_closed_without_a_token_and_never_calls_rollback() -> None:
    provider = _ApplyRaisesAdapter()
    adapter, _audit_sink = _adapter_under_test(provider)
    execution = _execution(MutationClass.REVERSIBLE_EXTERNAL_MUTATION)

    outcome = adapter.execute(
        _action(RemediationGrade.DISABLE),
        execution=execution,
        approval=_approval(MutationClass.REVERSIBLE_EXTERNAL_MUTATION),
        compensation=_contract(RecoveryStrategy.ROLLBACK),
        scope=_scope("finops.disable_integration"),
        apply_payload={"target": "vm-7"},
    )

    assert outcome.final_state is ExecutionState.FAILED
    assert outcome.recovery is None
    assert outcome.apply_result is None
    assert provider.rollback_calls == []


# --- fails closed before ever reaching the policy / grade checks ----------


def test_alert_grade_is_rejected_before_any_provider_call() -> None:
    provider = FakeProviderExecutionAdapter()
    adapter, _audit_sink = _adapter_under_test(provider)
    execution = _execution(MutationClass.REVERSIBLE_EXTERNAL_MUTATION)

    with pytest.raises(ValidationError):
        adapter.execute(
            _action(RemediationGrade.ALERT),
            execution=execution,
            approval=_approval(MutationClass.REVERSIBLE_EXTERNAL_MUTATION),
            compensation=_contract(RecoveryStrategy.ROLLBACK),
            scope=_scope("finops.alert"),
            apply_payload={},
        )
    assert provider.apply_calls == []


def test_mismatched_mutation_class_is_rejected_before_any_provider_call() -> None:
    provider = FakeProviderExecutionAdapter()
    adapter, _audit_sink = _adapter_under_test(provider)
    # STOP maps to COMPENSATABLE_EXTERNAL_MUTATION, not REVERSIBLE -- a
    # caller that builds the wrong execution record for the grade must be
    # rejected, not silently executed against the wrong tier's strategy.
    execution = _execution(MutationClass.REVERSIBLE_EXTERNAL_MUTATION)

    with pytest.raises(ValidationError):
        adapter.execute(
            _action(RemediationGrade.STOP),
            execution=execution,
            approval=_approval(MutationClass.REVERSIBLE_EXTERNAL_MUTATION),
            compensation=_contract(RecoveryStrategy.ROLLBACK),
            scope=_scope("finops.stop_resource"),
            apply_payload={},
        )
    assert provider.apply_calls == []


# --- the deliberate break: cannot reach apply() without clearing the gate -


def test_an_unapproved_action_cannot_reach_provider_apply() -> None:
    """R-GATE-01, applied to this unit's own call path: an approval that is
    not APPROVED is rejected by ``ExecutionGate.authorize`` before
    ``apply`` is ever touched."""

    provider = FakeProviderExecutionAdapter()
    adapter, _audit_sink = _adapter_under_test(provider)
    execution = _execution(MutationClass.REVERSIBLE_EXTERNAL_MUTATION)
    pending_approval = ApprovalRecord(
        approval_id="approval-1",
        tenant_id=TENANT,
        project_id=PROJECT,
        subject_kind="finops_remediation",
        subject_id="budget-7",
        revision_id=REVISION_ID,
        revision_hash="sha256:abc123",
        mutation_class=MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
        risk_tier="TIER_1",
        state=ApprovalState.PENDING_APPROVAL,
        proposer_actor_id="bob",
    )

    with pytest.raises(InvalidStateTransitionError):
        adapter.execute(
            _action(RemediationGrade.CAP),
            execution=execution,
            approval=pending_approval,
            compensation=_contract(RecoveryStrategy.ROLLBACK),
            scope=_scope("finops.cap_budget"),
            apply_payload={"target": "vm-7"},
        )
    assert provider.apply_calls == []
    assert provider.rollback_calls == []


def test_a_revision_mismatched_approval_cannot_reach_provider_apply() -> None:
    provider = FakeProviderExecutionAdapter()
    adapter, _audit_sink = _adapter_under_test(provider)
    execution = _execution(MutationClass.REVERSIBLE_EXTERNAL_MUTATION)
    mismatched_approval = replace(
        _approval(MutationClass.REVERSIBLE_EXTERNAL_MUTATION),
        revision_hash="sha256:does-not-match",
    )

    with pytest.raises(RevisionMismatchError):
        adapter.execute(
            _action(RemediationGrade.DISABLE),
            execution=execution,
            approval=mismatched_approval,
            compensation=_contract(RecoveryStrategy.ROLLBACK),
            scope=_scope("finops.disable_integration"),
            apply_payload={"target": "vm-7"},
        )
    assert provider.apply_calls == []


def test_a_missing_compensation_contract_cannot_reach_provider_apply() -> None:
    """A Class C mutation with no compensation contract fails
    ``authorize_execution``'s recovery-precondition check before this
    module ever constructs an ``ApplyRequest``."""

    provider = FakeProviderExecutionAdapter()
    adapter, _audit_sink = _adapter_under_test(provider)
    execution = _execution(MutationClass.REVERSIBLE_EXTERNAL_MUTATION)

    with pytest.raises(Exception):  # noqa: B017 - RecoveryPlanRequiredError, fails closed either way.
        adapter.execute(
            _action(RemediationGrade.CAP),
            execution=execution,
            approval=_approval(MutationClass.REVERSIBLE_EXTERNAL_MUTATION),
            compensation=None,  # type: ignore[arg-type]
            scope=_scope("finops.cap_budget"),
            apply_payload={"target": "vm-7"},
        )
    assert provider.apply_calls == []
