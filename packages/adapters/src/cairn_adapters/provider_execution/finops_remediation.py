"""R5-01b (unit 813): the FinOps Class C remediation execution adapter.

812 (R5-01a, ``cairn_modules.finops.remediation_policy``) grades a FinOps
remediation action -- ``ALERT``/``THROTTLE``/``CAP``/``STOP``/``DISABLE`` --
and, for the three Class C grades, maps it onto one of 783's risk tiers and
authorizes it via ``risk_policy.authorize_tier``. That module stops at
authorization: it never touches a provider. This module is the next step --
turning an authorized ``CAP``/``STOP``/``DISABLE`` action into a real
``ProviderExecutionPort.apply()`` call (784), with 790's ``RecoveryEngine``
wired for the action's mapped recovery strategy when ``apply`` fails.

Why this goes through ``cairn_modules.execution.gate.ExecutionGate.
authorize`` and not ``ExecutionGate.execute``
---------------------------------------------------------------------------
``ExecutionGate.execute`` dispatches through ``cairn_kernel.execution_gate.
ports.ExecutionAdapterPort`` -- a single ``execute(AdapterRequest)`` method
taking an operation name and a plain payload. That is a *different* port
shape from 784's ``ProviderExecutionPort`` (``plan``/``apply``/
``rollback``, each with its own typed request/result), and
``ExecutionGate.__init__`` calls ``require_deterministic_test_adapter``
unconditionally, which rejects by construction anything that is not the R1
``DETERMINISTIC_TEST`` adapter kind (R-GATE-01) -- including
``FakeProviderExecutionAdapter`` itself, whose own module docstring says it
is deliberately "never passed to ``ExecutionGate``". ``ExecutionGate.
authorize``, however, never touches the injected adapter at all: it only
re-validates the approval/revision/compensation-contract rules
``cairn_modules.execution.model.authorize_execution`` already owns (ADR-009/
ADR-010) -- the exact authorization gate 790's ``RecoveryEngine`` docstring
already assumes ran before it is ever reached, extended forward here to
also gate ``apply``.

So ``RemediationExecutionAdapter`` builds its internal ``ExecutionGate``
with a throwaway ``DeterministicTestExecutionAdapter`` (used only to
satisfy the constructor's guard; its own ``execute`` method is never
called) purely to call ``authorize`` on every remediation execution before
touching the real (here, fake) ``ProviderExecutionPort``. ``apply`` and
``rollback`` are then dispatched to that ``ProviderExecutionPort`` directly
-- exactly as 787's ``plan_orchestration`` (``plan``) and 790's
``RecoveryEngine`` (``rollback``) already do for their own calls, never
through ``ExecutionGate.execute``, which cannot carry a
``ProviderExecutionPort`` call at all. R-GATE-01's own check
(``test_execution_gate_ports.py``/``test_execution_gate_lifecycle.py``) is
untouched by this unit and keeps passing unmodified.

No code path in this module reaches ``ProviderExecutionPort.apply`` without
first clearing ``ExecutionGate.authorize`` and the ``PROPOSED -> AUTHORIZED
-> EXECUTING`` transition -- see
``test_finops_remediation_execution.py``'s deliberate-break test for the
construction proof (mirrors 784's "adapter cannot be called directly"
proof): an unauthorized action never reaches the provider port, proven by
the fake's own empty call log.

Judgement call -- what counts as "apply failed": ``FakeProviderExecutionAdapter.
apply`` never raises and always reports ``status="APPLIED"``. To exercise
the failure path end to end without inventing a second fake adapter (the
brief: "no new fake, no real cloud call"), every failure test here
subclasses it the same way 790's own tests subclass it for ``rollback``
(``_RollbackRaisesAdapter``/``_WrongStatusAdapter``): either ``apply``
raises (no rollback token is ever produced, so no recovery is attempted --
fails closed straight to ``FAILED`` with no adapter rollback call), or
``apply`` returns a non-``APPLIED`` status while still carrying a
``rollback_token`` (a provider that partially mutated state before
reporting failure, and can still be asked to undo it) -- in that case this
module calls ``RecoveryEngine.recover`` with that token, exactly the
scenario 790's engine is built for.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from cairn_kernel.errors import ValidationError
from cairn_kernel.execution_gate.deterministic_adapter import DeterministicTestExecutionAdapter
from cairn_kernel.hex.ports import Clock, IdGenerator
from cairn_kernel.hex.primitives import OPERATION_CLASS_BY_MUTATION, ProjectId, TenantId
from cairn_kernel.security import AuditEntry, AuditSink
from cairn_modules.approvals.model import ApprovalRecord
from cairn_modules.execution.gate import ExecutionGate
from cairn_modules.execution.model import (
    CompensationContract,
    ExecutionRecord,
    ExecutionState,
    validate_execution_transition,
)
from cairn_modules.finops.remediation_policy import RemediationAction

from cairn_adapters.provider_execution.ports import (
    ApplyRequest,
    ApplyResult,
    ExecutionScope,
    ProviderExecutionPort,
)
from cairn_adapters.provider_execution.recovery import RecoveryEngine, RecoveryOutcome

#: The one ``ApplyResult.status`` literal this module accepts as a
#: completed apply (matches ``FakeProviderExecutionAdapter.apply``'s own
#: returned literal). Anything else -- including a status that merely
#: *looks* successful -- is treated as an apply failure, the same
#: "never a silent success" discipline 790's ``RecoveryEngine`` already
#: applies to ``rollback``.
EXPECTED_APPLY_STATUS = "APPLIED"


@dataclass(frozen=True, slots=True)
class RemediationExecutionOutcome:
    """What ``RemediationExecutionAdapter.execute`` returns: the execution's
    final state, the raw ``apply`` result (if the provider port was ever
    called), the recovery outcome (``None`` unless recovery was attempted),
    and every audit entry this call appended, in order."""

    execution_id: str
    mutation_class_name: str
    final_state: ExecutionState
    apply_result: ApplyResult | None
    recovery: RecoveryOutcome | None
    audit_entry_ids: tuple[str, ...]


class RemediationExecutionAdapter:
    """Executes a 812 Class C remediation action (``CAP``/``STOP``/
    ``DISABLE``) against ``provider_port`` (``FakeProviderExecutionAdapter``
    in every test of this unit -- never a real provider), through
    ``ExecutionGate.authorize`` and, on apply failure, ``recovery_engine``.
    """

    def __init__(
        self,
        *,
        provider_port: ProviderExecutionPort,
        recovery_engine: RecoveryEngine,
        audit_sink: AuditSink,
        clock: Clock,
        id_generator: IdGenerator,
    ) -> None:
        self._gate = ExecutionGate(
            adapter=DeterministicTestExecutionAdapter(),
            audit_sink=audit_sink,
            idempotency_store=_NullIdempotencyStore(),
            clock=clock,
        )
        self._provider_port = provider_port
        self._recovery_engine = recovery_engine
        self._audit_sink = audit_sink
        self._clock = clock
        self._id_generator = id_generator

    def execute(
        self,
        action: RemediationAction,
        *,
        execution: ExecutionRecord,
        approval: ApprovalRecord,
        compensation: CompensationContract,
        scope: ExecutionScope,
        apply_payload: Mapping[str, object],
    ) -> RemediationExecutionOutcome:
        """Authorize, then execute, ``action`` against ``execution``.

        Raises (fails closed, no provider call) when ``action`` is not a
        Class C grade, when ``execution.mutation_class`` does not match the
        mutation class 812's policy maps ``action.grade`` onto, or when
        ``ExecutionGate.authorize`` itself rejects the approval/revision/
        compensation-contract binding -- the same rules every other Class C
        mutation in this codebase is already held to.
        """

        if not action.is_class_c:
            raise ValidationError(
                f"only a Class C remediation grade executes through the provider"
                f" execution gate; {action.grade.value} is not one"
            )
        mutation_class = action.mutation_class
        if execution.mutation_class is not mutation_class:
            raise ValidationError(
                f"execution record mutation_class {execution.mutation_class.value} does not"
                f" match {action.grade.value}'s mapped mutation_class"
                f" {mutation_class.value if mutation_class else None}"
            )

        authorized = self._gate.authorize(execution, approval, compensation=compensation)

        validate_execution_transition(mutation_class, authorized.state, ExecutionState.EXECUTING)
        executing = replace(authorized, state=ExecutionState.EXECUTING)

        before_id = self._audit(
            executing, action="apply_attempted", payload={"operation": scope.operation}
        )

        try:
            apply_result = self._provider_port.apply(
                ApplyRequest(scope=scope, payload=apply_payload)
            )
        except Exception as exc:  # noqa: BLE001 - any adapter failure lands here.
            return self._apply_failed(
                executing,
                compensation,
                scope=scope,
                apply_payload=apply_payload,
                before_id=before_id,
                reason=f"provider apply call raised: {exc}",
                apply_result=None,
            )

        if apply_result.status != EXPECTED_APPLY_STATUS:
            return self._apply_failed(
                executing,
                compensation,
                scope=scope,
                apply_payload=apply_payload,
                before_id=before_id,
                reason=(
                    "provider apply returned unexpected status"
                    f" {apply_result.status!r}, expected {EXPECTED_APPLY_STATUS!r}"
                ),
                apply_result=apply_result,
            )

        validate_execution_transition(
            mutation_class, ExecutionState.EXECUTING, ExecutionState.SUCCEEDED
        )
        after_id = self._audit(
            executing, action="apply_succeeded", payload={"status": apply_result.status}
        )
        return RemediationExecutionOutcome(
            execution_id=executing.execution_id,
            mutation_class_name=mutation_class.value,
            final_state=ExecutionState.SUCCEEDED,
            apply_result=apply_result,
            recovery=None,
            audit_entry_ids=(before_id, after_id),
        )

    def _apply_failed(
        self,
        executing: ExecutionRecord,
        compensation: CompensationContract,
        *,
        scope: ExecutionScope,
        apply_payload: Mapping[str, object],
        before_id: str,
        reason: str,
        apply_result: ApplyResult | None,
    ) -> RemediationExecutionOutcome:
        failed_audit_id = self._audit(executing, action="apply_failed", payload={"reason": reason})
        rollback_token = apply_result.rollback_token if apply_result is not None else None

        if rollback_token is None:
            # Nothing was committed for the provider to undo -- recovery
            # fails closed rather than inventing a token. Matches
            # RecoveryEngine's own "ROLLBACK/COMPENSATE recovery requires a
            # rollback_token" rule.
            validate_execution_transition(
                executing.mutation_class, executing.state, ExecutionState.FAILED
            )
            return RemediationExecutionOutcome(
                execution_id=executing.execution_id,
                mutation_class_name=executing.mutation_class.value,
                final_state=ExecutionState.FAILED,
                apply_result=apply_result,
                recovery=None,
                audit_entry_ids=(before_id, failed_audit_id),
            )

        recovery = self._recovery_engine.recover(
            executing,
            compensation=compensation,
            scope=scope,
            rollback_token=rollback_token,
            payload=apply_payload,
        )
        return RemediationExecutionOutcome(
            execution_id=executing.execution_id,
            mutation_class_name=executing.mutation_class.value,
            final_state=recovery.final_state,
            apply_result=apply_result,
            recovery=recovery,
            audit_entry_ids=(before_id, failed_audit_id, *recovery.audit_entry_ids),
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
                action=f"finops_remediation.{execution.execution_id}.{action}",
                operation_class=operation_class,
                payload=payload,
                correlation_id=execution.correlation_id,
                created_at=self._clock.now(),
            )
        )


class _NullIdempotencyStore:
    """``ExecutionGate`` requires an ``IdempotencyStorePort`` at
    construction, but this module only ever calls ``ExecutionGate.
    authorize`` (which never touches it) -- never ``execute`` (see module
    docstring). This throwaway store raises if either method is ever
    reached, so a future accidental call to ``ExecutionGate.execute``
    through this adapter fails loudly instead of silently using a store
    with no backing persistence."""

    def get(self, *args: object, **kwargs: object) -> object:
        raise AssertionError(
            "RemediationExecutionAdapter never calls ExecutionGate.execute,"
            " so its idempotency store must never be read"
        )

    def put(self, *args: object, **kwargs: object) -> None:
        raise AssertionError(
            "RemediationExecutionAdapter never calls ExecutionGate.execute,"
            " so its idempotency store must never be written"
        )


__all__ = [
    "EXPECTED_APPLY_STATUS",
    "RemediationExecutionAdapter",
    "RemediationExecutionOutcome",
]
