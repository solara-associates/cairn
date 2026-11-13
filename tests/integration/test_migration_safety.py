import psycopg
import pytest
from cairn_adapters.persistence_postgres.migrator import (
    BASELINE,
    Migration,
    MigrationError,
    Migrator,
    is_destructive,
    main,
)

TENANT = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"


def _seed(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(
            "INSERT INTO tenant (tenant_id, name) VALUES (%s, %s)",
            (TENANT, "tenant-a"),
        )
        connection.execute(
            "INSERT INTO project (project_id, tenant_id, customer_name, name)"
            " VALUES (%s, %s, %s, %s)",
            (PROJECT, TENANT, "Customer", "Project"),
        )


def test_destructive_statement_detection() -> None:
    assert is_destructive("DROP TABLE ledger_entry;")
    assert is_destructive("ALTER TABLE tenant DROP COLUMN name;")
    assert is_destructive("TRUNCATE workload;")
    assert is_destructive("DELETE FROM role_grant;")
    assert is_destructive("DROP POLICY tenant_isolation ON workload;")
    assert not is_destructive("CREATE TABLE project (id int);")
    assert not is_destructive("ALTER TABLE tenant ENABLE ROW LEVEL SECURITY;")


def test_rollback_without_target_is_rejected(migrated_database: str) -> None:
    assert main(["down", "--dsn", migrated_database]) == 2


def test_rollback_rejects_unknown_target(migrated_database: str) -> None:
    with pytest.raises(MigrationError, match="unknown rollback target"):
        Migrator(migrated_database).down("9999")


def test_rollback_rejects_unapplied_target(migrated_database: str) -> None:
    migrator = Migrator(migrated_database)
    migrator.down("0004", allow_destructive=True)
    assert migrator.applied_versions() == ("0001", "0002", "0003", "0004")
    with pytest.raises(MigrationError, match="not applied"):
        migrator.down("0005", allow_destructive=True)


def test_rollback_is_one_step_by_default(migrated_database: str) -> None:
    migrator = Migrator(migrated_database)
    with pytest.raises(MigrationError, match="multi-step"):
        migrator.down("0003")
    assert migrator.down("0004", allow_destructive=True) == ("0005",)
    assert migrator.applied_versions() == ("0001", "0002", "0003", "0004")


def test_rollback_allows_multiple_steps_when_requested(migrated_database: str) -> None:
    migrator = Migrator(migrated_database)
    with pytest.raises(MigrationError, match="destructive"):
        migrator.down(BASELINE, allow_multiple=True)
    reverted = migrator.down(
        BASELINE, allow_multiple=True, allow_destructive=True
    )
    assert reverted == ("0005", "0004", "0003", "0002", "0001")
    assert migrator.applied_versions() == ()


def test_destructive_rollback_requires_explicit_flag(migrated_database: str) -> None:
    migrator = Migrator(migrated_database)
    with pytest.raises(MigrationError, match="destructive"):
        migrator.down("0004")
    assert migrator.applied_versions() == ("0001", "0002", "0003", "0004", "0005")


def test_production_destructive_rollback_requires_recovery_reference(
    migrated_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CAIRN_ENVIRONMENT", "production")
    migrator = Migrator(migrated_database, operator="dba-1")
    with pytest.raises(MigrationError, match="recovery reference"):
        migrator.down("0004", allow_destructive=True)
    assert migrator.down(
        "0004",
        allow_destructive=True,
        recovery_reference="OPS-1234",
    ) == ("0005",)
    assert migrator.history()[-1] == ("0005", "down", "reverted")


def test_rollback_preserves_business_data_and_records_history(
    migrated_database: str,
) -> None:
    _seed(migrated_database)
    migrator = Migrator(migrated_database, operator="alice")
    assert migrator.down("0004", allow_destructive=True) == ("0005",)
    with psycopg.connect(migrated_database) as connection:
        assert connection.execute("SELECT count(*) FROM tenant").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM project").fetchone() == (1,)
    assert migrator.history()[-1] == ("0005", "down", "reverted")
    with psycopg.connect(migrated_database) as connection:
        operator = connection.execute(
            "SELECT operator_name FROM schema_migration_history ORDER BY history_id DESC LIMIT 1"
        ).fetchone()
    assert operator == ("alice",)


def test_failed_rollback_leaves_recoverable_state(migration_database: str) -> None:
    broken = (
        Migration(
            version="0001",
            name="sample",
            up_sql="CREATE TABLE sample (id integer);",
            down_sql="SELECT 1 / 0;",
        ),
    )
    migrator = Migrator(migration_database, broken, operator="alice")
    migrator.up()
    with pytest.raises(psycopg.errors.DivisionByZero):
        migrator.down(BASELINE)
    assert migrator.applied_versions() == ("0001",)
    with psycopg.connect(migration_database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM pg_class WHERE relname = 'sample'"
        ).fetchone() == (1,)
    assert migrator.history()[-1] == ("0001", "down", "failed")

    repaired = (
        Migration(
            version="0001",
            name="sample",
            up_sql="CREATE TABLE sample (id integer);",
            down_sql="DROP TABLE sample;",
        ),
    )
    assert Migrator(migration_database, repaired).down(
        BASELINE, allow_destructive=True
    ) == ("0001",)
    assert Migrator(migration_database, repaired).applied_versions() == ()


def test_history_records_successful_up_runs(migrated_database: str) -> None:
    history = Migrator(migrated_database).history()
    assert [entry[2] for entry in history] == ["applied"] * 5
    assert [entry[0] for entry in history] == ["0001", "0002", "0003", "0004", "0005"]
