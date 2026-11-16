"""R3-03b: persisting one transformation run (ADR-015's manifest
requirement) as a ``transformation_run`` row (migration 0008).

Spec §11.3-style append-only recording, the same discipline R2-04's
``cairn_modules.design.revisions`` applies to ``subject_revision``. That
module's own docstring explains why a transformation run does *not*
reuse ``subject_revision``: a design/plan revision is one subject
producing one ``content_hash``; a transformation run takes an ordered
set of source files and produces one manifest with many entries across
all of them, which does not fit ``subject_revision``'s one-hash-per-row
shape cleanly (see migration ``0008_transformation_run.up.sql``'s own
comment for the full reasoning). ``packages/adapters/tests/
test_source_git.py`` flagged this exact gap for 726 to close.

This module never calls the Rust engine or the subprocess adapter
itself -- it only persists a ``TransformationManifest`` a
``TransformationPort`` adapter already produced.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import psycopg
from cairn_kernel.errors import ValidationError
from cairn_kernel.hex import TenantId
from cairn_kernel.hex.ports import Clock, IdGenerator, SystemClock, UuidIdGenerator
from cairn_kernel.hex.primitives import Port
from cairn_kernel.tenancy import assert_tenant_allowed, current_tenant_context
from psycopg.rows import dict_row

from cairn_modules.transformation.engine import (
    ManifestEdit,
    ManifestEntry,
    ManifestOutcome,
    TransformationManifest,
)


@dataclass(frozen=True, slots=True)
class TransformationRunRecord:
    """One ``transformation_run`` row: append-only, never mutated."""

    run_id: str
    tenant_id: str
    project_id: str
    run_number: int
    manifest: TransformationManifest
    created_by: str
    created_at: datetime


def _manifest_to_json(manifest: TransformationManifest) -> dict[str, Any]:
    return {
        "source_file_ids": list(manifest.source_file_ids),
        "entries": [
            {
                "source_file_id": entry.source_file_id,
                "rule_id": entry.rule_id,
                "outcome": entry.outcome.value,
                "reason": entry.reason,
                "edits": [
                    {
                        "start_byte": edit.start_byte,
                        "end_byte": edit.end_byte,
                        "start_line": edit.start_line,
                        "end_line": edit.end_line,
                        "replacement": edit.replacement,
                    }
                    for edit in entry.edits
                ],
                "detector_version": entry.detector_version,
                "pattern_version": entry.pattern_version,
                "patcher_version": entry.patcher_version,
                "mapping_release_version": entry.mapping_release_version,
            }
            for entry in manifest.entries
        ],
    }


def _manifest_from_json(payload: dict[str, Any]) -> TransformationManifest:
    return TransformationManifest(
        source_file_ids=tuple(payload["source_file_ids"]),
        entries=tuple(
            ManifestEntry(
                source_file_id=raw["source_file_id"],
                rule_id=raw["rule_id"],
                outcome=ManifestOutcome(raw["outcome"]),
                reason=raw["reason"],
                edits=tuple(
                    ManifestEdit(
                        start_byte=edit["start_byte"],
                        end_byte=edit["end_byte"],
                        start_line=edit["start_line"],
                        end_line=edit["end_line"],
                        replacement=edit["replacement"],
                    )
                    for edit in raw["edits"]
                ),
                detector_version=raw["detector_version"],
                pattern_version=raw["pattern_version"],
                patcher_version=raw["patcher_version"],
                mapping_release_version=raw["mapping_release_version"],
            )
            for raw in payload["entries"]
        ),
    )


class TransformationRunRepository(Port, Protocol):
    def record_run(
        self,
        *,
        tenant_id: str,
        project_id: str,
        manifest: TransformationManifest,
        created_by: str,
    ) -> TransformationRunRecord:
        """Append a new run for ``(tenant_id, project_id)`` with the next
        ``run_number`` in sequence. Never mutates a prior run."""

    def list_runs(self, *, tenant_id: str, project_id: str) -> tuple[TransformationRunRecord, ...]:
        """Every run recorded for this project, in ``run_number`` order."""

    def latest_run(
        self, *, tenant_id: str, project_id: str
    ) -> TransformationRunRecord | None:
        """The most recent run for this project, or ``None`` if none has
        been recorded yet."""


class FakeTransformationRunRepository:
    """Thread-safe, process-local ``TransformationRunRepository``,
    mirroring migration 0008's monotonic-per-project and append-only
    invariants in memory, the same way ``FakeDesignRevisionRepository``
    mirrors migration 0005's."""

    def __init__(self, *, clock: Clock | None = None, id_generator: IdGenerator | None = None) -> None:
        self._clock = clock or SystemClock()
        self._ids = id_generator or UuidIdGenerator()
        self._lock = threading.Lock()
        self._runs: dict[tuple[str, str], list[TransformationRunRecord]] = {}

    def record_run(
        self,
        *,
        tenant_id: str,
        project_id: str,
        manifest: TransformationManifest,
        created_by: str,
    ) -> TransformationRunRecord:
        assert_tenant_allowed(current_tenant_context(), TenantId(tenant_id))
        key = (tenant_id, project_id)
        with self._lock:
            existing = self._runs.setdefault(key, [])
            next_number = len(existing) + 1
            record = TransformationRunRecord(
                run_id=self._ids.new_id(),
                tenant_id=tenant_id,
                project_id=project_id,
                run_number=next_number,
                manifest=manifest,
                created_by=created_by,
                created_at=self._clock.now(),
            )
            existing.append(record)
            return record

    def list_runs(self, *, tenant_id: str, project_id: str) -> tuple[TransformationRunRecord, ...]:
        assert_tenant_allowed(current_tenant_context(), TenantId(tenant_id))
        return tuple(self._runs.get((tenant_id, project_id), ()))

    def latest_run(
        self, *, tenant_id: str, project_id: str
    ) -> TransformationRunRecord | None:
        runs = self.list_runs(tenant_id=tenant_id, project_id=project_id)
        return runs[-1] if runs else None


def _row_to_record(row: dict[str, Any]) -> TransformationRunRecord:
    return TransformationRunRecord(
        run_id=str(row["run_id"]),
        tenant_id=str(row["tenant_id"]),
        project_id=str(row["project_id"]),
        run_number=row["run_number"],
        manifest=_manifest_from_json(row["manifest"]),
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


class PostgresTransformationRunRepository:
    """The real ``TransformationRunRepository`` adapter, against
    migration 0008's ``transformation_run`` table. Relies entirely on
    that table's own monotonic and append-only triggers, the same way
    ``PostgresDesignRevisionRepository`` relies on migration 0005's."""

    def __init__(self, dsn: str, *, assertion: str | None = None) -> None:
        self._dsn = dsn
        self._assertion = assertion

    def _bind_context(
        self, connection: psycopg.Connection, *, tenant_id: str, project_id: str
    ) -> None:
        if self._assertion is None:
            raise ValidationError("a tenant assertion is required for transformation runs")
        connection.execute("SELECT cairn_set_tenant_context(%s)", (self._assertion,))
        connection.execute("SELECT cairn_set_project_context(%s)", (project_id,))
        bound_tenant = connection.execute("SELECT cairn_current_tenant() AS tenant_id").fetchone()
        if bound_tenant is None or str(bound_tenant["tenant_id"]) != tenant_id:
            raise ValidationError("tenant assertion does not match the given tenant_id")
        bound_project = connection.execute("SELECT cairn_current_project() AS project_id").fetchone()
        if bound_project is None or str(bound_project["project_id"]) != project_id:
            raise ValidationError("tenant assertion does not match the given project_id")

    def record_run(
        self,
        *,
        tenant_id: str,
        project_id: str,
        manifest: TransformationManifest,
        created_by: str,
    ) -> TransformationRunRecord:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection, connection.transaction():
                self._bind_context(connection, tenant_id=tenant_id, project_id=project_id)
                existing_count = connection.execute(
                    "SELECT count(*) AS n FROM transformation_run"
                    " WHERE tenant_id = %s AND project_id = %s",
                    (tenant_id, project_id),
                ).fetchone()
                next_number = int(existing_count["n"]) + 1
                row = connection.execute(
                    "INSERT INTO transformation_run"
                    " (tenant_id, project_id, run_number, source_file_ids, manifest,"
                    "  applied_count, skipped_count, unsupported_count, created_by, created_at)"
                    " VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s)"
                    " RETURNING run_id, tenant_id, project_id, run_number, manifest,"
                    "  created_by, created_at",
                    (
                        tenant_id,
                        project_id,
                        next_number,
                        json.dumps(list(manifest.source_file_ids)),
                        json.dumps(_manifest_to_json(manifest)),
                        manifest.applied_count,
                        manifest.skipped_count,
                        manifest.unsupported_count,
                        created_by,
                        datetime.now(UTC),
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            raise ValidationError(f"could not record transformation run: {exc}") from exc
        if row is None:
            raise ValidationError("transformation run insert returned no row")
        return _row_to_record(row)

    def list_runs(self, *, tenant_id: str, project_id: str) -> tuple[TransformationRunRecord, ...]:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                self._bind_context(connection, tenant_id=tenant_id, project_id=project_id)
                rows = connection.execute(
                    "SELECT run_id, tenant_id, project_id, run_number, manifest,"
                    " created_by, created_at FROM transformation_run"
                    " WHERE tenant_id = %s AND project_id = %s"
                    " ORDER BY run_number",
                    (tenant_id, project_id),
                ).fetchall()
        except psycopg.Error as exc:
            raise ValidationError(f"could not list transformation runs: {exc}") from exc
        return tuple(_row_to_record(row) for row in rows)

    def latest_run(
        self, *, tenant_id: str, project_id: str
    ) -> TransformationRunRecord | None:
        runs = self.list_runs(tenant_id=tenant_id, project_id=project_id)
        return runs[-1] if runs else None


__all__ = [
    "FakeTransformationRunRepository",
    "PostgresTransformationRunRepository",
    "TransformationRunRecord",
    "TransformationRunRepository",
]
