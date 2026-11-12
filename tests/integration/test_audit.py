from collections.abc import Callable, Iterator
from contextlib import contextmanager

import psycopg
import pytest
from cairn_adapters.persistence_postgres.audit import PostgresAuditSink
from cairn_kernel.errors import AuditUnavailableError
from cairn_kernel.hex import OperationClass, ProjectId, TenantId
from cairn_kernel.security import AuditEntry, AuditSink

TENANT_A = TenantId("11111111-1111-4111-8111-111111111111")
TENANT_B = TenantId("33333333-3333-4333-8333-333333333333")
PROJECT = ProjectId("22222222-2222-4222-8222-222222222222")


def _seed(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as connection:
        for tenant in (TENANT_A, TENANT_B):
            connection.execute(
                "INSERT INTO tenant (tenant_id, name) VALUES (%s, %s)",
                (tenant.value, f"tenant-{tenant.value[:4]}"),
            )
        connection.execute(
            "INSERT INTO project (project_id, tenant_id, customer_name, name)"
            " VALUES (%s, %s, %s, %s)",
            (PROJECT.value, TENANT_A.value, "Customer", "Project"),
        )


def _entry(
    tenant: TenantId = TENANT_A,
    project: ProjectId | None = PROJECT,
    action: str = "project.update",
) -> AuditEntry:
    return AuditEntry(
        tenant_id=tenant,
        project_id=project,
        actor="user-1",
        action=action,
        operation_class=OperationClass.WORKSPACE_MUTATION,
        payload={"changed": ["name"]},
    )


def _rows(dsn: str, tenant: TenantId) -> list[tuple[object, ...]]:
    with _app_connection(dsn, tenant) as connection:
        return connection.execute(
            "SELECT sequence, entry_hash, previous_hash, actor, action,"
            " operation_class, payload FROM ledger_entry ORDER BY sequence"
        ).fetchall()


@contextmanager
def _app_connection(dsn: str, tenant: TenantId) -> Iterator[psycopg.Connection]:
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("SET ROLE cairn_app")
        connection.execute(
            "SELECT set_config('app.tenant_id', %s, false)", (tenant.value,)
        )
        yield connection


def _guarded_effect(
    sink: AuditSink, entry: AuditEntry, effect: Callable[[], None]
) -> None:
    sink.append(entry)
    effect()


def test_append_writes_hash_chain(migrated_database: str) -> None:
    _seed(migrated_database)
    sink = PostgresAuditSink(migrated_database)
    first = sink.append(_entry(action="project.create"))
    second = sink.append(_entry(action="project.update"))
    assert first != second

    rows = _rows(migrated_database, TENANT_A)
    assert [row[0] for row in rows] == [1, 2]
    assert rows[0][2] is None
    assert rows[1][2] == rows[0][1]
    assert all(len(str(row[1])) == 64 for row in rows)
    assert rows[1][5] == "WORKSPACE_MUTATION"
    assert rows[1][6] == {"changed": ["name"]}


def test_sequences_are_scoped_per_tenant(migrated_database: str) -> None:
    _seed(migrated_database)
    sink = PostgresAuditSink(migrated_database)
    sink.append(_entry(tenant=TENANT_A))
    sink.append(_entry(tenant=TENANT_B, project=None))
    assert [row[0] for row in _rows(migrated_database, TENANT_A)] == [1]
    assert [row[0] for row in _rows(migrated_database, TENANT_B)] == [1]


def test_ledger_is_append_only_for_the_application_role(migrated_database: str) -> None:
    _seed(migrated_database)
    PostgresAuditSink(migrated_database).append(_entry())
    with _app_connection(migrated_database, TENANT_A) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("UPDATE ledger_entry SET actor = 'mallory'")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("DELETE FROM ledger_entry")


def test_ledger_is_append_only_for_table_owners(migrated_database: str) -> None:
    _seed(migrated_database)
    PostgresAuditSink(migrated_database).append(_entry())
    with psycopg.connect(migrated_database, autocommit=True) as connection:
        connection.execute(
            "SELECT set_config('app.tenant_id', %s, false)", (TENANT_A.value,)
        )
        with pytest.raises(psycopg.errors.RaiseException):
            connection.execute("UPDATE ledger_entry SET actor = 'mallory'")
        with pytest.raises(psycopg.errors.RaiseException):
            connection.execute("DELETE FROM ledger_entry")
        with pytest.raises(psycopg.errors.RaiseException):
            connection.execute("TRUNCATE ledger_entry")


def test_ledger_entries_are_tenant_isolated(migrated_database: str) -> None:
    _seed(migrated_database)
    sink = PostgresAuditSink(migrated_database)
    sink.append(_entry(tenant=TENANT_A))
    sink.append(_entry(tenant=TENANT_B, project=None))
    with _app_connection(migrated_database, TENANT_B) as connection:
        rows = connection.execute("SELECT tenant_id FROM ledger_entry").fetchall()
    assert [str(row[0]) for row in rows] == [TENANT_B.value]
    assert len(_rows(migrated_database, TENANT_A)) == 1


def test_audit_is_recorded_before_the_effect(migrated_database: str) -> None:
    _seed(migrated_database)
    sink = PostgresAuditSink(migrated_database)
    rows_visible_at_effect: list[int] = []
    _guarded_effect(
        sink,
        _entry(),
        lambda: rows_visible_at_effect.append(
            len(_rows(migrated_database, TENANT_A))
        ),
    )
    assert rows_visible_at_effect == [1]


def test_audit_outage_fails_closed(migrated_database: str) -> None:
    sink = PostgresAuditSink("postgresql://postgres:postgres@127.0.0.1:1/postgres")
    effected: list[str] = []
    with pytest.raises(AuditUnavailableError):
        _guarded_effect(sink, _entry(), lambda: effected.append("applied"))
    assert effected == []
