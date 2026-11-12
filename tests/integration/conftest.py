import os
import subprocess
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from cairn_adapters.persistence_postgres.migrator import Migrator
from cairn_kernel.hex import ProjectId, TenantId
from cairn_kernel.security import sign_tenant_assertion

POSTGRES_IMAGE = "postgres:16-alpine"
APP_ROLE = "cairn_app"
TENANT_CONTEXT_SECRET = b"test-tenant-context-secret"


def _docker_available() -> bool:
    try:
        completed = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    return completed.returncode == 0


def _start_container() -> tuple[str, str]:
    started = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "-e",
            "POSTGRES_PASSWORD=postgres",
            "-e",
            "POSTGRES_DB=postgres",
            "-p",
            "127.0.0.1:0:5432",
            POSTGRES_IMAGE,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if started.returncode != 0:
        raise RuntimeError(f"could not start postgres container: {started.stderr}")
    container_id = started.stdout.strip()
    published = subprocess.run(
        ["docker", "port", container_id, "5432/tcp"],
        capture_output=True,
        text=True,
        check=False,
    )
    host_port = published.stdout.strip().rsplit(":", 1)[1]
    return container_id, f"postgresql://postgres:postgres@127.0.0.1:{host_port}/postgres"


def _wait_ready(dsn: str, timeout_seconds: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=2):
                return
        except psycopg.OperationalError as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"postgres did not become ready: {last_error}")


@pytest.fixture(scope="session")
def postgres_dsn() -> Iterator[str]:
    env_dsn = os.environ.get("CAIRN_TEST_DATABASE_URL")
    if env_dsn:
        _wait_ready(env_dsn)
        yield env_dsn
        return
    if not _docker_available():
        pytest.skip(
            "set CAIRN_TEST_DATABASE_URL or start Docker to run Postgres integration tests"
        )
    container_id, dsn = _start_container()
    try:
        _wait_ready(dsn)
        yield dsn
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container_id],
            capture_output=True,
            check=False,
        )


@pytest.fixture(scope="session")
def app_role(postgres_dsn: str) -> str:
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        connection.execute(
            "DO $$ BEGIN "
            f"IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN "
            f"CREATE ROLE {APP_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE; "
            "END IF; END $$;"
        )
    return APP_ROLE


def _database_dsn(base_dsn: str, database: str) -> str:
    return base_dsn.rsplit("/", 1)[0] + "/" + database


@pytest.fixture()
def migration_database(postgres_dsn: str, app_role: str) -> Iterator[str]:
    database = f"cairn_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        connection.execute(f'CREATE DATABASE "{database}"')
    try:
        yield _database_dsn(postgres_dsn, database)
    finally:
        with psycopg.connect(postgres_dsn, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                (database,),
            )
            connection.execute(f'DROP DATABASE "{database}"')


def grant_application_role(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
        connection.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}"
        )
        connection.execute(f"REVOKE UPDATE, DELETE ON ledger_entry FROM {APP_ROLE}")
        connection.execute(
            f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO {APP_ROLE}"
        )
        connection.execute(
            "INSERT INTO tenant_context_secret (name, secret) VALUES (%s, %s)"
            " ON CONFLICT (name) DO UPDATE SET secret = EXCLUDED.secret",
            ("tenant-context", TENANT_CONTEXT_SECRET),
        )


@pytest.fixture()
def migrated_database(migration_database: str) -> Iterator[str]:
    Migrator(migration_database).up()
    grant_application_role(migration_database)
    yield migration_database


def signed_assertion(
    tenant_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    *,
    actor_id: str = "test-actor",
    ttl: timedelta = timedelta(minutes=5),
    secret: bytes = TENANT_CONTEXT_SECRET,
) -> str:
    return sign_tenant_assertion(
        secret=secret,
        tenant_id=TenantId(str(tenant_id)),
        actor_id=actor_id,
        expires_at=datetime.now(UTC) + ttl,
        project_id=None if project_id is None else ProjectId(str(project_id)),
    )
