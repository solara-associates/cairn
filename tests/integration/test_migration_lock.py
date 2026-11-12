import threading
from concurrent.futures import ThreadPoolExecutor

import psycopg
from cairn_adapters.persistence_postgres.migrator import LOCK_KEY, Migration, Migrator
from psycopg import ClientCursor


def _hold_lock(dsn: str) -> psycopg.Connection:
    connection = psycopg.connect(dsn, cursor_factory=ClientCursor)
    connection.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
    return connection


def _release(connection: psycopg.Connection) -> None:
    connection.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
    connection.commit()
    connection.close()


def test_up_waits_for_the_migration_lock(migration_database: str) -> None:
    holder = _hold_lock(migration_database)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(Migrator(migration_database).up)
            threading.Event().wait(0.5)
            assert not future.done()
            _release(holder)
            holder = None
            applied = future.result(timeout=30)
        assert applied == ("0001", "0002", "0003", "0004")
    finally:
        if holder is not None:
            _release(holder)


def test_concurrent_up_applies_each_migration_once(migration_database: str) -> None:
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(Migrator(migration_database).up) for _ in range(2)]
        results = [future.result(timeout=60) for future in futures]
    applied_versions = [version for result in results for version in result]
    assert sorted(applied_versions) == ["0001", "0002", "0003", "0004"]
    assert Migrator(migration_database).applied_versions() == (
        "0001",
        "0002",
        "0003",
        "0004",
    )


def test_down_waits_for_the_migration_lock(migration_database: str) -> None:
    migrator = Migrator(migration_database)
    migrator.up()
    holder = _hold_lock(migration_database)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                migrator.down, "0003", allow_destructive=True
            )
            threading.Event().wait(0.5)
            assert not future.done()
            _release(holder)
            holder = None
            assert future.result(timeout=30) == ("0004",)
    finally:
        if holder is not None:
            _release(holder)


def test_lock_is_released_after_failure(migration_database: str) -> None:
    migrator = Migrator(
        migration_database,
        migrations=(
            Migration(
                version="0001",
                name="broken",
                up_sql="SELECT 1; SELECT missing_function();",
                down_sql="SELECT 1",
            ),
        ),
    )
    try:
        migrator.up()
    except psycopg.Error:
        pass
    else:
        raise AssertionError("the broken migration should fail")
    with psycopg.connect(migration_database, cursor_factory=ClientCursor) as connection:
        assert connection.execute(
            "SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,)
        ).fetchone() == (True,)
