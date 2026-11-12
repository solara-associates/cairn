import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

import psycopg
import pytest
from conftest import APP_ROLE, TENANT_CONTEXT_SECRET, signed_assertion

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
        connection.execute(
            "INSERT INTO app_user (tenant_id, subject) VALUES (%s, 'a'), (%s, 'b')",
            (TENANT_A, TENANT_B),
        )


@contextmanager
def _as_app(dsn: str, assertion: str | None = None) -> Iterator[psycopg.Connection]:
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(f"SET ROLE {APP_ROLE}")
        with connection.transaction():
            if assertion is not None:
                connection.execute(
                    "SELECT cairn_set_tenant_context(%s)", (assertion,)
                )
            yield connection


def test_assertion_binds_the_tenant_context(migrated_database: str) -> None:
    _seed(migrated_database)
    with _as_app(migrated_database, signed_assertion(TENANT_A)) as connection:
        tenant = connection.execute("SELECT cairn_current_tenant()").fetchone()
        assert tenant == (TENANT_A,)


def test_spoofed_session_tenant_does_not_change_scope(migrated_database: str) -> None:
    _seed(migrated_database)
    with _as_app(migrated_database, signed_assertion(TENANT_A)) as connection:
        connection.execute(
            "SELECT set_config('app.tenant_id', %s, true)", (str(TENANT_B),)
        )
        rows = connection.execute("SELECT tenant_id FROM tenant").fetchall()
        assert rows == [(TENANT_A,)]


def test_forged_assertion_is_ignored(migrated_database: str) -> None:
    _seed(migrated_database)
    forged = signed_assertion(TENANT_B, secret=b"not-the-secret")
    with _as_app(migrated_database) as connection:
        connection.execute(
            "SELECT set_config('app.tenant_assertion', %s, true)", (forged,)
        )
        assert connection.execute("SELECT count(*) FROM tenant").fetchone() == (0,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT cairn_set_tenant_context(%s)", (forged,))


def test_expired_assertion_is_rejected(migrated_database: str) -> None:
    _seed(migrated_database)
    expired = signed_assertion(TENANT_A, ttl=timedelta(minutes=-1))
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        _as_app(migrated_database) as connection,
    ):
        connection.execute("SELECT cairn_set_tenant_context(%s)", (expired,))


def test_missing_context_denies_access(migrated_database: str) -> None:
    _seed(migrated_database)
    with _as_app(migrated_database) as connection:
        for table in ("tenant", "app_user", "project", "role_grant"):
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone() == (
                0,
            )


def test_cross_tenant_insert_is_denied(migrated_database: str) -> None:
    _seed(migrated_database)
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        _as_app(migrated_database, signed_assertion(TENANT_A)) as connection,
    ):
        connection.execute(
            "INSERT INTO app_user (tenant_id, subject) VALUES (%s, 'intruder')",
            (TENANT_B,),
        )


def test_cross_tenant_update_is_denied(migrated_database: str) -> None:
    _seed(migrated_database)
    with _as_app(migrated_database, signed_assertion(TENANT_A)) as connection:
        result = connection.execute(
            "UPDATE app_user SET subject = 'hijacked' WHERE tenant_id = %s",
            (TENANT_B,),
        )
        assert result.rowcount == 0
        assert connection.execute(
            "SELECT count(*) FROM app_user WHERE tenant_id = %s AND subject = 'b'",
            (TENANT_B,),
        ).fetchone() == (0,)
    with psycopg.connect(migrated_database) as owner:
        assert owner.execute(
            "SELECT subject FROM app_user WHERE tenant_id = %s", (TENANT_B,)
        ).fetchone() == ("b",)


def test_project_context_must_be_in_the_assertion(migrated_database: str) -> None:
    _seed(migrated_database)
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        _as_app(migrated_database, signed_assertion(TENANT_A)) as connection,
    ):
        connection.execute("SELECT cairn_set_project_context(%s)", (PROJECT_A,))

    with _as_app(
        migrated_database, signed_assertion(TENANT_A, PROJECT_A)
    ) as scoped:
        scoped.execute("SELECT cairn_set_project_context(%s)", (PROJECT_A,))
        assert scoped.execute("SELECT project_id FROM project").fetchall() == [
            (PROJECT_A,)
        ]


def test_project_from_another_tenant_is_rejected(migrated_database: str) -> None:
    _seed(migrated_database)
    with _as_app(
        migrated_database, signed_assertion(TENANT_A, PROJECT_B)
    ) as connection:
        assert connection.execute("SELECT count(*) FROM project").fetchone() == (0,)
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        _as_app(
            migrated_database, signed_assertion(TENANT_A, PROJECT_B)
        ) as connection,
    ):
        connection.execute("SELECT cairn_set_project_context(%s)", (PROJECT_A,))


def test_context_is_transaction_local(migrated_database: str) -> None:
    _seed(migrated_database)
    with psycopg.connect(migrated_database, autocommit=True) as connection:
        connection.execute(f"SET ROLE {APP_ROLE}")
        with connection.transaction():
            connection.execute(
                "SELECT cairn_set_tenant_context(%s)",
                (signed_assertion(TENANT_A),),
            )
            assert connection.execute("SELECT count(*) FROM tenant").fetchone() == (
                1,
            )
        with connection.transaction():
            assert connection.execute("SELECT count(*) FROM tenant").fetchone() == (
                0,
            )


def test_secret_rotation_invalidates_old_assertions(migrated_database: str) -> None:
    _seed(migrated_database)
    old = signed_assertion(TENANT_A)
    rotated = TENANT_CONTEXT_SECRET + b"-rotated"
    with psycopg.connect(migrated_database, autocommit=True) as owner:
        owner.execute(
            "UPDATE tenant_context_secret SET secret = %s WHERE name = %s",
            (rotated, "tenant-context"),
        )
    try:
        with (
            pytest.raises(psycopg.errors.InsufficientPrivilege),
            _as_app(migrated_database) as connection,
        ):
            connection.execute("SELECT cairn_set_tenant_context(%s)", (old,))
    finally:
        with psycopg.connect(migrated_database, autocommit=True) as owner:
            owner.execute(
                "UPDATE tenant_context_secret SET secret = %s WHERE name = %s",
                (TENANT_CONTEXT_SECRET, "tenant-context"),
            )


def test_application_role_is_not_a_member_of_administrative_roles(
    migrated_database: str,
) -> None:
    with psycopg.connect(migrated_database, autocommit=True) as connection:
        assert connection.execute(
            "SELECT pg_has_role(%s, 'postgres', 'member')", (APP_ROLE,)
        ).fetchone() == (False,)
        assert connection.execute(
            "SELECT rolbypassrls FROM pg_roles WHERE rolname = %s", (APP_ROLE,)
        ).fetchone() == (False,)
