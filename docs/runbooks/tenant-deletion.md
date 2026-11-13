# Tenant deletion runbook

Status: R0-20 gate 12 (tenant-deletion half). Paired with a dry-run test,
`tests/integration/test_tenant_deletion_runbook.py`, that creates a real
tenant with data in every classified table, runs the procedure below
against a local Postgres container, and asserts the result -- including
that a second, untouched tenant's rows are never affected. The procedure
itself is
`cairn_adapters.persistence_postgres.tenant_deletion.delete_tenant_data`,
not a description of what someone should write someday.

## Scope: every table in the tenancy classification matrix

This runbook walks every table in
`cairn_kernel.tenancy.classification.TABLE_CLASSIFICATIONS` (ADR-012). The
module that implements deletion (`tenant_deletion.py`) asserts at import
time that its own table lists partition that matrix exactly -- adding a
new tenant- or project-owned table without updating this runbook and that
module makes every import of it fail, not just this one going quietly out
of date.

| Table | Scope | What happens on tenant deletion |
| --- | --- | --- |
| `execution_record` | PROJECT | Deleted. |
| `approval` | PROJECT | Deleted. |
| `role_grant` | TENANT | Deleted. |
| `app_user` | TENANT | Deleted. |
| `project` | PROJECT | Kept, scrubbed (`customer_name`, `name`, `scope`, `providers`, `regions`, `selected_modules` overwritten), never deleted. |
| `tenant` | TENANT | Kept, scrubbed (`name` overwritten) and tombstoned (`status = 'DELETED'`), never deleted. |
| `subject_revision` | PROJECT | **Preserved unchanged.** Append-only by migration trigger; cannot be deleted by any role. |
| `ledger_entry` | TENANT | **Preserved unchanged.** Append-only by migration trigger; cannot be deleted by any role. |
| `schema_migration`, `schema_migration_history`, `tenant_context_secret` | GLOBAL | Not tenant data; not touched. |

## Why `tenant` and `project` rows are not deleted

`ledger_entry` and `subject_revision` reference `(tenant_id, project_id)`
by composite foreign key, and that reference is never relaxed (migrations
`0003_audit_ledger.up.sql`, `0005_revision_approval_execution.up.sql`).
Since those two audit tables are themselves never deleted -- see the next
section -- deleting the `tenant`/`project` rows they point at would either
violate that foreign key or require deleting the evidence first, which is
exactly the outcome ADR-009's append-only triggers exist to make
impossible. The honest procedure is to scrub the identifying fields on
`tenant`/`project` and tombstone `tenant.status`, leaving the row as a
structural anchor with no remaining tenant-identifying content, rather
than claim a physical row deletion that the schema cannot actually
perform.

**This is a known, deliberate gap against a literal "every row physically
removed" reading of a deletion request.** If a regulatory erasure request
ever requires physically removing the `tenant`/`project` row itself
(rather than scrubbing + tombstoning it), that requires a decision on
whether `ledger_entry`/`subject_revision` rows for a deleted tenant can
ever be purged after a retention period -- a legal/compliance call, not a
schema change this runbook makes unilaterally. Flagged for Allan; not
resolved here.

## Why `ledger_entry` and `subject_revision` rows are preserved, not deleted

This is the same evidence-immutability invariant
`docs/runbooks/incident-response.md`'s evidence-preservation section
relies on: deleting a tenant must not erase the record that the tenant,
or its deletion, ever existed. Concretely:

- `ledger_entry_append_only` / `ledger_entry_no_truncate` (migration 0003)
  reject UPDATE, DELETE and TRUNCATE on `ledger_entry` unconditionally, for
  every role -- including the migration superuser connection this
  procedure itself runs on.
- `subject_revision_append_only` / `subject_revision_no_truncate`
  (migration 0005) do the same for `subject_revision`.
- The application role (`cairn_app`) additionally has no UPDATE/DELETE
  grant on either table at all (least privilege, independent of the
  trigger).

`delete_tenant_data` never attempts to touch either table, and the
dry-run test proves both that it does not, and that doing so would fail
even if it tried.

## Procedure

1. **Authorization.** A tenant-deletion request is approved the same way
   any other irreversible action in this estate is -- through the
   escalation path in `docs/runbooks/incident-response.md` section 2, or
   the equivalent customer-support approval chain once one exists. This
   runbook does not define who may approve a deletion; it defines what
   happens once one is approved.
2. **Record the request.** Before any data is touched, append a
   `tenant.deletion.requested` entry to the audit ledger for the tenant
   being deleted (`PostgresAuditSink`/`append_entry`,
   `packages/adapters/src/cairn_adapters/persistence_postgres/audit.py`),
   naming the approving actor. Because `ledger_entry` is append-only, this
   record of the deletion having happened outlives the deletion itself.
3. **Run the procedure.** Call
   `cairn_adapters.persistence_postgres.tenant_deletion.delete_tenant_data(connection, tenant_id)`
   on the privileged (migration-class) connection used for schema changes
   -- not through the `cairn_app` role. This is deliberate: the
   application role's RLS model (ADR-012) assumes one project in scope per
   transaction, while a tenant deletion must sweep every project the
   tenant owns in a single transaction. Running this as an out-of-band,
   change-managed administrative action (the same operational class as a
   migration) rather than as an application code path is the point, not an
   oversight.
4. **Verify.** Confirm zero rows remain for the tenant in
   `execution_record`, `approval`, `role_grant` and `app_user`; confirm
   `tenant`/`project` rows are scrubbed and tombstoned; confirm
   `ledger_entry`/`subject_revision` rows for the tenant are unchanged.
   `tests/integration/test_tenant_deletion_runbook.py` is this check,
   automated, against a real Postgres container -- run it as the proof a
   given deletion worked, not a substitute for running the actual
   procedure against the actual tenant.
5. **Confirm isolation.** Confirm every other tenant's rows, across every
   table above, are byte-for-byte unchanged. A tenant-deletion bug that
   touches another tenant's data is a tenant-isolation incident in its own
   right (ADR-012) and escalates as one.
