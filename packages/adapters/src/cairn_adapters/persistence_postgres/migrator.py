import argparse
import getpass
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import psycopg
from psycopg import ClientCursor

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
MIGRATION_FILE_PATTERN = re.compile(
    r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.(?P<direction>up|down)\.sql$"
)
LEDGER_TABLE = "schema_migration"
HISTORY_TABLE = "schema_migration_history"
BASELINE = "0000"
LOCK_KEY = 0x636169726E
PRODUCTION_ENVIRONMENTS = frozenset({"production", "prod"})
DESTRUCTIVE_STATEMENTS = re.compile(
    r"\b(?:DROP\s+(?:TABLE|COLUMN|SCHEMA|TYPE|FUNCTION|INDEX|TRIGGER|POLICY)"
    r"|TRUNCATE|DELETE\s+FROM)\b",
    re.IGNORECASE,
)


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Migration:
    version: str
    name: str
    up_sql: str
    down_sql: str


def discover_migrations(directory: Path = MIGRATIONS_DIR) -> tuple[Migration, ...]:
    scripts: dict[str, dict[str, str | None]] = {}
    names: dict[str, str] = {}
    for path in sorted(directory.glob("*.sql")):
        match = MIGRATION_FILE_PATTERN.match(path.name)
        if match is None:
            raise MigrationError(f"{path.name} is not a valid migration file name")
        version = match["version"]
        name = match["name"]
        direction = match["direction"]
        known_name = names.setdefault(version, name)
        if known_name != name:
            raise MigrationError(
                f"migration {version} has conflicting names: {known_name} and {name}"
            )
        scripts.setdefault(version, {"up": None, "down": None})[direction] = path.read_text(
            encoding="utf-8"
        )

    migrations: list[Migration] = []
    for version in sorted(scripts):
        up_sql = scripts[version]["up"]
        down_sql = scripts[version]["down"]
        if up_sql is None or down_sql is None:
            raise MigrationError(f"migration {version} needs both up and down scripts")
        migrations.append(
            Migration(version=version, name=names[version], up_sql=up_sql, down_sql=down_sql)
        )

    expected = [f"{index:04d}" for index in range(1, len(migrations) + 1)]
    actual = [migration.version for migration in migrations]
    if actual != expected:
        raise MigrationError(f"migration versions must be contiguous: {actual}")
    return tuple(migrations)


def is_destructive(sql: str) -> bool:
    return DESTRUCTIVE_STATEMENTS.search(sql) is not None


def _is_production() -> bool:
    return os.environ.get("CAIRN_ENVIRONMENT", "").strip().lower() in PRODUCTION_ENVIRONMENTS


class Migrator:
    def __init__(
        self,
        dsn: str,
        migrations: tuple[Migration, ...] | None = None,
        *,
        operator: str | None = None,
    ) -> None:
        self._dsn = dsn
        self._migrations = migrations if migrations is not None else discover_migrations()
        self._operator = (
            operator
            or os.environ.get("CAIRN_MIGRATION_OPERATOR")
            or getpass.getuser()
        )

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._dsn, cursor_factory=ClientCursor)

    def _ensure_ledger(self, connection: psycopg.Connection) -> None:
        connection.execute(
            f"CREATE TABLE IF NOT EXISTS {LEDGER_TABLE} ("
            "version text PRIMARY KEY,"
            "name text NOT NULL,"
            "applied_at timestamptz NOT NULL DEFAULT now()"
            ")"
        )
        connection.execute(
            f"CREATE TABLE IF NOT EXISTS {HISTORY_TABLE} ("
            "history_id bigserial PRIMARY KEY,"
            "version text NOT NULL,"
            "name text NOT NULL,"
            "direction text NOT NULL CHECK (direction IN ('up', 'down')),"
            "outcome text NOT NULL CHECK (outcome IN ('applied', 'reverted', 'failed')),"
            "operator_name text NOT NULL,"
            "executed_at timestamptz NOT NULL DEFAULT now(),"
            "recovery_reference text"
            ")"
        )

    def _record(
        self,
        version: str,
        name: str,
        direction: str,
        outcome: str,
        *,
        recovery_reference: str | None = None,
    ) -> None:
        with self._connect() as connection:
            self._ensure_ledger(connection)
            connection.execute(
                f"INSERT INTO {HISTORY_TABLE}"
                " (version, name, direction, outcome, operator_name, recovery_reference)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    version,
                    name,
                    direction,
                    outcome,
                    self._operator,
                    recovery_reference,
                ),
            )
            connection.commit()

    def applied_versions(self) -> tuple[str, ...]:
        with self._connect() as connection:
            self._ensure_ledger(connection)
            rows = connection.execute(
                f"SELECT version FROM {LEDGER_TABLE} ORDER BY version"
            ).fetchall()
            connection.commit()
        return tuple(row[0] for row in rows)

    def history(self) -> tuple[tuple[str, str, str], ...]:
        with self._connect() as connection:
            self._ensure_ledger(connection)
            rows = connection.execute(
                f"SELECT version, direction, outcome FROM {HISTORY_TABLE}"
                " ORDER BY history_id"
            ).fetchall()
            connection.commit()
        return tuple((row[0], row[1], row[2]) for row in rows)

    def up(self) -> tuple[str, ...]:
        with self._lock():
            return self._up()

    def _up(self) -> tuple[str, ...]:
        applied = set(self.applied_versions())
        pending = [migration for migration in self._migrations if migration.version not in applied]
        for migration in pending:
            with self._connect() as connection:
                connection.execute(migration.up_sql)
                connection.execute(
                    f"INSERT INTO {LEDGER_TABLE} (version, name) VALUES (%s, %s)",
                    (migration.version, migration.name),
                )
                connection.commit()
            self._record(migration.version, migration.name, "up", "applied")
        return tuple(migration.version for migration in pending)

    def down(
        self,
        target: str,
        *,
        allow_multiple: bool = False,
        allow_destructive: bool = False,
        recovery_reference: str | None = None,
    ) -> tuple[str, ...]:
        with self._lock():
            return self._down(
                target,
                allow_multiple=allow_multiple,
                allow_destructive=allow_destructive,
                recovery_reference=recovery_reference,
            )

    def _down(
        self,
        target: str,
        *,
        allow_multiple: bool = False,
        allow_destructive: bool = False,
        recovery_reference: str | None = None,
    ) -> tuple[str, ...]:
        if not target:
            raise MigrationError("rollback requires an explicit target version")
        known = self._by_version()
        if target != BASELINE and target not in known:
            raise MigrationError(f"unknown rollback target: {target}")
        applied = self.applied_versions()
        if target != BASELINE and target not in applied:
            raise MigrationError(f"rollback target is not applied: {target}")
        to_revert = [version for version in applied if version > target]
        if not to_revert:
            raise MigrationError(f"nothing to revert above {target}")
        if len(to_revert) > 1 and not allow_multiple:
            raise MigrationError(
                "refusing multi-step rollback; revert one migration at a time"
                " or pass allow_multiple"
            )
        destructive = [
            version for version in to_revert if is_destructive(known[version].down_sql)
        ]
        if destructive and not allow_destructive:
            raise MigrationError(
                f"refusing destructive rollback of {', '.join(destructive)};"
                " pass allow_destructive after review"
            )
        if destructive and _is_production() and not recovery_reference:
            raise MigrationError(
                "production rollback of destructive migrations requires"
                " a recovery reference"
            )
        reverted: list[str] = []
        for version in reversed(to_revert):
            migration = known[version]
            try:
                with self._connect() as connection:
                    connection.execute(migration.down_sql)
                    connection.execute(
                        f"DELETE FROM {LEDGER_TABLE} WHERE version = %s", (version,)
                    )
                    connection.commit()
            except Exception:
                self._record(
                    migration.version,
                    migration.name,
                    "down",
                    "failed",
                    recovery_reference=recovery_reference,
                )
                raise
            self._record(
                migration.version,
                migration.name,
                "down",
                "reverted",
                recovery_reference=recovery_reference,
            )
            reverted.append(version)
        return tuple(reverted)

    def _lock(self) -> "_AdvisoryLock":
        return _AdvisoryLock(self)

    def _by_version(self) -> dict[str, Migration]:
        return {migration.version: migration for migration in self._migrations}


class _AdvisoryLock:
    def __init__(self, migrator: Migrator) -> None:
        self._migrator = migrator
        self._connection: psycopg.Connection | None = None

    def __enter__(self) -> Self:
        self._connection = self._migrator._connect()
        self._connection.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
        return self

    def __exit__(self, *exc_info: object) -> None:
        assert self._connection is not None
        self._connection.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
        self._connection.commit()
        self._connection.close()
        self._connection = None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cairn-migrate",
        description="Apply or revert CAIRN Postgres migrations.",
    )
    parser.add_argument("command", choices=("up", "down", "status"))
    parser.add_argument("--dsn", default=os.environ.get("CAIRN_DATABASE_URL"))
    parser.add_argument("--to", dest="target", help="applied version to roll back to")
    parser.add_argument("--allow-multiple", action="store_true")
    parser.add_argument("--allow-destructive", action="store_true")
    parser.add_argument("--recovery-reference")
    args = parser.parse_args(argv)
    if not args.dsn:
        print("cairn-migrate: set CAIRN_DATABASE_URL or pass --dsn")
        return 2

    migrator = Migrator(args.dsn)
    if args.command == "status":
        applied = migrator.applied_versions()
        for migration in migrator._by_version().values():
            state = "applied" if migration.version in applied else "pending"
            print(f"{migration.version} {migration.name} {state}")
        return 0
    if args.command == "down":
        if not args.target:
            print("cairn-migrate: down requires --to VERSION")
            return 2
        try:
            changed = migrator.down(
                args.target,
                allow_multiple=args.allow_multiple,
                allow_destructive=args.allow_destructive,
                recovery_reference=args.recovery_reference,
            )
        except MigrationError as exc:
            print(f"cairn-migrate: {exc}")
            return 2
        print(f"down: {len(changed)} migration(s) reverted")
        return 0
    changed = migrator.up()
    print(f"up: {len(changed)} migration(s) applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
