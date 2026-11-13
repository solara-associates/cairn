"""R1-22: the kernel execution gate (ADR-010).

Composes R1-21's approval/execution state machines
(``cairn_modules.approvals.model``, ``cairn_modules.execution.model``) with
the kernel's execution-gate primitives
(``cairn_kernel.execution_gate``: the adapter port, the no-production-
adapter guard, and scoped idempotency). This is the single path every
Class C mutation crosses — propose, approve and authorize happen against
the R1-21 state machines before this module is ever reached; this module
owns authorize-to-execute, dispatch via the port, audit-before-effect, and
recording the outcome.

No code path here can reach a production adapter: the constructor calls
``require_deterministic_test_adapter`` unconditionally, and no execution
credential of any kind is constructed, read from the environment, or passed
through — the adapter receives only a synthetic operation name and a plain
payload (``cairn_kernel.execution_gate.ports.AdapterRequest``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import timedelta

from cairn_kernel.errors import InvalidStateTransitionError, RevisionMismatchError
from cairn_kernel.execution_gate import (
    AdapterRequest,
    AdapterResult,
    ExecutionAdapterPort,
    IdempotencyRecord,
    IdempotencyScope,
    IdempotencyStorePort,
    canonical_request_hash,
    check_idempotency,
    require_deterministic_test_adapter,
)
from cairn_kernel.hex.ports import Clock
from cairn_kernel.hex.primitives import OPERATION_CLASS_BY_MUTATION, ProjectId, TenantId
from cairn_kernel.security import AuditEntry, AuditSink

from cairn_modules.approvals.model import ApprovalRecord
from cairn_modules.execution.model import (
    CompensationContract,
    ExecutionRecord,
    ExecutionState,
    authorize_execution,
    validate_execution_transition,
)

DEFAULT_IDEMPOTENCY_TTL = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    """What ``ExecutionGate.execute`` returns: the terminal execution state,
    the adapter's result (or the replayed one), which audit entries were
    appended, and whether this call was an idempotent replay."""

    execution_id: str
    state: ExecutionState
    result: AdapterResult
    audit_entry_ids: tuple[str, ...]
    idempotent_replay: bool


class ExecutionGate:
    """The kernel execution gate (ADR-010, R1-22).

    No Class C operation may execute outside this gate, regardless of
    origin (ADR-010). ``authorize`` re-validates the recovery precondition
    and revision binding R1-21 already enforces at approval time — by
    delegating to ``authorize_execution`` rather than re-implementing it,
    the two can never silently diverge. ``execute`` is idempotent per
    ``IdempotencyScope``, audits before the adapter is invoked, and records
    the outcome whether the adapter succeeds or fails.
    """

    def __init__(
        self,
        *,
        adapter: ExecutionAdapterPort,
        audit_sink: AuditSink,
        idempotency_store: IdempotencyStorePort,
        clock: Clock,
        idempotency_ttl: timedelta = DEFAULT_IDEMPOTENCY_TTL,
    ) -> None:
        require_deterministic_test_adapter(adapter)
        self._adapter = adapter
        self._audit_sink = audit_sink
        self._idempotency_store = idempotency_store
        self._clock = clock
        self._idempotency_ttl = idempotency_ttl

    def authorize(
        self,
        execution: ExecutionRecord,
        approval: ApprovalRecord,
        *,
        compensation: CompensationContract | None,
    ) -> ExecutionRecord:
        """Authorize a ``PROPOSED`` execution against its ``APPROVED``
        approval. Raises (fails closed, no external effect) when the
        approval is not ``APPROVED``, the revision does not match, or the
        recovery precondition for the mutation class is absent —
        ``authorize_execution`` (R1-21) is the single source of those
        rules."""

        if execution.approval_id != approval.approval_id:
            raise RevisionMismatchError(
                f"execution {execution.execution_id} names approval"
                f" {execution.approval_id}, not {approval.approval_id}"
            )
        authorize_execution(
            approval,
            revision_id=execution.revision_id,
            revision_hash=execution.approved_hash,
            compensation=compensation,
        )
        validate_execution_transition(
            execution.mutation_class, execution.state, ExecutionState.AUTHORIZED
        )
        return replace(execution, state=ExecutionState.AUTHORIZED)

    def execute(
        self,
        execution: ExecutionRecord,
        *,
        scope: IdempotencyScope,
        request: Mapping[str, object],
    ) -> ExecutionOutcome:
        """Dispatch an ``AUTHORIZED`` execution to the adapter port.

        Idempotency is resolved before anything else: a replay for the same
        ``scope``/request returns the original result without touching the
        audit sink or the adapter a second time. Otherwise the audit entry
        for "about to effect" is appended *before* the adapter is called —
        ADR-010 Class C rule 4, "audit-before-effect" — and a second entry
        records the terminal outcome.
        """

        if execution.state is not ExecutionState.AUTHORIZED:
            raise InvalidStateTransitionError(
                f"execution {execution.execution_id} is {execution.state.value},"
                " not AUTHORIZED"
            )

        now = self._clock.now()
        request_hash = canonical_request_hash(request)
        decision = check_idempotency(self._idempotency_store, scope, request_hash, now=now)
        if decision.is_replay:
            record = decision.record
            assert record is not None
            return ExecutionOutcome(
                execution_id=execution.execution_id,
                state=ExecutionState.SUCCEEDED,
                result=AdapterResult(status="REPLAYED", detail=record.result),
                audit_entry_ids=(),
                idempotent_replay=True,
            )

        tenant_id = TenantId(execution.tenant_id)
        project_id = ProjectId(execution.project_id) if execution.project_id else None
        operation_class = OPERATION_CLASS_BY_MUTATION[execution.mutation_class]

        before_entry_id = self._audit_sink.append(
            AuditEntry(
                tenant_id=tenant_id,
                project_id=project_id,
                actor=execution.actor_id,
                action=f"execution.{scope.operation}.before_effect",
                operation_class=operation_class,
                payload={
                    "execution_id": execution.execution_id,
                    "approval_id": execution.approval_id,
                    "request_hash": request_hash,
                },
                correlation_id=execution.correlation_id,
                created_at=now,
            )
        )

        validate_execution_transition(
            execution.mutation_class, execution.state, ExecutionState.EXECUTING
        )

        try:
            result = self._adapter.execute(
                AdapterRequest(operation=scope.operation, payload=request)
            )
        except Exception:
            validate_execution_transition(
                execution.mutation_class, ExecutionState.EXECUTING, ExecutionState.FAILED
            )
            self._audit_sink.append(
                AuditEntry(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    actor=execution.actor_id,
                    action=f"execution.{scope.operation}.failed",
                    operation_class=operation_class,
                    payload={"execution_id": execution.execution_id},
                    correlation_id=execution.correlation_id,
                    created_at=self._clock.now(),
                )
            )
            raise

        validate_execution_transition(
            execution.mutation_class, ExecutionState.EXECUTING, ExecutionState.SUCCEEDED
        )
        self._idempotency_store.put(
            IdempotencyRecord(
                scope=scope,
                request_hash=request_hash,
                result=result.detail,
                created_at=now,
                expires_at=now + self._idempotency_ttl,
            )
        )
        after_entry_id = self._audit_sink.append(
            AuditEntry(
                tenant_id=tenant_id,
                project_id=project_id,
                actor=execution.actor_id,
                action=f"execution.{scope.operation}.succeeded",
                operation_class=operation_class,
                payload={"execution_id": execution.execution_id, "status": result.status},
                correlation_id=execution.correlation_id,
                created_at=self._clock.now(),
            )
        )
        return ExecutionOutcome(
            execution_id=execution.execution_id,
            state=ExecutionState.SUCCEEDED,
            result=result,
            audit_entry_ids=(before_entry_id, after_entry_id),
            idempotent_replay=False,
        )


__all__ = ["ExecutionGate", "ExecutionOutcome"]
