from pathlib import Path

import pytest
from cairn_adapters.persistence_postgres.migrator import (
    MigrationError,
    discover_migrations,
)


def _write(directory: Path, name: str, content: str = "") -> None:
    (directory / name).write_text(content, encoding="utf-8")


def test_default_migrations_are_the_tenancy_baseline() -> None:
    migrations = discover_migrations()
    assert [migration.version for migration in migrations] == ["0001", "0002"]
    assert [migration.name for migration in migrations] == [
        "tenancy_baseline",
        "tenant_rls",
    ]


def test_discover_migrations_orders_by_version(tmp_path: Path) -> None:
    _write(tmp_path, "0002_second.up.sql", "SELECT 2;")
    _write(tmp_path, "0002_second.down.sql", "SELECT -2;")
    _write(tmp_path, "0001_first.up.sql", "SELECT 1;")
    _write(tmp_path, "0001_first.down.sql", "SELECT -1;")
    migrations = discover_migrations(tmp_path)
    assert [migration.version for migration in migrations] == ["0001", "0002"]
    assert migrations[0].up_sql == "SELECT 1;"
    assert migrations[1].down_sql == "SELECT -2;"


def test_discover_migrations_requires_down_script(tmp_path: Path) -> None:
    _write(tmp_path, "0001_first.up.sql", "SELECT 1;")
    with pytest.raises(MigrationError, match="both up and down"):
        discover_migrations(tmp_path)


def test_discover_migrations_rejects_version_gaps(tmp_path: Path) -> None:
    for version, name in (("0001", "first"), ("0003", "third")):
        _write(tmp_path, f"{version}_{name}.up.sql", "SELECT 1;")
        _write(tmp_path, f"{version}_{name}.down.sql", "SELECT 1;")
    with pytest.raises(MigrationError, match="contiguous"):
        discover_migrations(tmp_path)


def test_discover_migrations_rejects_malformed_names(tmp_path: Path) -> None:
    _write(tmp_path, "initial.sql", "SELECT 1;")
    with pytest.raises(MigrationError, match="not a valid migration file name"):
        discover_migrations(tmp_path)


def test_discover_migrations_rejects_conflicting_names(tmp_path: Path) -> None:
    _write(tmp_path, "0001_first.up.sql", "SELECT 1;")
    _write(tmp_path, "0001_first.down.sql", "SELECT 1;")
    _write(tmp_path, "0001_other.up.sql", "SELECT 1;")
    with pytest.raises(MigrationError, match="conflicting names"):
        discover_migrations(tmp_path)
