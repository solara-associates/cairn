"""Tenant deletion procedure (docs/runbooks/tenant-deletion.md).

This module is the testable half of the tenant-deletion runbook. It is
built from ``cairn_kernel.tenancy.classification.TABLE_CLASSIFICATIONS`` on
purpose: every table that classification knows about must be accounted for
in exactly one of the four groups below, or importing this module raises.
That is deliberate drift detection -- if a future migration adds a new
tenant- or project-owned table and nobody updates this module, the
deletion procedure (and every test that imports it) fails loudly instead of
silently leaving the new table's rows behind on a real deletion request.

Two of migration 0003/0005's tables -- ``ledger_entry`` and
``subject_revision`` -- are append-only by design (ADR-009; the
``ledger_entry_append_only`` and ``subject_revision_append_only`` triggers
reject UPDATE/DELETE unconditionally, even for a superuser connection, and
the application role additionally has no UPDATE/DELETE grant on either).
That is the same evidence-immutability invariant
docs/runbooks/incident-response.md's evidence-preservation section leans
on: a tenant-deletion request must not erase the record that the tenant,
or the deletion itself, ever existed. This procedure never attempts to
touch those two tables, and could not even if it tried.

``tenant`` and ``project`` rows are not deleted either, for a narrower
reason: ``ledger_entry`` and ``subject_revision`` rows reference them by a
composite foreign key on ``(tenant_id, project_id)`` that is never relaxed,
so deleting the parent rows while the audit trail still points at them
would either violate that foreign key or require deleting evidence -- the
same thing migration 0003 and 0005 were written to make impossible. They
are scrubbed of identifying content and tombstoned instead: ``tenant.name``
and ``project.customer_name``/``project.name`` are overwritten, and
``tenant.status`` is set to ``DELETED``.

Running as the application role (``cairn_app``) is deliberately not
supported here. The per-request RLS model (ADR-012) assumes exactly one
project in scope per transaction (``project``'s own RESTRICTIVE policy
requires ``project_id = cairn_current_project()`` to even read a project
row), whereas a tenant deletion must sweep every project the tenant owns
in one transaction. This procedure is run on the same privileged,
change-managed connection used for schema migrations -- an out-of-band
administrative action, not an application code path -- per
docs/runbooks/tenant-deletion.md.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import psycopg
from cairn_kernel.tenancy.classification import TABLE_CLASSIFICATIONS

#: Rows deleted outright: operational and PII-bearing data with no audit
#: role of their own. Order matters -- children before parents -- so the
#: sweep never trips a foreign-key violation partway through.
ERASED_TABLES: tuple[str, ...] = ("execution_record", "approval", "role_grant", "app_user")

#: Rows kept (foreign keys from the preserved audit tables require it) but
#: scrubbed of tenant-identifying content and tombstoned.
SCRUBBED_TABLES: tuple[str, ...] = ("project", "tenant")

#: Append-only by migration-level trigger (ADR-009). Never touched by this
#: or any procedure.
PRESERVED_AUDIT_TABLES: tuple[str, ...] = ("ledger_entry", "subject_revision")

#: Classified GLOBAL: no per-tenant rows exist in these tables at all.
NO_TENANT_DATA_TABLES: tuple[str, ...] = (
    "schema_migration",
    "schema_migration_history",
    "tenant_context_secret",
)

_ALL_CLASSIFIED_TABLES = frozenset(
    classification.table for classification in TABLE_CLASSIFICATIONS
)
_ACCOUNTED_FOR_TABLES = (
    frozenset(ERASED_TABLES)
    | frozenset(SCRUBBED_TABLES)
    | frozenset(PRESERVED_AUDIT_TABLES)
    | frozenset(NO_TENANT_DATA_TABLES)
)
if _ACCOUNTED_FOR_TABLES != _ALL_CLASSIFIED_TABLES:
    _missing = sorted(_ALL_CLASSIFIED_TABLES - _ACCOUNTED_FOR_TABLES)
    _extra = sorted(_ACCOUNTED_FOR_TABLES - _ALL_CLASSIFIED_TABLES)
    raise RuntimeError(
        "cairn_adapters.persistence_postgres.tenant_deletion has drifted from"
        " cairn_kernel.tenancy.classification.TABLE_CLASSIFICATIONS:"
        f" missing={_missing} extra={_extra}. Add the new table to exactly one"
        " of ERASED_TABLES, SCRUBBED_TABLES, PRESERVED_AUDIT_TABLES or"
        " NO_TENANT_DATA_TABLES, and update docs/runbooks/tenant-deletion.md."
    )

_SCRUBBED_TENANT_NAME = "[deleted tenant]"
_SCRUBBED_PROJECT_TEXT = "[deleted]"


@dataclass(frozen=True, slots=True)
class TenantDeletionReport:
    tenant_id: str
    erased_row_counts: dict[str, int]
    scrubbed_tables: tuple[str, ...]
    preserved_audit_tables: tuple[str, ...]


def delete_tenant_data(
    connection: psycopg.Connection, tenant_id: uuid.UUID | str
) -> TenantDeletionReport:
    """Erase a tenant's operational data on request, in one transaction.

    ``connection`` must be a privileged (migration-class) connection, not
    one bound to ``cairn_app`` -- see the module docstring for why. Table
    names interpolated below come only from the fixed module-level tuples
    above, never from a caller-supplied value.
    """
    tenant = str(tenant_id)
    erased: dict[str, int] = {}
    with connection.transaction():
        for table in ERASED_TABLES:
            cursor = connection.execute(
                f"DELETE FROM {table} WHERE tenant_id = %s",
                (tenant,),
            )
            erased[table] = cursor.rowcount
        connection.execute(
            "UPDATE project SET customer_name = %s, name = %s, scope = NULL,"
            " providers = '{}', regions = '{}', selected_modules = '{}'"
            " WHERE tenant_id = %s",
            (_SCRUBBED_PROJECT_TEXT, _SCRUBBED_PROJECT_TEXT, tenant),
        )
        connection.execute(
            "UPDATE tenant SET name = %s, status = 'DELETED' WHERE tenant_id = %s",
            (_SCRUBBED_TENANT_NAME, tenant),
        )
    return TenantDeletionReport(
        tenant_id=tenant,
        erased_row_counts=erased,
        scrubbed_tables=SCRUBBED_TABLES,
        preserved_audit_tables=PRESERVED_AUDIT_TABLES,
    )
