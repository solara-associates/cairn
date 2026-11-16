"""790 (R4-04a): the rollback/compensation engine (ADR-010's compensation-
contract table, "Failure handling" row).

Where this sits: R1-21/R1-22 (``cairn_modules.execution.model``/``.gate``)
already own propose -> authorize -> execute for a Class C mutation, and the
gate's own ``execute`` already catches an adapter ``apply`` failure and
moves the record ``EXECUTING -> FAILED`` (ADR-009's allowed-transitions
table). This engine is the next step that table already anticipates but
R1-22 never implements: *before* that terminal state is accepted, attempt
the recovery action the mutation's own ``CompensationContract`` promised --
``ROLLBACK``, ``COMPENSATE`` or ``ACCEPT_IRREVERSIBLE`` (the three
``RecoveryStrategy`` members ``cairn_kernel.classification.model`` already
defines and ``cairn_modules.execution.model.STRATEGY_BY_MUTATION`` already
binds one-to-one to each external ``MutationClass``) -- and only then settle
on the execution's terminal state.

Call shape (ADR-010 Class C rule 8, and 784's own ``ProviderExecutionPort``
docstring): ``ROLLBACK`` and ``COMPENSATE`` both call the adapter's single
``rollback()`` method -- the mechanical call is identical; the semantic
difference between "undo the mutation" and "trigger a separate
compensating effect" lives entirely in the compensation contract this
engine validates before calling, never in the call shape. The engine does
not re-derive what the compensating action *is* -- that is the contract's
``preconditions`` field, already validated for completeness at
authorization time (``cairn_modules.execution.model.authorize_execution``)
-- it only executes the recovery call the contract already committed to and
reconciles the result. ``ACCEPT_IRREVERSIBLE`` never calls the adapter at
all: ADR-010 is explicit that an irreversible mutation "carries no rollback
promise", so this engine's only job for that strategy is to record the
accepted risk.

Fails closed in every branch (ADR-010: "Recovery failure is an incident
with reconciliation; the execution is ``FAILED``, never silently
``SUCCEEDED``"): a raised adapter exception, or an adapter response whose
``status`` is not the one expected literal for a completed recovery, both
produce ``ExecutionState.FAILED`` plus an ``IncidentRecord`` -- never a
state this engine did not itself just validate via
``cairn_modules.execution.model.validate_execution_transition``, so this
engine can never silently disagree with ADR-009's own transition table.

No cloud call anywhere in this module: the only outbound call is
``ProviderExecutionPort.rollback``, exercised in every test of this unit
against ``FakeProviderExecutionAdapter`` (787) or an equally fake,
deliberately-failing test double. Real provider rollback execution is a
separate, cloud-gated unit (791) that this module does not start.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from cairn_kernel.classification.model import CompensationContract, RecoveryStrategy
from cairn_kernel.errors import InvalidStateTransitionError, ValidationError
from cairn_kernel.hex.ports import Clock, IdGenerator
from cairn_kernel.hex.primitives import OPERATION_CLASS_BY_MUTATION, ProjectId, TenantId
from cairn_kernel.security import AuditEntry, AuditSink
from cairn_modules.execution.model import (
    STRATEGY_BY_MUTATION,
    ExecutionRecord,
    ExecutionState,
    validate_execution_transition,
)

from cairn_adapters.provider_execution.ports import (
    ExecutionScope,
    ProviderExecutionPort,
    RollbackRequest,
    RollbackResult,
)

#: The one ``RollbackResult.status`` literal this engine accepts as a
#: completed recovery (matches ``FakeProviderExecutionAdapter.rollback``'s
#: own returned literal). Anything else -- including a status that merely
#: *looks* successful -- is treated as a reconciliation failure, never as a
#: silent success: ADR-010's "never a silent success" applies as much to a
#: wrong status string as it does to a raised exception.
EXPECTED_ROLLBACK_STATUS = "ROLLED_BACK"

#: Where an operator goes when this engine itself reports a recovery
#: failure. Points at the runbook this unit ships (not a new, free-standing
#: incident format -- the brief's own instruction is to reuse this repo's
#: existing ``docs/runbooks/`` convention), which in turn hands off to
#: ``docs/runbooks/incident-response.md``'s escalation and post-incident
#: review sections for anything this engine's own record does not resolve.
RECOVERY_FAILURE_RUNBOOK = "docs/runbooks/rollback-compensation-recovery.md"


@dataclass(frozen=True, slots=True)
class IncidentRecord:
    """ADR-010's "failure handling" element, as a structured record: what
    recovery was attempted, for which execution, and why it failed. Never
    constructed for a successful recovery (including ``ACCEPT_IRREVERSIBLE``,
    which is an expected outcome, not a failure) -- its mere existence on a
    ``RecoveryOutcome`` *is* the signal that recovery itself failed."""

    incident_id: str
    tenant_id: str
    project_id: str
    execution_id: str
    approval_id: str
    strategy: RecoveryStrategy
    reason: str
    detail: Mapping[str, object]
    runbook_ref: str
    created_at: datetime

    def __post_init__(self) -> None:
        for field_name, value in (
            ("incident_id", self.incident_id),
            ("execution_id", self.execution_id),
            ("reason", self.reason),
            ("runbook_ref", self.runbook_ref),
        ):
            if not value.strip():
                raise ValidationError(f"incident record {field_name!r} must not be blank")


@dataclass(frozen=True, slots=True)
class ReconciliationRecord:
    """Verifies/records that the execution's resulting state matches what
    was expected after a recovery attempt (ADR-009's state machine: never a
    hidden-success transition). ``reconciled`` is ``False`` exactly when
    ``actual_state`` is not ``expected_state`` -- i.e. exactly when a
    recovery attempt failed."""

    execution_id: str
    expected_state: ExecutionState
    actual_state: ExecutionState
    reconciled: bool
    detail: str

    def __post_init__(self) -> None:
        if self.reconciled and self.expected_state is not self.actual_state:
            raise ValidationError(
                "a reconciliation record cannot claim reconciled=True while"
                " expected_state and actual_state disagree"
            )
        if not self.reconciled and self.expected_state is self.actual_state:
            raise ValidationError(
                "a reconciliation record cannot claim reconciled=False while"
                " expected_state and actual_state agree"
            )


@dataclass(frozen=True, slots=True)
class RecoveryOutcome:
    """What ``RecoveryEngine.recover`` returns: the execution's new terminal
    state, the raw adapter result (if the adapter was called at all), the
    reconciliation record, an incident record if and only if recovery
    itself failed, and the audit entries this call appended."""

    execution_id: str
    strategy: RecoveryStrategy
    final_state: ExecutionState
    rollback_result: RollbackResult | None
    reconciliation: ReconciliationRecord
    incident: IncidentRecord | None
    audit_entry_ids: tuple[str, ...]


class RecoveryEngine:
    """Executes ADR-010 recovery for one failed ``EXECUTING`` mutation
    against ``provider_port`` (``FakeProviderExecutionAdapter`` in every
    test of this unit -- never a real provider).

    Scope: this engine is reached while the execution is still
    ``ExecutionState.EXECUTING`` -- i.e. the gate's own apply attempt has
    just failed (or a compensation trigger has fired) and no terminal state
    has been committed yet. ``ExecutionState.EXECUTING`` is deliberately
    the only entry state this engine accepts: ADR-009's own
    ``ALLOWED_EXECUTION_TRANSITIONS`` table only permits ``ROLLED_BACK`` or
    ``FAILED`` as a *next* state from ``EXECUTING`` (and, separately, from
    ``SUCCEEDED`` for a compensation trigger firing after the fact -- not
    yet wired into this engine, since this unit's acceptance is "no cloud"
    contract tests for the EXECUTING-time recovery path, not an extension
    of ADR-009's table).
    """

    def __init__(
        self,
        *,
        provider_port: ProviderExecutionPort,
        audit_sink: AuditSink,
        clock: Clock,
        id_generator: IdGenerator,
    ) -> None:
        self._provider_port = provider_port
        self._audit_sink = audit_sink
        self._clock = clock
        self._id_generator = id_generator

    def recover(
        self,
        execution: ExecutionRecord,
        *,
        compensation: CompensationContract,
        scope: ExecutionScope,
        rollback_token: str | None,
        payload: Mapping[str, object],
    ) -> RecoveryOutcome:
        """Attempt recovery for ``execution`` per its compensation
        contract's strategy.

        Raises (fails closed, no adapter call, no state recorded) when:
          - ``execution.state`` is not ``EXECUTING``,
          - ``compensation.strategy`` does not match the strategy
            ``STRATEGY_BY_MUTATION`` requires for ``execution.mutation_class``
            (the same rule ``authorize_execution`` already enforced at
            authorization time -- re-checked here defensively, so this
            engine can never be handed a mismatched contract),
          - the strategy is ``ROLLBACK``/``COMPENSATE`` and no
            ``rollback_token`` is supplied.

        Otherwise always returns a ``RecoveryOutcome`` -- a raised adapter
        exception or an unexpected adapter response never propagates past
        this method; both become ``ExecutionState.FAILED`` plus an
        ``IncidentRecord``.
        """

        if execution.state is not ExecutionState.EXECUTING:
            raise InvalidStateTransitionError(
                f"recovery can only be attempted for an EXECUTING execution,"
                f" {execution.execution_id} is {execution.state.value}"
            )

        expected_strategy = STRATEGY_BY_MUTATION[execution.mutation_class]
        if compensation.strategy is not expected_strategy:
            raise ValidationError(
                f"{execution.mutation_class.value} requires recovery strategy"
                f" {expected_strategy.value}, got {compensation.strategy.value}"
            )

        if compensation.strategy is RecoveryStrategy.ACCEPT_IRREVERSIBLE:
            return self._accept_irreversible(execution, compensation)

        if rollback_token is None or not rollback_token.strip():
            raise ValidationError(
                f"{compensation.strategy.value} recovery requires a rollback_token"
            )

        return self._rollback_or_compensate(
            execution,
            compensation,
            scope=scope,
            rollback_token=rollback_token,
            payload=payload,
        )

    # -- ACCEPT_IRREVERSIBLE: never attempt anything, just record the risk --

    def _accept_irreversible(
        self, execution: ExecutionRecord, compensation: CompensationContract
    ) -> RecoveryOutcome:
        validate_execution_transition(
            execution.mutation_class, execution.state, ExecutionState.FAILED
        )
        audit_id = self._audit(
            execution,
            action="risk_accepted",
            payload={
                "execution_id": execution.execution_id,
                "strategy": compensation.strategy.value,
                "residual_risk": compensation.preconditions,
            },
        )
        reconciliation = ReconciliationRecord(
            execution_id=execution.execution_id,
            expected_state=ExecutionState.FAILED,
            actual_state=ExecutionState.FAILED,
            reconciled=True,
            detail=(
                "IRREVERSIBLE_EXTERNAL_MUTATION carries no rollback promise"
                " (ADR-010); accepted risk recorded, no recovery action"
                " attempted."
            ),
        )
        return RecoveryOutcome(
            execution_id=execution.execution_id,
            strategy=compensation.strategy,
            final_state=ExecutionState.FAILED,
            rollback_result=None,
            reconciliation=reconciliation,
            incident=None,
            audit_entry_ids=(audit_id,),
        )

    # -- ROLLBACK / COMPENSATE: call the adapter's rollback(), reconcile ----

    def _rollback_or_compensate(
        self,
        execution: ExecutionRecord,
        compensation: CompensationContract,
        *,
        scope: ExecutionScope,
        rollback_token: str,
        payload: Mapping[str, object],
    ) -> RecoveryOutcome:
        before_id = self._audit(
            execution,
            action="attempted",
            payload={
                "execution_id": execution.execution_id,
                "strategy": compensation.strategy.value,
                "operation": scope.operation,
            },
        )

        request = RollbackRequest(scope=scope, rollback_token=rollback_token, payload=payload)
        try:
            result = self._provider_port.rollback(request)
        except Exception as exc:  # noqa: BLE001 - deliberately broad: any adapter
            # failure, of any kind, must land here rather than propagate.
            return self._recovery_failed(
                execution,
                compensation,
                before_id=before_id,
                reason=f"provider rollback call raised: {exc}",
                detail={"exception_type": type(exc).__name__, "exception_detail": str(exc)},
                rollback_result=None,
            )

        if result.status != EXPECTED_ROLLBACK_STATUS:
            return self._recovery_failed(
                execution,
                compensation,
                before_id=before_id,
                reason=(
                    "provider rollback returned unexpected status"
                    f" {result.status!r}, expected {EXPECTED_ROLLBACK_STATUS!r}"
                ),
                detail={"status": result.status, "adapter_detail": dict(result.detail)},
                rollback_result=result,
            )

        validate_execution_transition(
            execution.mutation_class, execution.state, ExecutionState.ROLLED_BACK
        )
        after_id = self._audit(
            execution,
            action="rolled_back",
            payload={"execution_id": execution.execution_id, "status": result.status},
        )
        reconciliation = ReconciliationRecord(
            execution_id=execution.execution_id,
            expected_state=ExecutionState.ROLLED_BACK,
            actual_state=ExecutionState.ROLLED_BACK,
            reconciled=True,
            detail="provider rollback call succeeded and reconciled.",
        )
        return RecoveryOutcome(
            execution_id=execution.execution_id,
            strategy=compensation.strategy,
            final_state=ExecutionState.ROLLED_BACK,
            rollback_result=result,
            reconciliation=reconciliation,
            incident=None,
            audit_entry_ids=(before_id, after_id),
        )

    def _recovery_failed(
        self,
        execution: ExecutionRecord,
        compensation: CompensationContract,
        *,
        before_id: str,
        reason: str,
        detail: Mapping[str, object],
        rollback_result: RollbackResult | None,
    ) -> RecoveryOutcome:
        # ADR-010: recovery failure is FAILED, never silently SUCCEEDED (and,
        # per this module's scope, never silently ROLLED_BACK either) --
        # validated through the same transition gate the happy path uses, so
        # this branch can never land on a state ADR-009 does not permit.
        validate_execution_transition(
            execution.mutation_class, execution.state, ExecutionState.FAILED
        )
        incident = IncidentRecord(
            incident_id=self._id_generator.new_id(),
            tenant_id=execution.tenant_id,
            project_id=execution.project_id,
            execution_id=execution.execution_id,
            approval_id=execution.approval_id,
            strategy=compensation.strategy,
            reason=reason,
            detail=detail,
            runbook_ref=RECOVERY_FAILURE_RUNBOOK,
            created_at=self._clock.now(),
        )
        after_id = self._audit(
            execution,
            action="failed",
            payload={
                "execution_id": execution.execution_id,
                "incident_id": incident.incident_id,
                "reason": reason,
            },
        )
        reconciliation = ReconciliationRecord(
            execution_id=execution.execution_id,
            expected_state=ExecutionState.ROLLED_BACK,
            actual_state=ExecutionState.FAILED,
            reconciled=False,
            detail=f"recovery itself failed: {reason}",
        )
        return RecoveryOutcome(
            execution_id=execution.execution_id,
            strategy=compensation.strategy,
            final_state=ExecutionState.FAILED,
            rollback_result=rollback_result,
            reconciliation=reconciliation,
            incident=incident,
            audit_entry_ids=(before_id, after_id),
        )

    def _audit(
        self, execution: ExecutionRecord, *, action: str, payload: Mapping[str, object]
    ) -> str:
        tenant_id = TenantId(execution.tenant_id)
        project_id = ProjectId(execution.project_id) if execution.project_id else None
        operation_class = OPERATION_CLASS_BY_MUTATION[execution.mutation_class]
        return self._audit_sink.append(
            AuditEntry(
                tenant_id=tenant_id,
                project_id=project_id,
                actor=execution.actor_id,
                action=f"recovery.{execution.execution_id}.{action}",
                operation_class=operation_class,
                payload=payload,
                correlation_id=execution.correlation_id,
                created_at=self._clock.now(),
            )
        )


__all__ = [
    "EXPECTED_ROLLBACK_STATUS",
    "RECOVERY_FAILURE_RUNBOOK",
    "IncidentRecord",
    "ReconciliationRecord",
    "RecoveryEngine",
    "RecoveryOutcome",
]
