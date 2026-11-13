import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest
from cairn_adapters.persistence_postgres.migrator import BASELINE, Migrator
from cairn_kernel.tenancy import (
    PROJECT_POLICY,
    REQUIRED_POLICIES,
    TENANCY_CLASSIFICATION,
    TENANT_POLICY,
    TenancyScope,
)
from conftest import signed_assertion

APP_ROLE = "cairn_app"



def _public_tables(connection: psycopg.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT c.relname FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relkind = 'r'"
    ).fetchall()
    return {row[0] for row in rows}


def _rls_flags(connection: psycopg.Connection) -> dict[str, tuple[bool, bool]]:
    rows = connection.execute(
        "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relkind = 'r'"
    ).fetchall()
    return {row[0]: (row[1], row[2]) for row in rows}


def _table_policies(connection: psycopg.Connection, table: str) -> set[str]:
    rows = connection.execute(
        "SELECT policyname FROM pg_policies WHERE schemaname = 'public' AND tablename = %s",
        (table,),
    ).fetchall()
    return {row[0] for row in rows}


@contextmanager
def app_role_session(
    dsn: str,
    tenant_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
) -> Iterator[psycopg.Connection]:
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(f"SET ROLE {APP_ROLE}")
        with connection.transaction():
            if tenant_id is not None:
                connection.execute(
                    "SELECT cairn_set_tenant_context(%s)",
                    (signed_assertion(tenant_id, project_id),),
                )
            yield connection


def test_migrations_up_and_down_round_trip(migration_database: str) -> None:
    migrator = Migrator(migration_database)
    assert migrator.up() == ("0001", "0002", "0003", "0004", "0005")
    with psycopg.connect(migration_database) as connection:
        assert _public_tables(connection) == {
            "tenant",
            "app_user",
            "project",
            "role_grant",
            "ledger_entry",
            "subject_revision",
            "approval",
            "execution_record",
            "schema_migration",
            "schema_migration_history",
            "tenant_context_secret",
        }
    assert migrator.up() == ()
    assert migrator.down(
        BASELINE, allow_multiple=True, allow_destructive=True
    ) == ("0005", "0004", "0003", "0002", "0001")
    with psycopg.connect(migration_database) as connection:
        assert _public_tables(connection) == {
            "schema_migration",
            "schema_migration_history",
        }
    assert migrator.up() == ("0001", "0002", "0003", "0004", "0005")


def test_every_table_is_classified_with_required_rls(migrated_database: str) -> None:
    with psycopg.connect(migrated_database) as connection:
        flags = _rls_flags(connection)
        assert set(flags) == set(TENANCY_CLASSIFICATION)
        for table, (enabled, forced) in flags.items():
            scope = TENANCY_CLASSIFICATION[table]
            expected = scope is not TenancyScope.GLOBAL
            assert (enabled, forced) == (expected, expected), table
        for table in flags:
            assert _table_policies(connection, table) == set(
                REQUIRED_POLICIES[TENANCY_CLASSIFICATION[table]]
            ), table


def test_application_role_cannot_bypass_row_security(migrated_database: str) -> None:
    with psycopg.connect(migrated_database) as connection:
        connection.execute(f"SET ROLE {APP_ROLE}")
        assert connection.execute(
            "SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user"
        ).fetchone() == (False,)


def _seed_two_tenants(dsn: str) -> dict[str, uuid.UUID]:
    ids = {
        "tenant_a": uuid.uuid4(),
        "tenant_b": uuid.uuid4(),
        "project_a": uuid.uuid4(),
        "project_b": uuid.uuid4(),
        "user_a": uuid.uuid4(),
        "user_b": uuid.uuid4(),
    }
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "INSERT INTO tenant (tenant_id, name) VALUES (%s, 'A'), (%s, 'B')",
            (ids["tenant_a"], ids["tenant_b"]),
        )
        connection.execute(
            "INSERT INTO app_user (user_id, tenant_id, subject) "
            "VALUES (%s, %s, 'sub-a'), (%s, %s, 'sub-b')",
            (ids["user_a"], ids["tenant_a"], ids["user_b"], ids["tenant_b"]),
        )
        connection.execute(
            "INSERT INTO project (project_id, tenant_id, customer_name, name) "
            "VALUES (%s, %s, 'Customer A', 'Project A'), "
            "(%s, %s, 'Customer B', 'Project B')",
            (ids["project_a"], ids["tenant_a"], ids["project_b"], ids["tenant_b"]),
        )
        connection.commit()
    return ids


def test_cross_tenant_access_is_denied_under_app_role(migrated_database: str) -> None:
    ids = _seed_two_tenants(migrated_database)
    with app_role_session(migrated_database, tenant_id=ids["tenant_a"]) as connection:
        visible = {
            row[0]
            for row in connection.execute("SELECT tenant_id FROM app_user").fetchall()
        }
        assert visible == {ids["tenant_a"]}
        assert {
            row[0] for row in connection.execute("SELECT tenant_id FROM tenant").fetchall()
        } == {ids["tenant_a"]}

    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        app_role_session(migrated_database, tenant_id=ids["tenant_a"]) as connection,
    ):
        connection.execute(
            "INSERT INTO app_user (tenant_id, subject) VALUES (%s, 'intruder')",
            (ids["tenant_b"],),
        )


def test_cross_project_access_is_denied_under_app_role(migrated_database: str) -> None:
    ids = _seed_two_tenants(migrated_database)
    with app_role_session(migrated_database, tenant_id=ids["tenant_a"]) as connection:
        assert connection.execute("SELECT project_id FROM project").fetchall() == []

    with app_role_session(
        migrated_database,
        tenant_id=ids["tenant_a"],
        project_id=ids["project_a"],
    ) as connection:
        assert connection.execute("SELECT project_id FROM project").fetchall() == [
            (ids["project_a"],)
        ]

    with app_role_session(
        migrated_database,
        tenant_id=ids["tenant_a"],
        project_id=ids["project_b"],
    ) as connection:
        assert connection.execute("SELECT project_id FROM project").fetchall() == []

    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        app_role_session(migrated_database, tenant_id=ids["tenant_a"]) as connection,
    ):
        connection.execute(
            "INSERT INTO project (tenant_id, customer_name, name) "
            "VALUES (%s, 'Customer A', 'Unscoped')",
            (ids["tenant_a"],),
        )


def test_missing_context_fails_closed(migrated_database: str) -> None:
    _seed_two_tenants(migrated_database)
    with app_role_session(migrated_database) as connection:
        assert connection.execute("SELECT count(*) FROM app_user").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM project").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM tenant").fetchone() == (0,)

    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        app_role_session(migrated_database) as connection,
    ):
        connection.execute("INSERT INTO tenant (name) VALUES ('sneaky')")


def test_context_is_transaction_local(migrated_database: str) -> None:
    ids = _seed_two_tenants(migrated_database)
    with psycopg.connect(migrated_database, autocommit=True) as connection:
        connection.execute(f"SET ROLE {APP_ROLE}")
        with connection.transaction():
            connection.execute(
                "SELECT cairn_set_tenant_context(%s)",
                (signed_assertion(ids["tenant_a"]),),
            )
            assert connection.execute("SELECT count(*) FROM tenant").fetchone() == (1,)
        with connection.transaction():
            assert connection.execute("SELECT count(*) FROM tenant").fetchone() == (0,)


def test_rls_policy_names_match_the_tenancy_contract(migrated_database: str) -> None:
    with psycopg.connect(migrated_database) as connection:
        assert _table_policies(connection, "project") == {TENANT_POLICY, PROJECT_POLICY}
        assert _table_policies(connection, "app_user") == {TENANT_POLICY}


def test_project_policy_is_restrictive(migrated_database: str) -> None:
    with psycopg.connect(migrated_database) as connection:
        rows = connection.execute(
            "SELECT policyname, permissive FROM pg_policies "
            "WHERE schemaname = 'public' AND tablename = 'project'"
        ).fetchall()
    modes = dict(rows)
    assert modes == {TENANT_POLICY: "PERMISSIVE", PROJECT_POLICY: "RESTRICTIVE"}
