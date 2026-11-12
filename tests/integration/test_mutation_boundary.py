import uuid

import psycopg
import pytest
from cairn_adapters.persistence_postgres.audit import PostgresMutationBoundary
from cairn_kernel.errors import AuditUnavailableError
from cairn_kernel.hex import OperationClass, ProjectId, TenantId
from cairn_kernel.security import AuditEntry
from conftest import signed_assertion

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = uuid.UUID("33333333-3333-4333-8333-333333333333")
PROJECT_A = uuid.UUID("22222222-2222-4222-8222-222222222222")
PROJECT_B = uuid.UUID("44444444-4444-4444-8444-444444444444")


def _seed(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(
            "INSERT INTO tenant (tenant_id, name) VALUES (%s, 'A'), (%s, 'B')",
            (TENANT_A, TENANT_B),
        )
        connection.execute(
            "INSERT INTO project (project_id, tenant_id, customer_name, name)"
            " VALUES (%s, %s, 'Customer', 'A'), (%s, %s, 'Customer', 'B')",
            (PROJECT_A, TENANT_A, PROJECT_B, TENANT_B),
        )


def _entry(
    tenant: uuid.UUID = TENANT_A,
    project: uuid.UUID | None = PROJECT_A,
    correlation_id: str | None = "corr-1",
) -> AuditEntry:
    return AuditEntry(
        tenant_id=TenantId(str(tenant)),
        project_id=None if project is None else ProjectId(str(project)),
        actor="user-1",
        action="app_user.create",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        payload={"before": None, "after": {"subject": "boundary-user"}},
        correlation_id=correlation_id,
    )


def _asserted(dsn: str, tenant: uuid.UUID, project: uuid.UUID | None = PROJECT_A) -> PostgresMutationBoundary:
    return PostgresMutationBoundary(dsn, signed_assertion(tenant, project))


def _ledger_rows(dsn: str, tenant: uuid.UUID = TENANT_A) -> list[tuple[object, ...]]:
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("SET ROLE cairn_app")
        with connection.transaction():
            connection.execute(
                "SELECT cairn_set_tenant_context(%s)",
                (signed_assertion(tenant, PROJECT_A if tenant == TENANT_A else None),),
            )
            return connection.execute(
                "SELECT sequence, actor, action, operation_class, payload"
                " FROM ledger_entry ORDER BY sequence"
            ).fetchall()


def test_mutation_and_audit_commit_together(migrated_database: str) -> None:
    _seed(migrated_database)
    boundary = _asserted(migrated_database, TENANT_A)

    def create_user(connection: psycopg.Connection) -> None:
        connection.execute(
            "INSERT INTO app_user (tenant_id, subject) VALUES (%s, %s)",
            (TENANT_A, "boundary-user"),
        )

    outcome = boundary.execute(_entry(), create_user)
    assert outcome.audit_entry_id

    rows = _ledger_rows(migrated_database)
    assert len(rows) == 1
    sequence, actor, action, class_, payload = rows[0]
    assert (sequence, actor, action, class_) == (
        1,
        "user-1",
        "app_user.create",
        "WORKSPACE_MUTATION",
    )
    assert payload == {
        "after": {"subject": "boundary-user"},
        "before": None,
        "correlation_id": "corr-1",
    }
    with psycopg.connect(migrated_database) as owner:
        assert owner.execute(
            "SELECT count(*) FROM app_user WHERE subject = 'boundary-user'"
        ).fetchone() == (1,)


def test_audit_failure_rolls_back_the_mutation(
    migrated_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(migrated_database)
    from cairn_adapters.persistence_postgres import audit as audit_module

    def failing_append(connection: psycopg.Connection, entry: AuditEntry) -> str:
        raise psycopg.OperationalError("audit store unavailable")

    monkeypatch.setattr(audit_module, "append_entry", failing_append)
    boundary = _asserted(migrated_database, TENANT_A)
    with pytest.raises(AuditUnavailableError):
        boundary.execute(
            _entry(),
            lambda connection: connection.execute(
                "INSERT INTO app_user (tenant_id, subject) VALUES (%s, %s)",
                (TENANT_A, "rollback-user"),
            ),
        )
    with psycopg.connect(migrated_database) as owner:
        assert owner.execute(
            "SELECT count(*) FROM app_user WHERE subject = 'rollback-user'"
        ).fetchone() == (0,)
        assert owner.execute("SELECT count(*) FROM ledger_entry").fetchone() == (0,)


def test_business_failure_writes_no_audit(migrated_database: str) -> None:
    _seed(migrated_database)
    boundary = _asserted(migrated_database, TENANT_A)

    def failing_mutation(connection: psycopg.Connection) -> None:
        raise RuntimeError("business rule failed")

    with pytest.raises(RuntimeError, match="business rule failed"):
        boundary.execute(_entry(), failing_mutation)
    with psycopg.connect(migrated_database) as owner:
        assert owner.execute("SELECT count(*) FROM ledger_entry").fetchone() == (0,)


def test_entry_outside_the_assertion_is_rejected(migrated_database: str) -> None:
    _seed(migrated_database)
    boundary = _asserted(migrated_database, TENANT_A)
    with pytest.raises(AuditUnavailableError, match="outside the assertion"):
        boundary.execute(
            _entry(tenant=TENANT_B, project=None),
            lambda connection: None,
        )
    with psycopg.connect(migrated_database) as owner:
        assert owner.execute("SELECT count(*) FROM ledger_entry").fetchone() == (0,)


def test_forged_assertion_fails_closed(migrated_database: str) -> None:
    _seed(migrated_database)
    boundary = PostgresMutationBoundary(
        migrated_database,
        signed_assertion(TENANT_A, PROJECT_A, secret=b"wrong-secret"),
    )
    with pytest.raises(AuditUnavailableError):
        boundary.execute(_entry(), lambda connection: None)
    with psycopg.connect(migrated_database) as owner:
        assert owner.execute("SELECT count(*) FROM ledger_entry").fetchone() == (0,)


def test_successive_mutations_extend_the_chain(migrated_database: str) -> None:
    _seed(migrated_database)
    boundary = _asserted(migrated_database, TENANT_A)
    boundary.execute(
        _entry(correlation_id="corr-1"),
        lambda connection: connection.execute(
            "INSERT INTO app_user (tenant_id, subject) VALUES (%s, %s)",
            (TENANT_A, "first-user"),
        ),
    )
    boundary.execute(
        _entry(correlation_id="corr-2"),
        lambda connection: connection.execute(
            "INSERT INTO app_user (tenant_id, subject) VALUES (%s, %s)",
            (TENANT_A, "second-user"),
        ),
    )
    rows = _ledger_rows(migrated_database)
    assert [row[0] for row in rows] == [1, 2]
    assert [row[4]["correlation_id"] for row in rows] == ["corr-1", "corr-2"]
