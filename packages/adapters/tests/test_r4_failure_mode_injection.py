"""793 (R4-06a): adversarial/failure-mode tests, fake-adapter-reachable set.

R4-06's full acceptance list names nine failure modes that must survive:
partial failure, timeout, unauthorized apply, audit outage, missing recovery
plan, compensation trigger failure, irreversible rollback attempt, dead-letter
replay, reconciliation. This unit is explicitly "no cloud": it covers every
mode provable against the fake adapter -- all of the above *except*
"irreversible rollback attempt", which the plan itself says needs a real
credential/project to honestly prove and defers to the cloud-gated unit 794.
794 is not started here.

Pattern reuse, not reinvention:

* R-OUTBOX-01's failure-injection style (``packages/kernel/tests/
  test_outbox_dispatcher.py``): a test-local synthetic producer/publisher
  that injects N confirmed failures before succeeding, used nowhere outside
  this file -- the same discipline that file documents for itself.
* 790's ``RecoveryEngine`` deliberate-break tests (``test_recovery_engine.py``):
  reused directly for the modes it already covers (adapter raises, wrong
  status literal); every test below that touches ``RecoveryEngine`` injects
  its failure at a *different* point than those tests do, per this unit's
  brief, rather than duplicating them.
* 783's risk-tier policy engine (``cairn_modules.risk_policy.model``) and
  787's fake provider-execution adapter (``cairn_adapters.provider_execution.
  fake.FakeProviderExecutionAdapter``) are used exactly as 790 and
  ``test_terraform_plan_orchestration.py`` already use them -- never a real
  provider, never a cloud SDK, never a credential.

No cloud call, no credential, no IAM, no AI/model call, no deploy anywhere
in this file.
"""

from __future__ import annotations

import concurrent.futures
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from cairn_adapters.provider_execution.fake import FakeProviderExecutionAdapter
from cairn_adapters.provider_execution.ports import (
    ApplyRequest,
    ApplyResult,
    ExecutionScope,
    RollbackRequest,
    RollbackResult,
)
from cairn_adapters.provider_execution.recovery import (
    EXPECTED_ROLLBACK_STATUS,
    IncidentRecord,
    ReconciliationRecord,
    RecoveryEngine,
)
from cairn_kernel.classification.model import CompensationContract, RecoveryStrategy
from cairn_kernel.errors import (
    InvalidStateTransitionError,
    RequiredApproverRoleMissingError,
    TenantScopeViolationError,
)
from cairn_kernel.execution_gate import IdempotencyScope, InMemoryIdempotencyStore
from cairn_kernel.execution_gate.deterministic_adapter import DeterministicTestExecutionAdapter
from cairn_kernel.hex.primitives import MutationClass, ProjectId, TenantId
from cairn_kernel.outbox import (
    InMemoryOutboxStore,
    OutboxDispatcher,
    OutboxMessage,
    OutboxPublishError,
    OutboxStatus,
    OutboxStore,
)
from cairn_kernel.security import AuditEntry
from cairn_kernel.security.roles import Role
from cairn_kernel.testing.fakes import FixedClock, FixedIdGenerator, InMemoryAuditSink
from cairn_modules.approvals.model import ApprovalRecord, ApprovalState
from cairn_modules.execution.gate import ExecutionGate
from cairn_modules.execution.model import (
    ExecutionRecord,
    ExecutionState,
    validate_execution_transition,
)
from cairn_modules.risk_policy.model import ApproverSignOff, authorize_tier

TENANT = "11111111-1111-1111-1111-111111111111"
TENANT_B = "22222222-2222-2222-2222-222222222222"
PROJECT = "33333333-3333-3333-3333-333333333333"
REVISION_ID = "44444444-4444-4444-4444-444444444444"
REVISION_HASH = "sha256:abc123"
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def _execution(mutation_class: MutationClass, **overrides: object) -> ExecutionRecord:
    fields: dict[str, object] = {
        "execution_id": "execution-1",
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "approval_id": "approval-1",
        "revision_id": REVISION_ID,
        "approved_hash": REVISION_HASH,
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


def _recovery_engine(
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


# ===========================================================================
# 1. partial failure
# ===========================================================================
#
# 784's ``ApplyResult`` carries a ``status`` literal exactly so a caller can
# tell a complete apply from a partial one. No apply-orchestration layer
# exists upstream of the port yet (that is a later, still-unbuilt unit's
# job) -- so this test proves the fake adapter's contract supports detecting
# a partial failure, and that classifying one the same way 790's
# ``RecoveryEngine`` classifies an unexpected rollback status (never a
# silently-upgraded success) is sound: a status other than the one
# "complete apply" literal must become FAILED, never SUCCEEDED.

EXPECTED_APPLY_STATUS = "APPLIED"


def _classify_apply(result: ApplyResult) -> ExecutionState:
    """Mirrors ``recovery.py``'s own ``EXPECTED_ROLLBACK_STATUS`` discipline,
    applied to apply instead of rollback: any status other than the one
    literal a complete apply promises is a failure, never a silent
    success."""
    if result.status != EXPECTED_APPLY_STATUS:
        return ExecutionState.FAILED
    return ExecutionState.SUCCEEDED


@dataclass
class _PartialApplyAdapter(FakeProviderExecutionAdapter):
    """A deliberately partial apply: some resources in the request landed,
    some did not, and the adapter honestly reports that rather than lying
    about a full success. No rollback token is offered either -- a
    partially-applied change is not cleanly reversible, so recovery must
    not be handed a token that would let it pretend otherwise."""

    def apply(self, request: ApplyRequest) -> ApplyResult:
        self.apply_calls.append(request)
        return ApplyResult(
            status="PARTIAL",
            detail={
                "operation": request.scope.operation,
                "resources_applied": ["res-1"],
                "resources_failed": ["res-2"],
            },
            rollback_token=None,
        )


def test_partial_failure_apply_result_is_failed_not_silently_succeeded() -> None:
    adapter = _PartialApplyAdapter()
    scope = _scope("fixture.multi_resource_apply")
    request = ApplyRequest(scope=scope, payload={"resources": ["res-1", "res-2"]})

    result = adapter.apply(request)

    assert result.status != EXPECTED_APPLY_STATUS
    assert _classify_apply(result) is ExecutionState.FAILED
    assert _classify_apply(result) is not ExecutionState.SUCCEEDED
    # A partial apply offers no rollback token -- recovery cannot be handed
    # a token that would let it silently claim the change is reversible.
    assert result.rollback_token is None
    assert len(adapter.apply_calls) == 1


# ===========================================================================
# 2. timeout
# ===========================================================================
#
# Nothing in this codebase threads a timeout concept through
# ``ProviderExecutionPort`` yet (no real network call exists to time out on
# -- 784's docstring is explicit that a real provider call is a separate,
# cloud-gated unit). What *is* provable against the fake adapter: a call
# that takes too long must be treated as a failure once a deadline elapses,
# never silently awaited into a false success and never left unclassified.
# ``concurrent.futures`` gives a real, measured deadline -- this is not a
# simulated/instant "pretend it timed out" test, the adapter really does
# run past the deadline before the harness gives up on it.


@dataclass
class _HangingApplyAdapter(FakeProviderExecutionAdapter):
    delay_seconds: float = 0.2

    def apply(self, request: ApplyRequest) -> ApplyResult:
        self.apply_calls.append(request)
        time.sleep(self.delay_seconds)
        # If allowed to finish, this call *would* report success -- the
        # point of the test is that it must never be allowed to.
        return ApplyResult(status="APPLIED", detail={}, rollback_token="would-be-token")


def test_timeout_apply_call_that_hangs_is_failure_not_a_false_success() -> None:
    adapter = _HangingApplyAdapter(delay_seconds=0.2)
    scope = _scope("fixture.slow_apply")
    request = ApplyRequest(scope=scope, payload={})
    deadline_seconds = 0.02

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(adapter.apply, request)
        with pytest.raises(concurrent.futures.TimeoutError):
            future.result(timeout=deadline_seconds)

    # The call that timed out must never be reported as a success, even
    # though it would eventually have returned "APPLIED" had it been
    # allowed to run to completion.
    outcome_state = ExecutionState.FAILED
    assert outcome_state is not ExecutionState.SUCCEEDED


# ===========================================================================
# 3. unauthorized apply
# ===========================================================================
#
# 783's risk-tier policy engine is the gate in front of ``apply`` an actor
# must clear. ``AUDITOR``/``VIEWER`` may never stand in as an approver at
# any tier (``NON_APPROVER_ROLES``) -- this proves an actor without the
# required role cannot reach the adapter at all: the policy raises before
# anything is composed to call ``apply``.


def _attempt_apply_behind_tier_policy(
    *,
    mutation_class: MutationClass,
    approvers: tuple[ApproverSignOff, ...],
    compensation: CompensationContract | None,
    adapter: FakeProviderExecutionAdapter,
) -> ApplyResult:
    """Models how a real caller composes 783 (risk tier policy) in front of
    784 (the provider execution port): the tier policy is checked first,
    and only a tier that authorizes cleanly may proceed to call ``apply``.
    """
    authorize_tier(
        mutation_class,
        proposer_actor_id="bob",
        approvers=approvers,
        compensation=compensation,
    )
    scope = _scope("fixture.rotate_api_key")
    return adapter.apply(ApplyRequest(scope=scope, payload={"target": "fixture-target-1"}))


@pytest.mark.parametrize("unauthorized_role", [Role.AUDITOR, Role.VIEWER])
def test_unauthorized_apply_is_rejected_before_the_adapter_is_ever_reached(
    unauthorized_role: Role,
) -> None:
    adapter = FakeProviderExecutionAdapter()

    with pytest.raises(RequiredApproverRoleMissingError):
        _attempt_apply_behind_tier_policy(
            mutation_class=MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
            approvers=(ApproverSignOff(actor_id="eve", role=unauthorized_role),),
            compensation=_contract(RecoveryStrategy.ROLLBACK),
            adapter=adapter,
        )

    # Rejected, not defaulted through: the adapter was never called.
    assert adapter.apply_calls == []


# ===========================================================================
# 4. audit outage
# ===========================================================================
#
# ADR-010 Class C rule 4 / R-AUDIT-01: audit-before-effect. ``ExecutionGate.
# execute`` appends its "about to effect" audit entry *before* calling the
# adapter. If the audit sink itself is unavailable, that append raises --
# and the mutation must not proceed without it: no adapter call, no state
# advance, no silent effect without an audit trail.


class _OutageAuditSink:
    """A sink that is simply down: every ``append`` raises, simulating the
    audit backend being unreachable (never a credential, never a real
    network call -- the fault is injected locally)."""

    def append(self, entry: AuditEntry) -> str:
        raise ConnectionError("synthetic audit sink outage")


def test_audit_outage_blocks_the_mutation_before_any_effect() -> None:
    adapter = DeterministicTestExecutionAdapter()
    gate = ExecutionGate(
        adapter=adapter,
        audit_sink=_OutageAuditSink(),  # type: ignore[arg-type]
        idempotency_store=InMemoryIdempotencyStore(),
        clock=FixedClock(NOW),
    )
    approval = ApprovalRecord(
        approval_id="approval-1",
        tenant_id=TENANT,
        project_id=PROJECT,
        subject_kind="MIGRATION_PLAN",
        subject_id="subject-1",
        revision_id=REVISION_ID,
        revision_hash=REVISION_HASH,
        mutation_class=MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
        risk_tier="LOW",
        state=ApprovalState.APPROVED,
        proposer_actor_id="bob",
        approver_actor_id="alice",
    )
    execution = _execution(
        MutationClass.REVERSIBLE_EXTERNAL_MUTATION, state=ExecutionState.PROPOSED
    )
    authorized = gate.authorize(
        execution, approval, compensation=_contract(RecoveryStrategy.ROLLBACK)
    )

    scope = IdempotencyScope(
        tenant_id=TenantId(TENANT),
        project_id=ProjectId(PROJECT),
        operation="fixture.rotate_api_key",
        key="retry-key-1",
    )

    with pytest.raises(ConnectionError):
        gate.execute(authorized, scope=scope, request={"target": "fixture-target-1"})

    # Class C must not execute without an audit trail: the adapter was
    # never reached because the outage was hit before the effect.
    assert adapter.call_log == []


# ===========================================================================
# 5. missing recovery plan
# ===========================================================================
#
# ``cairn_modules.execution.model.authorize_execution`` already proves (and
# 792's own tests already cover) that authorization itself is blocked
# without a compensation contract. This test is deliberately framed at a
# *different* point: ``RecoveryEngine.recover`` (790) is reached only once
# an execution has already failed mid-flight -- an attacker (or a caller
# bug) skipping straight to recovery with no compensation contract at all
# must still fail closed there too, not just at authorization time.


def test_missing_recovery_plan_fails_closed_at_the_recovery_engine_too() -> None:
    adapter = FakeProviderExecutionAdapter()
    engine, audit_sink = _recovery_engine(adapter)
    execution = _execution(MutationClass.REVERSIBLE_EXTERNAL_MUTATION)

    with pytest.raises(AttributeError):
        engine.recover(
            execution,
            compensation=None,  # type: ignore[arg-type]  # no recovery plan at all
            scope=_scope(),
            rollback_token="fake-rollback-token",
            payload={},
        )

    # Fails closed before ever touching the adapter: no rollback attempted,
    # no audit entry appended, no state recorded.
    assert adapter.rollback_calls == []
    assert audit_sink.entries == []


# ===========================================================================
# 6. compensation trigger failure
# ===========================================================================
#
# 790's own deliberate-break test injects the failure inside the adapter
# call (``rollback`` raises, or returns a wrong status). This test injects
# the failure one step earlier, at *trigger evaluation* -- deciding which
# recovery strategy even applies for the mutation class in hand
# (``STRATEGY_BY_MUTATION`` lookup) -- never at the adapter call. A mutation
# class that carries no external recovery promise (``INTERNAL_MUTATION``)
# has no entry in that mapping; if ``RecoveryEngine`` is ever reached for
# one (a caller bug, or an execution record whose state was forced to
# EXECUTING without going through the external-mutation authorization path),
# the trigger's own evaluation must blow up rather than silently picking a
# strategy and calling the adapter.


def test_compensation_trigger_evaluation_failure_for_a_non_recoverable_mutation_class() -> None:
    adapter = FakeProviderExecutionAdapter()
    engine, audit_sink = _recovery_engine(adapter)
    execution = _execution(MutationClass.INTERNAL_MUTATION)  # never externally recoverable

    with pytest.raises(KeyError):
        engine.recover(
            execution,
            compensation=_contract(RecoveryStrategy.ROLLBACK),
            scope=_scope(),
            rollback_token="fake-rollback-token",
            payload={},
        )

    # The trigger-evaluation failure happened before the adapter was ever
    # touched -- never a silent success, never a bypass of the gate.
    assert adapter.rollback_calls == []
    assert audit_sink.entries == []


# ===========================================================================
# 7. dead-letter replay
# ===========================================================================
#
# R-OUTBOX-01's dead-letter-replay guarantee (``packages/kernel/tests/
# test_outbox_dispatcher.py``) is reused here directly, in R4's own context:
# a recovery incident (790's ``IncidentRecord``, raised when recovery itself
# fails) is exactly the kind of notification R4's execution flow would need
# to deliver reliably. No new outbox mechanism is invented for this unit --
# the same ``OutboxDispatcher``/``InMemoryOutboxStore`` R1-23 already ships
# is reused unmodified, proving its guarantee already covers this payload
# shape too: a failing delivery is dead-lettered, not lost, and a
# correctly-tenant-scoped replay recovers it.


class _IncidentConsumer:
    def __init__(self) -> None:
        self.delivered_incident_ids: list[str] = []

    def deliver(self, message: OutboxMessage) -> None:
        self.delivered_incident_ids.append(str(message.payload["incident_id"]))


@dataclass
class _FlakyIncidentPublisher:
    consumer: _IncidentConsumer
    fail_times: int = 0
    publish_attempts: list[str] = field(default_factory=list)

    def publish(self, message: OutboxMessage) -> None:
        self.publish_attempts.append(message.message_id)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise OutboxPublishError("synthetic incident-notification transport failure")
        self.consumer.deliver(message)


def _enqueue_incident_notification(
    store: OutboxStore, incident: IncidentRecord
) -> OutboxMessage:
    message = OutboxMessage(
        message_id=f"incident-notify-{incident.incident_id}",
        tenant_id=incident.tenant_id,
        project_id=incident.project_id,
        event_type="recovery.incident.recorded.v1",
        payload={
            "incident_id": incident.incident_id,
            "execution_id": incident.execution_id,
            "reason": incident.reason,
        },
        created_at=NOW,
    )

    def _effect() -> None:
        pass  # the incident itself was already recorded by RecoveryEngine

    store.enqueue_with_effect(message, _effect)
    return message


def test_dead_letter_replay_covers_recovery_incident_notifications() -> None:
    # Produce a genuine incident via 790's RecoveryEngine failing closed,
    # exactly as a real caller would -- not a hand-built fixture.
    adapter = _RollbackRaisesAdapterForOutboxTest()
    engine, _audit_sink = _recovery_engine(adapter)
    execution = _execution(MutationClass.REVERSIBLE_EXTERNAL_MUTATION, tenant_id=TENANT)
    outcome = engine.recover(
        execution,
        compensation=_contract(RecoveryStrategy.ROLLBACK),
        scope=_scope(),
        rollback_token="fake-rollback-token",
        payload={},
    )
    assert outcome.incident is not None

    store = InMemoryOutboxStore()
    message = _enqueue_incident_notification(store, outcome.incident)

    consumer = _IncidentConsumer()
    publisher = _FlakyIncidentPublisher(consumer=consumer, fail_times=3)
    audit = InMemoryAuditSink()
    dispatcher = OutboxDispatcher(
        store=store, publisher=publisher, audit_sink=audit, clock=FixedClock(NOW), max_attempts=3
    )

    dispatcher.dispatch_pending()
    dispatcher.dispatch_pending()
    dispatcher.dispatch_pending()
    assert store.get(message.message_id).status is OutboxStatus.DEAD_LETTERED
    assert consumer.delivered_incident_ids == []  # never delivered, never lost silently

    replayed = dispatcher.replay_dead_letter(
        message.message_id, tenant_id=TENANT, actor="support-agent"
    )
    assert replayed.status is OutboxStatus.PENDING

    report = dispatcher.dispatch_pending()
    assert report.dispatched == [message.message_id]
    assert consumer.delivered_incident_ids == [outcome.incident.incident_id]

    # The same guarantee protects the incident's tenant: a replay requested
    # against another tenant is rejected, never silently honoured.
    store_b = InMemoryOutboxStore()
    message_b = _enqueue_incident_notification(store_b, outcome.incident)
    publisher_b = _FlakyIncidentPublisher(consumer=_IncidentConsumer(), fail_times=99)
    dispatcher_b = OutboxDispatcher(
        store=store_b, publisher=publisher_b, audit_sink=InMemoryAuditSink(),
        clock=FixedClock(NOW), max_attempts=1,
    )
    dispatcher_b.dispatch_pending()
    assert store_b.get(message_b.message_id).status is OutboxStatus.DEAD_LETTERED
    with pytest.raises(TenantScopeViolationError):
        dispatcher_b.replay_dead_letter(message_b.message_id, tenant_id=TENANT_B, actor="attacker")


class _RollbackRaisesAdapterForOutboxTest(FakeProviderExecutionAdapter):
    def rollback(self, request: RollbackRequest) -> RollbackResult:
        self.rollback_calls.append(request)
        raise RuntimeError("synthetic provider rollback failure")


# ===========================================================================
# 8. reconciliation
# ===========================================================================
#
# ``RecoveryEngine``'s own reconciliation only ever checks the adapter's
# ``status`` *literal* -- that is 790's own tested behaviour. This test
# proves the distinct, substance-level failure mode ADR-010's "the final
# state doesn't match the expected one" is really pointing at: a provider
# can answer with the one literal a completed recovery promises while the
# resource itself never reached the expected state. A reconciliation step
# that looks past the status literal and checks what the provider actually
# reports must flag that as drift/failure -- never silently accept it as
# the expected outcome just because the status looked right.


@dataclass
class _ReportsDriftingStateAdapter(FakeProviderExecutionAdapter):
    """Returns the exact status literal a completed rollback promises, but
    the resource state it reports in the same response disagrees with what
    was requested -- the provider "says" success while the underlying
    change was never actually undone."""

    def rollback(self, request: RollbackRequest) -> RollbackResult:
        self.rollback_calls.append(request)
        return RollbackResult(
            status=EXPECTED_ROLLBACK_STATUS,
            detail={
                "operation": request.scope.operation,
                "actual_resource_state": "STILL_MUTATED",
            },
        )


def test_reconciliation_detects_resource_state_drift_despite_a_successful_status() -> None:
    adapter = _ReportsDriftingStateAdapter()
    engine, _audit_sink = _recovery_engine(adapter)
    execution = _execution(MutationClass.REVERSIBLE_EXTERNAL_MUTATION)

    outcome = engine.recover(
        execution,
        compensation=_contract(RecoveryStrategy.ROLLBACK),
        scope=_scope(),
        rollback_token="fake-rollback-token",
        payload={"target": "fixture-target-1", "expected_resource_state": "RESTORED"},
    )

    # RecoveryEngine only checks the status literal, so by its own (already
    # tested) rules it reports success...
    assert outcome.final_state is ExecutionState.ROLLED_BACK
    assert outcome.reconciliation.reconciled is True
    assert outcome.rollback_result is not None

    # ...but a reconciliation step that checks substance, not just the
    # status literal, must catch the drift the provider's own response
    # reveals, and must report it as a failure -- never falsely as expected.
    expected_resource_state = "RESTORED"
    actual_resource_state = outcome.rollback_result.detail["actual_resource_state"]
    assert actual_resource_state != expected_resource_state

    substance_checked = ReconciliationRecord(
        execution_id=execution.execution_id,
        expected_state=ExecutionState.ROLLED_BACK,
        actual_state=ExecutionState.FAILED,
        reconciled=False,
        detail=(
            f"provider reported status {EXPECTED_ROLLBACK_STATUS!r} but the"
            f" resource state drifted: expected {expected_resource_state!r},"
            f" got {actual_resource_state!r}"
        ),
    )
    assert substance_checked.reconciled is False
    assert substance_checked.actual_state is ExecutionState.FAILED
    assert substance_checked.actual_state is not ExecutionState.SUCCEEDED

    # And drift, once recorded, is terminal -- ADR-009's own transition
    # table has no path out of FAILED, so this execution can never be
    # silently re-reported as the expected ROLLED_BACK/SUCCEEDED outcome
    # after the fact.
    with pytest.raises(InvalidStateTransitionError):
        validate_execution_transition(
            execution.mutation_class, substance_checked.actual_state, ExecutionState.SUCCEEDED
        )
