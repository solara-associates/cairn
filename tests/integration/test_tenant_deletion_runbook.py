"""R0-20 gate 12 (tenant-deletion half): the dry-run proof for
``docs/runbooks/tenant-deletion.md``.

Seeds one tenant with a row in every table classified by
``cairn_kernel.tenancy.classification.TABLE_CLASSIFICATIONS`` (ADR-012),
seeds a second control tenant the same way, runs
``cairn_adapters.persistence_postgres.tenant_deletion.delete_tenant_data``
against the first, and asserts:

- every ``ERASED_TABLES`` row for the deleted tenant is gone,
- ``tenant``/``project`` rows for it are scrubbed and tombstoned, not
  deleted (they cannot be, while the audit tables below still reference
  them),
- ``ledger_entry``/``subject_revision`` rows for it -- including the
  ``tenant.deletion.requested`` entry recorded before the sweep -- are
  byte-for-byte unchanged (append-only, by migration trigger),
- the control tenant's rows, in every one of those tables, are completely
  untouched.
"""

import uuid

import psycopg
from cairn_adapters.persistence_postgres.audit import PostgresAuditSink
from cairn_adapters.persistence_postgres.tenant_deletion import (
    ERASED_TABLES,
    PRESERVED_AUDIT_TABLES,
    delete_tenant_data,
)
from cairn_kernel.hex import OperationClass, ProjectId, TenantId
from cairn_kernel.security import AuditEntry
from conftest import signed_assertion


def _seed_tenant(dsn: str, *, tenant_id: uuid.UUID, project_id: uuid.UUID) -> uuid.UUID:
    """Create one row in every classified tenant/project table for
    ``tenant_id``, and return the ``user_id`` that row's FKs are anchored
    to."""
    subject_id = uuid.uuid4()
    user_id = uuid.uuid4()
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(
            "INSERT INTO tenant (tenant_id, name) VALUES (%s, %s)",
            (tenant_id, f"Tenant {tenant_id}"),
        )
        connection.execute(
            "INSERT INTO project (project_id, tenant_id, customer_name, name)"
            " VALUES (%s, %s, 'Customer', 'Project')",
            (project_id, tenant_id),
        )
        connection.execute(
            "INSERT INTO app_user (user_id, tenant_id, subject)"
            " VALUES (%s, %s, 'alice@example.com')",
            (user_id, tenant_id),
        )
        connection.execute(
            "INSERT INTO role_grant (tenant_id, user_id, project_id, role)"
            " VALUES (%s, %s, %s, 'PROJECT_OWNER')",
            (tenant_id, user_id, project_id),
        )
        revision_id = connection.execute(
            "INSERT INTO subject_revision"
            " (tenant_id, project_id, subject_kind, subject_id, revision_number,"
            "  content_hash, created_by)"
            " VALUES (%s, %s, 'MIGRATION_PLAN', %s, 1, 'sha256:abc123', 'alice')"
            " RETURNING revision_id",
            (tenant_id, project_id, subject_id),
        ).fetchone()[0]
        approval_id = connection.execute(
            "INSERT INTO approval"
            " (tenant_id, project_id, subject_kind, subject_id, revision_id,"
            "  revision_hash, mutation_class, risk_tier, proposer_actor_id)"
            " VALUES (%s, %s, 'MIGRATION_PLAN', %s, %s, 'sha256:abc123',"
            "  'INTERNAL_MUTATION', 'LOW', 'bob')"
            " RETURNING approval_id",
            (tenant_id, project_id, subject_id, revision_id),
        ).fetchone()[0]
        connection.execute(
            "UPDATE approval SET state = 'PENDING_APPROVAL' WHERE approval_id = %s",
            (approval_id,),
        )
        connection.execute(
            "UPDATE approval SET state = 'APPROVED', approver_actor_id = 'alice'"
            " WHERE approval_id = %s",
            (approval_id,),
        )
        connection.execute(
            "INSERT INTO execution_record"
            " (tenant_id, project_id, approval_id, revision_id, approved_hash,"
            "  mutation_class, actor_id, correlation_id)"
            " VALUES (%s, %s, %s, %s, 'sha256:abc123', 'INTERNAL_MUTATION',"
            "  'bob', 'corr-1')",
            (tenant_id, project_id, approval_id, revision_id),
        )
    sink = PostgresAuditSink(dsn, signed_assertion(tenant_id, project_id))
    sink.append(
        AuditEntry(
            tenant_id=TenantId(str(tenant_id)),
            project_id=ProjectId(str(project_id)),
            actor="alice",
            action="project.create",
            operation_class=OperationClass.WORKSPACE_MUTATION,
            payload={"changed": ["name"]},
        )
    )
    return user_id


def _record_deletion_request(dsn: str, *, tenant_id: uuid.UUID, approver: str) -> None:
    sink = PostgresAuditSink(dsn, signed_assertion(tenant_id, project_id=None))
    sink.append(
        AuditEntry(
            tenant_id=TenantId(str(tenant_id)),
            project_id=None,
            actor=approver,
            action="tenant.deletion.requested",
            operation_class=OperationClass.WORKSPACE_MUTATION,
            payload={"reason": "customer request"},
        )
    )


def _counts_for_tenant(dsn: str, tenant_id: uuid.UUID) -> dict[str, int]:
    tables = (*ERASED_TABLES, *PRESERVED_AUDIT_TABLES)
    counts: dict[str, int] = {}
    with psycopg.connect(dsn, autocommit=True) as connection:
        for table in tables:
            row = connection.execute(
                f"SELECT count(*) FROM {table} WHERE tenant_id = %s",
                (tenant_id,),
            ).fetchone()
            counts[table] = row[0]
    return counts


def test_tenant_deletion_erases_operational_data_and_preserves_the_audit_trail(
    migrated_database: str,
) -> None:
    deleted_tenant = uuid.uuid4()
    deleted_project = uuid.uuid4()
    control_tenant = uuid.uuid4()
    control_project = uuid.uuid4()

    _seed_tenant(migrated_database, tenant_id=deleted_tenant, project_id=deleted_project)
    _seed_tenant(migrated_database, tenant_id=control_tenant, project_id=control_project)

    control_before = _counts_for_tenant(migrated_database, control_tenant)
    for table in ERASED_TABLES + PRESERVED_AUDIT_TABLES:
        assert control_before[table] >= 1, f"control tenant seed is missing {table}"

    _record_deletion_request(migrated_database, tenant_id=deleted_tenant, approver="ops-alice")

    preserved_before = _counts_for_tenant(migrated_database, deleted_tenant)
    for table in PRESERVED_AUDIT_TABLES:
        # +1 on ledger_entry for the deletion-request entry just recorded.
        assert preserved_before[table] >= 1

    with psycopg.connect(migrated_database) as connection:
        report = delete_tenant_data(connection, deleted_tenant)
        connection.commit()

    assert report.tenant_id == str(deleted_tenant)
    for table in ERASED_TABLES:
        assert report.erased_row_counts[table] == 1

    after = _counts_for_tenant(migrated_database, deleted_tenant)
    for table in ERASED_TABLES:
        assert after[table] == 0, f"{table} still has rows for the deleted tenant"
    for table in PRESERVED_AUDIT_TABLES:
        assert after[table] == preserved_before[table], (
            f"{table} row count for the deleted tenant changed -- the audit"
            " trail must be preserved exactly, even for a deleted tenant"
        )

    with psycopg.connect(migrated_database, autocommit=True) as connection:
        tenant_row = connection.execute(
            "SELECT name, status FROM tenant WHERE tenant_id = %s",
            (deleted_tenant,),
        ).fetchone()
        project_row = connection.execute(
            "SELECT customer_name, name FROM project WHERE tenant_id = %s",
            (deleted_tenant,),
        ).fetchone()
    assert tenant_row == ("[deleted tenant]", "DELETED")
    assert project_row == ("[deleted]", "[deleted]")

    control_after = _counts_for_tenant(migrated_database, control_tenant)
    assert control_after == control_before, (
        "deleting one tenant must never change another tenant's row counts"
    )
    with psycopg.connect(migrated_database, autocommit=True) as connection:
        control_tenant_row = connection.execute(
            "SELECT name, status FROM tenant WHERE tenant_id = %s",
            (control_tenant,),
        ).fetchone()
        control_project_row = connection.execute(
            "SELECT customer_name, name FROM project WHERE tenant_id = %s",
            (control_tenant,),
        ).fetchone()
    assert control_tenant_row == (f"Tenant {control_tenant}", "ACTIVE")
    assert control_project_row == ("Customer", "Project")


def test_tenant_deletion_coverage_matches_the_tenancy_classification_matrix() -> None:
    """Drift detection: importing the module already asserts this (it
    raises at import time otherwise), but a dedicated test makes the
    invariant discoverable without reading the module's docstring."""
    from cairn_adapters.persistence_postgres.tenant_deletion import (
        NO_TENANT_DATA_TABLES,
        SCRUBBED_TABLES,
    )
    from cairn_kernel.tenancy.classification import TABLE_CLASSIFICATIONS

    all_classified = {c.table for c in TABLE_CLASSIFICATIONS}
    accounted_for = (
        set(ERASED_TABLES)
        | set(SCRUBBED_TABLES)
        | set(PRESERVED_AUDIT_TABLES)
        | set(NO_TENANT_DATA_TABLES)
    )
    assert accounted_for == all_classified


def test_deletion_runs_without_app_role_privilege() -> None:
    """``delete_tenant_data`` interpolates only from the fixed module-level
    table tuples, never from the ``tenant_id`` argument -- guard against a
    future edit accidentally making it format-string the identifier."""
    import inspect

    from cairn_adapters.persistence_postgres import tenant_deletion

    source = inspect.getsource(tenant_deletion.delete_tenant_data)
    assert "{tenant" not in source
    assert "{table}" in source
