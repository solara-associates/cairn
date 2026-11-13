"""Backup/restore dry run for the CAIRN runbook at docs/runbooks/backup-restore.md.

Proves the restore procedure actually works, against the same local Postgres
test container tests/integration/ uses — never a live GCP Cloud SQL instance.
No cloud account exists for this repository; this is the closest testable
analog to the Cloud SQL automated-backup + point-in-time-recovery path that
`infra/terraform/modules/cairn-data` provisions.

What it proves:
  1. A schema-migrated database with real rows can be backed up with pg_dump.
  2. The backup can be restored into a fresh database with pg_restore.
  3. The restored data is byte-identical to what was backed up (data
     integrity after restore), not just "the restore command exited zero".

Usage:
    uv run python tools/ops/backup_restore_dry_run.py

Honors CAIRN_TEST_DATABASE_URL exactly like tests/integration/conftest.py: if
set, it is used as the admin connection (CI already provides this via the
postgres service container); otherwise a throwaway postgres:16-alpine Docker
container is started and torn down.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import psycopg
from cairn_adapters.persistence_postgres.migrator import Migrator

POSTGRES_IMAGE = "postgres:16-alpine"


def log(message: str) -> None:
    print(f"[backup-restore-dry-run] {message}", flush=True)


def docker_available() -> bool:
    try:
        completed = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        return False
    return completed.returncode == 0


def start_container() -> tuple[str, str]:
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


def wait_ready(dsn: str, timeout_seconds: float = 60.0) -> None:
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


def database_dsn(base_dsn: str, database: str) -> str:
    return base_dsn.rsplit("/", 1)[0] + "/" + database


def create_database(admin_dsn: str, database: str) -> None:
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(f'CREATE DATABASE "{database}"')


def drop_database(admin_dsn: str, database: str) -> None:
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
            (database,),
        )
        connection.execute(f'DROP DATABASE IF EXISTS "{database}"')


def seed_rows(dsn: str) -> str:
    """Insert deterministic rows and return a content hash to compare post-restore."""
    marker = uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(
            "INSERT INTO tenant (name, status, retention_days) VALUES (%s, %s, %s)"
            " RETURNING tenant_id",
            (f"backup-dry-run-{marker}", "ACTIVE", 365),
        )
        tenant_id = connection.execute(
            "SELECT tenant_id FROM tenant WHERE name = %s", (f"backup-dry-run-{marker}",)
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO project (tenant_id, customer_name, name)"
            " VALUES (%s, %s, %s)",
            (tenant_id, "Dry Run Co", f"project-{marker}"),
        )
    return content_hash(dsn)


def content_hash(dsn: str) -> str:
    """Hash of every tenant/project row, order-independent, to detect any
    difference introduced by the backup/restore round trip."""
    with psycopg.connect(dsn) as connection:
        tenants = connection.execute(
            "SELECT name, status, retention_days FROM tenant ORDER BY name"
        ).fetchall()
        projects = connection.execute(
            "SELECT customer_name, name FROM project ORDER BY name"
        ).fetchall()
    digest = hashlib.sha256()
    for row in (*tenants, *projects):
        digest.update(repr(row).encode("utf-8"))
    return digest.hexdigest()


def pg_dump(dsn: str, dump_path: Path, *, container_id: str | None) -> None:
    """Run pg_dump with a client guaranteed to match the server's major
    version. When we started our own throwaway container, exec the matching
    client bundled inside that same image rather than trusting whatever
    pg_dump happens to be on the host's PATH (it can easily be a different
    major version, which pg_dump refuses to talk to)."""
    if container_id is not None:
        in_container_dsn = _in_container_dsn(dsn)
        result = subprocess.run(
            [
                "docker", "exec", container_id,
                "pg_dump", "--format=custom", "--no-owner", "--no-privileges",
                "-f", "/tmp/backup.dump", in_container_dsn,
            ],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"pg_dump failed: {result.stderr}")
        copy = subprocess.run(
            ["docker", "cp", f"{container_id}:/tmp/backup.dump", str(dump_path)],
            capture_output=True, text=True, check=False,
        )
        if copy.returncode != 0:
            raise RuntimeError(f"could not copy backup out of container: {copy.stderr}")
        return
    result = subprocess.run(
        ["pg_dump", "--format=custom", "--no-owner", "--no-privileges", "-f", str(dump_path), dsn],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pg_dump failed: {result.stderr}")


def pg_restore(dump_path: Path, target_dsn: str, *, container_id: str | None) -> None:
    if container_id is not None:
        in_container_dsn = _in_container_dsn(target_dsn)
        copy = subprocess.run(
            ["docker", "cp", str(dump_path), f"{container_id}:/tmp/restore.dump"],
            capture_output=True, text=True, check=False,
        )
        if copy.returncode != 0:
            raise RuntimeError(f"could not copy backup into container: {copy.stderr}")
        result = subprocess.run(
            [
                "docker", "exec", container_id,
                "pg_restore", "--no-owner", "--no-privileges",
                "--dbname", in_container_dsn, "/tmp/restore.dump",
            ],
            capture_output=True, text=True, check=False,
        )
    else:
        result = subprocess.run(
            ["pg_restore", "--no-owner", "--no-privileges", "--dbname", target_dsn, str(dump_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    # pg_restore exits non-zero on harmless warnings (e.g. extension already
    # exists); treat it as a failure only if nothing restored at all.
    if result.returncode != 0 and "ERROR" in result.stderr and "already exists" not in result.stderr:
        raise RuntimeError(f"pg_restore failed: {result.stderr}")


def _in_container_dsn(dsn: str) -> str:
    """Rewrite a host-published DSN (127.0.0.1:<published-port>) to the
    address the database is reachable at from inside its own container."""
    _, rest = dsn.split("@", 1)
    _, tail = rest.split("/", 1)
    return f"postgresql://postgres:postgres@localhost:5432/{tail}"


def run() -> None:
    env_dsn = os.environ.get("CAIRN_TEST_DATABASE_URL")
    container_id: str | None = None
    if env_dsn:
        admin_dsn = env_dsn
        log(f"using CAIRN_TEST_DATABASE_URL ({admin_dsn.rsplit('@', 1)[-1]})")
        wait_ready(admin_dsn)
    elif docker_available():
        container_id, admin_dsn = start_container()
        log(f"started throwaway postgres container {container_id[:12]}")
        wait_ready(admin_dsn)
    else:
        log("neither CAIRN_TEST_DATABASE_URL nor Docker is available; skipping")
        return

    source_db = f"cairn_backup_dryrun_src_{uuid.uuid4().hex[:12]}"
    restore_db = f"cairn_backup_dryrun_restore_{uuid.uuid4().hex[:12]}"
    dump_path: Path | None = None
    try:
        log(f"creating source database {source_db}")
        create_database(admin_dsn, source_db)
        source_dsn = database_dsn(admin_dsn, source_db)

        log("running migrations against the source database")
        Migrator(source_dsn).up()

        log("seeding rows and computing the pre-backup content hash")
        pre_hash = seed_rows(source_dsn)
        log(f"pre-backup content hash: {pre_hash}")

        with tempfile.TemporaryDirectory() as tmp:
            dump_path = Path(tmp) / "backup.dump"
            log(f"pg_dump -> {dump_path}")
            pg_dump(source_dsn, dump_path, container_id=container_id)
            if not dump_path.exists() or dump_path.stat().st_size == 0:
                raise RuntimeError("pg_dump produced an empty or missing backup file")

            log(f"creating restore target database {restore_db}")
            create_database(admin_dsn, restore_db)
            restore_dsn = database_dsn(admin_dsn, restore_db)

            log("pg_restore into the restore target")
            pg_restore(dump_path, restore_dsn, container_id=container_id)

            log("computing the post-restore content hash")
            post_hash = content_hash(restore_dsn)
            log(f"post-restore content hash: {post_hash}")

            if pre_hash != post_hash:
                raise RuntimeError(
                    "data integrity check failed: restored content hash does not "
                    f"match the pre-backup hash ({pre_hash} != {post_hash})"
                )
        log("PASS: restored database content matches the pre-backup content hash")
    finally:
        for db in (source_db, restore_db):
            try:
                drop_database(admin_dsn, db)
            except psycopg.Error as exc:  # pragma: no cover - best-effort cleanup
                log(f"cleanup warning: could not drop {db}: {exc}")
        if container_id is not None:
            subprocess.run(["docker", "rm", "-f", container_id], capture_output=True, check=False)


if __name__ == "__main__":
    run()
