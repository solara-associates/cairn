import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import ClientCursor

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
MIGRATION_FILE_PATTERN = re.compile(
    r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.(?P<direction>up|down)\.sql$"
)
LEDGER_TABLE = "schema_migration"


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


class Migrator:
    def __init__(
        self,
        dsn: str,
        migrations: tuple[Migration, ...] | None = None,
    ) -> None:
        self._dsn = dsn
        self._migrations = migrations if migrations is not None else discover_migrations()

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

    def applied_versions(self) -> tuple[str, ...]:
        with self._connect() as connection:
            self._ensure_ledger(connection)
            rows = connection.execute(
                f"SELECT version FROM {LEDGER_TABLE} ORDER BY version"
            ).fetchall()
            connection.commit()
        return tuple(row[0] for row in rows)

    def up(self) -> tuple[str, ...]:
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
        return tuple(migration.version for migration in pending)

    def down(self) -> tuple[str, ...]:
        applied = self.applied_versions()
        reverted: list[str] = []
        for version in reversed(applied):
            migration = self._by_version()[version]
            with self._connect() as connection:
                connection.execute(migration.down_sql)
                connection.execute(f"DELETE FROM {LEDGER_TABLE} WHERE version = %s", (version,))
                connection.commit()
            reverted.append(version)
        return tuple(reverted)

    def _by_version(self) -> dict[str, Migration]:
        return {migration.version: migration for migration in self._migrations}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cairn-migrate",
        description="Apply or revert CAIRN Postgres migrations.",
    )
    parser.add_argument("command", choices=("up", "down", "status"))
    parser.add_argument("--dsn", default=os.environ.get("CAIRN_DATABASE_URL"))
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
    changed = migrator.up() if args.command == "up" else migrator.down()
    print(f"{args.command}: {len(changed)} migration(s) {'applied' if args.command == 'up' else 'reverted'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
