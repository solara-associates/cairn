"""R2-04: persisting a generated ``TargetModel`` as a ``subject_revision``
row (ADR-009; migration ``0005_revision_approval_execution``).

Spec §11.3's "Plan/design revision: DRAFT -> IMMUTABLE" state machine and
"a revision is immutable once created" rule are the design half of what
R1-21 already built generically on ``subject_revision``: a DB-enforced
monotonic ``revision_number`` per ``(tenant_id, project_id, subject_kind,
subject_id)`` and append-only triggers that reject any update or delete.
Approval itself (the other half of §11.3, binding a revision to an
``approval`` row) is R4 scope -- this module only records the revision.

Mapping releases are Global, so R2-01 did not reuse ``subject_revision``
for them (see migration 0007's docstring). Plan/design revisions are
tenant/project-scoped, so this *is* the right table: the exact row shape
R1-21 built, used here with ``subject_kind="design"`` and
``subject_id`` = the design's own id.

``subject_revision`` enforces both tenant and project row-level security
(migration 0005), so every real query needs both contexts bound, not only
the tenant one R2-01's ``mapping_proposal`` needed. This module does not
re-implement the monotonicity or append-only enforcement already proven
in ``tests/integration/test_revision_approval_execution_schema.py`` -- it
only has to bind context and write/read correctly into the table those
triggers already protect.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from typing import Any, Protocol

import psycopg
from cairn_kernel.errors import ValidationError
from cairn_kernel.hex import TenantId
from cairn_kernel.hex.ports import Clock, IdGenerator, SystemClock, UuidIdGenerator
from cairn_kernel.hex.primitives import Port
from cairn_kernel.tenancy import assert_tenant_allowed, current_tenant_context
from psycopg.rows import dict_row

from cairn_modules.approvals.model import RevisionRecord
from cairn_modules.design.target_model import TargetModel

DESIGN_SUBJECT_KIND = "design"


def _input_versions(target_model: TargetModel) -> tuple[tuple[str, str], ...]:
    """Project a ``TargetModel``'s recorded versions/parameters into
    ``RevisionRecord.input_versions``'s ``tuple[tuple[str, str], ...]``
    shape -- the exact "records versions" data spec §16's R2-04 row and
    R2-10's later consistency check need, with the full parameter set
    carried as one canonical JSON string so no parameter value type is
    lost."""
    parameters_json = json.dumps(
        [[key, value] for key, value in target_model.parameters],
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        ("pattern_id", target_model.pattern_id),
        ("pattern_catalogue_version", target_model.pattern_catalogue_version),
        ("mapping_release_version", target_model.mapping_release_version),
        ("target_provider", target_model.target_provider),
        ("parameters", parameters_json),
    )


class DesignRevisionRepository(Port, Protocol):
    def create_revision(
        self,
        *,
        design_id: str,
        target_model: TargetModel,
        created_by: str,
    ) -> RevisionRecord:
        """Append a new revision for ``design_id`` (``subject_kind=
        "design"``, ``subject_id=design_id``, scoped to
        ``target_model.tenant_id``/``target_model.project_id``) with the
        next ``revision_number`` in sequence. Never mutates a prior
        revision -- a regeneration with changed parameters/pattern/
        mapping produces a new row, never an update of the last one."""

    def list_revisions(
        self, *, tenant_id: str, project_id: str, design_id: str
    ) -> tuple[RevisionRecord, ...]:
        """Every revision recorded for ``design_id`` within
        ``tenant_id``/``project_id``, in ``revision_number`` order."""

    def latest_revision(
        self, *, tenant_id: str, project_id: str, design_id: str
    ) -> RevisionRecord | None:
        """The most recent revision for ``design_id``, or ``None`` if none
        has been generated yet."""


class FakeDesignRevisionRepository:
    """Thread-safe, process-local ``DesignRevisionRepository``, mirroring
    migration 0005's monotonic-per-subject and append-only invariants in
    memory so unit tests can prove the same behaviour without a
    database. Tenant isolation is enforced the same way
    ``FakeMappingRepository`` enforces it (ADR-012's ambient
    ``TenantContext``), via ``assert_tenant_allowed``."""

    def __init__(self, *, clock: Clock | None = None, id_generator: IdGenerator | None = None) -> None:
        self._clock = clock or SystemClock()
        self._ids = id_generator or UuidIdGenerator()
        self._lock = threading.Lock()
        self._revisions: dict[tuple[str, str, str], list[RevisionRecord]] = {}

    def create_revision(
        self,
        *,
        design_id: str,
        target_model: TargetModel,
        created_by: str,
    ) -> RevisionRecord:
        assert_tenant_allowed(current_tenant_context(), TenantId(target_model.tenant_id))
        key = (target_model.tenant_id, target_model.project_id, design_id)
        with self._lock:
            existing = self._revisions.setdefault(key, [])
            next_number = len(existing) + 1
            record = RevisionRecord(
                revision_id=self._ids.new_id(),
                tenant_id=target_model.tenant_id,
                project_id=target_model.project_id,
                subject_kind=DESIGN_SUBJECT_KIND,
                subject_id=design_id,
                revision_number=next_number,
                content_hash=target_model.content_hash,
                input_versions=_input_versions(target_model),
                created_by=created_by,
                created_at=self._clock.now(),
            )
            existing.append(record)
            return record

    def list_revisions(
        self, *, tenant_id: str, project_id: str, design_id: str
    ) -> tuple[RevisionRecord, ...]:
        assert_tenant_allowed(current_tenant_context(), TenantId(tenant_id))
        return tuple(self._revisions.get((tenant_id, project_id, design_id), ()))

    def latest_revision(
        self, *, tenant_id: str, project_id: str, design_id: str
    ) -> RevisionRecord | None:
        revisions = self.list_revisions(
            tenant_id=tenant_id, project_id=project_id, design_id=design_id
        )
        return revisions[-1] if revisions else None


def _row_to_record(row: dict[str, Any]) -> RevisionRecord:
    input_versions_payload = row["input_versions"] or {}
    return RevisionRecord(
        revision_id=str(row["revision_id"]),
        tenant_id=str(row["tenant_id"]),
        project_id=str(row["project_id"]),
        subject_kind=row["subject_kind"],
        subject_id=str(row["subject_id"]),
        revision_number=row["revision_number"],
        content_hash=row["content_hash"],
        input_versions=tuple(sorted(input_versions_payload.items())),
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


class PostgresDesignRevisionRepository:
    """The real ``DesignRevisionRepository`` adapter, against migration
    0005's ``subject_revision`` table, used with ``subject_kind=
    "design"``. Relies entirely on that table's own monotonic and
    append-only triggers -- this adapter does not duplicate either check,
    it only binds the tenant/project RLS context and inserts/reads.

    ``assertion`` is the same signed tenant assertion
    ``cairn_set_tenant_context`` takes elsewhere in this codebase
    (``PostgresMappingRepository.propose``, ``PostgresAuditSink``); unlike
    the mapping registry's Global tables, ``subject_revision`` also
    enforces project-level RLS, so every call binds
    ``cairn_set_project_context`` too and verifies both match the caller's
    claimed ``tenant_id``/``project_id`` before touching any row.
    """

    def __init__(self, dsn: str, *, assertion: str | None = None) -> None:
        self._dsn = dsn
        self._assertion = assertion

    def _bind_context(
        self, connection: psycopg.Connection, *, tenant_id: str, project_id: str
    ) -> None:
        if self._assertion is None:
            raise ValidationError("a tenant assertion is required for design revisions")
        connection.execute("SELECT cairn_set_tenant_context(%s)", (self._assertion,))
        connection.execute("SELECT cairn_set_project_context(%s)", (project_id,))
        bound_tenant = connection.execute(
            "SELECT cairn_current_tenant() AS tenant_id"
        ).fetchone()
        if bound_tenant is None or str(bound_tenant["tenant_id"]) != tenant_id:
            raise ValidationError("tenant assertion does not match the given tenant_id")
        bound_project = connection.execute(
            "SELECT cairn_current_project() AS project_id"
        ).fetchone()
        if bound_project is None or str(bound_project["project_id"]) != project_id:
            raise ValidationError("tenant assertion does not match the given project_id")

    def create_revision(
        self,
        *,
        design_id: str,
        target_model: TargetModel,
        created_by: str,
    ) -> RevisionRecord:
        input_versions = dict(_input_versions(target_model))
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection, connection.transaction():
                self._bind_context(
                    connection,
                    tenant_id=target_model.tenant_id,
                    project_id=target_model.project_id,
                )
                existing_count = connection.execute(
                    "SELECT count(*) AS n FROM subject_revision"
                    " WHERE tenant_id = %s AND project_id = %s"
                    " AND subject_kind = %s AND subject_id = %s",
                    (
                        target_model.tenant_id,
                        target_model.project_id,
                        DESIGN_SUBJECT_KIND,
                        design_id,
                    ),
                ).fetchone()
                next_number = int(existing_count["n"]) + 1
                row = connection.execute(
                    "INSERT INTO subject_revision"
                    " (tenant_id, project_id, subject_kind, subject_id, revision_number,"
                    "  content_hash, input_versions, created_by, created_at)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)"
                    " RETURNING revision_id, tenant_id, project_id, subject_kind, subject_id,"
                    "  revision_number, content_hash, input_versions, created_by, created_at",
                    (
                        target_model.tenant_id,
                        target_model.project_id,
                        DESIGN_SUBJECT_KIND,
                        design_id,
                        next_number,
                        target_model.content_hash,
                        json.dumps(input_versions),
                        created_by,
                        datetime.now(UTC),
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            raise ValidationError(f"could not record design revision: {exc}") from exc
        if row is None:
            raise ValidationError("design revision insert returned no row")
        return _row_to_record(row)

    def list_revisions(
        self, *, tenant_id: str, project_id: str, design_id: str
    ) -> tuple[RevisionRecord, ...]:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                self._bind_context(connection, tenant_id=tenant_id, project_id=project_id)
                rows = connection.execute(
                    "SELECT revision_id, tenant_id, project_id, subject_kind, subject_id,"
                    " revision_number, content_hash, input_versions, created_by, created_at"
                    " FROM subject_revision"
                    " WHERE tenant_id = %s AND project_id = %s"
                    " AND subject_kind = %s AND subject_id = %s"
                    " ORDER BY revision_number",
                    (tenant_id, project_id, DESIGN_SUBJECT_KIND, design_id),
                ).fetchall()
        except psycopg.Error as exc:
            raise ValidationError(f"could not list design revisions: {exc}") from exc
        return tuple(_row_to_record(row) for row in rows)

    def latest_revision(
        self, *, tenant_id: str, project_id: str, design_id: str
    ) -> RevisionRecord | None:
        revisions = self.list_revisions(
            tenant_id=tenant_id, project_id=project_id, design_id=design_id
        )
        return revisions[-1] if revisions else None


__all__ = [
    "DESIGN_SUBJECT_KIND",
    "DesignRevisionRepository",
    "FakeDesignRevisionRepository",
    "PostgresDesignRevisionRepository",
]
