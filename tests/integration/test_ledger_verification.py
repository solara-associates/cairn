import uuid

import psycopg
import pytest
from cairn_adapters.persistence_postgres.audit import PostgresAuditSink
from cairn_adapters.persistence_postgres.ledger_verifier import verify_ledger
from cairn_kernel.errors import AuditUnavailableError
from cairn_kernel.hex import OperationClass, ProjectId, TenantId
from cairn_kernel.security import AuditEntry, entry_hash
from conftest import signed_assertion

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = uuid.UUID("33333333-3333-4333-8333-333333333333")
PROJECT_A = uuid.UUID("22222222-2222-4222-8222-222222222222")


def _seed(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(
            "INSERT INTO tenant (tenant_id, name) VALUES (%s, 'A'), (%s, 'B')",
            (TENANT_A, TENANT_B),
        )
        connection.execute(
            "INSERT INTO project (project_id, tenant_id, customer_name, name)"
            " VALUES (%s, %s, 'Customer', 'A')",
            (PROJECT_A, TENANT_A),
        )


def _entry(action: str = "project.update") -> AuditEntry:
    return AuditEntry(
        tenant_id=TenantId(str(TENANT_A)),
        project_id=ProjectId(str(PROJECT_A)),
        actor="user-1",
        action=action,
        operation_class=OperationClass.WORKSPACE_MUTATION,
        payload={"changed": ["name"]},
    )


def _sink(dsn: str) -> PostgresAuditSink:
    return PostgresAuditSink(dsn, signed_assertion(TENANT_A, PROJECT_A))


def _assertion() -> str:
    return signed_assertion(TENANT_A, PROJECT_A)


def _verify(dsn: str):
    with psycopg.connect(dsn) as connection:
        return verify_ledger(
            connection, TenantId(str(TENANT_A)), _assertion()
        )


def _tamper(dsn: str, statement: str, params: tuple[object, ...] = ()) -> None:
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("ALTER TABLE ledger_entry DISABLE TRIGGER ledger_entry_append_only")
        connection.execute(statement, params)
        connection.execute("ALTER TABLE ledger_entry ENABLE TRIGGER ledger_entry_append_only")


def test_empty_chain_is_valid(migrated_database: str) -> None:
    _seed(migrated_database)
    report = _verify(migrated_database)
    assert report.valid
    assert report.entries_checked == 0
    assert report.latest_hash is None


def test_valid_chain_reports_latest_hash(migrated_database: str) -> None:
    _seed(migrated_database)
    sink = _sink(migrated_database)
    sink.append(_entry("project.create"))
    sink.append(_entry("project.update"))
    report = _verify(migrated_database)
    assert report.valid
    assert report.entries_checked == 2
    with psycopg.connect(migrated_database) as connection:
        latest = connection.execute(
            "SELECT entry_hash FROM ledger_entry ORDER BY sequence DESC LIMIT 1"
        ).fetchone()[0]
    assert report.latest_hash == latest


def test_modified_payload_is_detected(migrated_database: str) -> None:
    _seed(migrated_database)
    sink = _sink(migrated_database)
    sink.append(_entry("project.create"))
    sink.append(_entry("project.update"))
    _tamper(
        migrated_database,
        "UPDATE ledger_entry SET payload = %s::jsonb WHERE sequence = 2",
        ('{"changed": ["tampered"]}',),
    )
    report = _verify(migrated_database)
    assert not report.valid
    assert report.first_invalid_sequence == 2
    assert report.reason == "entry hash mismatch"


def test_modified_actor_is_detected(migrated_database: str) -> None:
    _seed(migrated_database)
    sink = _sink(migrated_database)
    sink.append(_entry("project.create"))
    sink.append(_entry("project.update"))
    _tamper(
        migrated_database,
        "UPDATE ledger_entry SET actor = 'mallory' WHERE sequence = 1",
    )
    report = _verify(migrated_database)
    assert not report.valid
    assert report.first_invalid_sequence == 1


def test_deleted_entry_is_detected(migrated_database: str) -> None:
    _seed(migrated_database)
    sink = _sink(migrated_database)
    for action in ("project.create", "project.update", "project.archive"):
        sink.append(_entry(action))
    _tamper(migrated_database, "DELETE FROM ledger_entry WHERE sequence = 2")
    report = _verify(migrated_database)
    assert not report.valid
    assert report.first_invalid_sequence == 2
    assert report.reason == "sequence gap or out of order"


def test_inserted_entry_with_broken_link_is_detected(migrated_database: str) -> None:
    _seed(migrated_database)
    sink = _sink(migrated_database)
    sink.append(_entry("project.create"))
    sink.append(_entry("project.update"))
    forged = entry_hash(
        tenant_id=str(TENANT_A),
        project_id=str(PROJECT_A),
        actor="mallory",
        action="project.delete",
        operation_class="WORKSPACE_MUTATION",
        sequence=3,
        previous_hash="0" * 64,
        payload='{"changed":["name"]}',
        created_at="2026-01-01T00:00:00+00:00",
    )
    _tamper(
        migrated_database,
        "INSERT INTO ledger_entry (tenant_id, project_id, sequence, entry_hash,"
        " previous_hash, actor, action, operation_class, payload, created_at)"
        " VALUES (%s, %s, 3, %s, %s, 'mallory', 'project.delete',"
        " 'WORKSPACE_MUTATION', %s::jsonb, %s)",
        (
            TENANT_A,
            PROJECT_A,
            forged,
            "0" * 64,
            '{"changed":["name"]}',
            "2026-01-01T00:00:00+00:00",
        ),
    )
    report = _verify(migrated_database)
    assert not report.valid
    assert report.first_invalid_sequence == 3
    assert report.reason == "previous hash mismatch"


def test_trusted_anchor_is_enforced(migrated_database: str) -> None:
    _seed(migrated_database)
    sink = _sink(migrated_database)
    sink.append(_entry("project.create"))
    report = _verify(migrated_database)
    with psycopg.connect(migrated_database) as connection:
        anchored = verify_ledger(
            connection,
            TenantId(str(TENANT_A)),
            _assertion(),
            expected_latest_hash=report.latest_hash,
        )
        stale = verify_ledger(
            connection,
            TenantId(str(TENANT_A)),
            _assertion(),
            expected_latest_hash="0" * 64,
        )
    assert anchored.valid
    assert not stale.valid
    assert stale.reason == "latest hash does not match the trusted anchor"


def test_verification_is_tenant_scoped(migrated_database: str) -> None:
    _seed(migrated_database)
    sink = _sink(migrated_database)
    sink.append(_entry())
    with pytest.raises(ValueError, match="does not match the assertion"), psycopg.connect(
        migrated_database
    ) as connection:
        verify_ledger(
            connection,
            TenantId(str(TENANT_B)),
            signed_assertion(TENANT_A, PROJECT_A),
        )


def test_verification_with_forged_assertion_fails_closed(migrated_database: str) -> None:
    _seed(migrated_database)
    _sink(migrated_database).append(_entry())
    with pytest.raises(AuditUnavailableError), psycopg.connect(migrated_database) as connection:
        verify_ledger(
            connection,
            TenantId(str(TENANT_A)),
            signed_assertion(TENANT_A, PROJECT_A, secret=b"wrong-secret"),
        )
