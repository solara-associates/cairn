"""Tenant-context change guard (R1-19 early slice, R-TENANT-03).

ADR-012 requires that "tenant-context change attempts, including
session-variable and SET LOCAL tricks, are rejected and audited." The
database itself rejects a second ``cairn_set_tenant_context`` call within
one transaction (see migration ``0006_tenant_context_change_guard``); this
module is the sanctioned way application code attempts a context change so
that the rejection is also recorded via the R0-10 audit sink against the
tenant the connection was already (legitimately) bound to, never silently
dropped.
"""

from __future__ import annotations

import psycopg
from cairn_kernel.errors import TenantScopeViolationError
from cairn_kernel.hex import OperationClass, ProjectId, TenantId
from cairn_kernel.security.audit import AuditEntry, AuditSink

CONTEXT_CHANGE_REJECTED_ACTION = "tenancy.context_change_rejected"


def guard_tenant_context_change(
    connection: psycopg.Connection,
    *,
    new_assertion: str,
    audit_sink: AuditSink,
    bound_tenant_id: TenantId,
    bound_project_id: ProjectId | None,
    actor: str,
) -> None:
    """Attempt to (re)bind the tenant context mid-transaction.

    The attempt is always rejected once a context is already bound in this
    transaction (fail closed, ADR-012/R-TENANT-03). The rejection is
    recorded against ``bound_tenant_id``/``bound_project_id`` -- the
    context the connection already legitimately holds -- via
    ``audit_sink``, using a fresh connection so the record survives the
    aborted transaction.

    Raises ``TenantScopeViolationError`` in every case; never silently
    ignores the attempt.
    """
    try:
        connection.execute("SELECT cairn_set_tenant_context(%s)", (new_assertion,))
    except psycopg.errors.InsufficientPrivilege as exc:
        audit_sink.append(
            AuditEntry(
                tenant_id=bound_tenant_id,
                project_id=bound_project_id,
                actor=actor,
                action=CONTEXT_CHANGE_REJECTED_ACTION,
                operation_class=OperationClass.READ,
                payload={"reason": "tenant_context_already_bound"},
            )
        )
        raise TenantScopeViolationError(
            "tenant context change rejected: context already bound for this"
            " transaction"
        ) from exc
    else:
        # The database only reaches this line if no context was bound yet,
        # which means this was not a change attempt at all -- a caller bug.
        raise TenantScopeViolationError(
            "guard_tenant_context_change called with no tenant context bound;"
            " this is not a context-change attempt"
        )
