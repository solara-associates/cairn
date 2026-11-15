"""R2-01: ``MappingRepository`` adapters.

This replaces R0-14's ``InMemoryMappingRegistry`` -- a simple, no-workflow,
load-and-publish-directly store -- with ADR-004's full propose/review/
approve/publish/retire workflow (spec 5.4's ``MappingRepository`` port).
It does not wrap the old class; nothing here calls it.

``FakeMappingRepository`` is the in-memory adapter tests and ``create_app``
default to, the same role ``InMemoryProjectRepository`` plays for
``ProjectRepository`` -- apps/api wires no production datastore for any
surface yet. ``PostgresMappingRepository`` is the real adapter, against
migration 0007's ``mapping_release``/``mapping_release_review`` tables.
Both enforce the identical ADR-004 transition sequence
(``cairn_modules.mappings.domain.require_legal_transition``), so an
illegal transition fails the same way against either one, and the same
way the migration's own trigger would reject it.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from typing import Any

import psycopg
from cairn_contracts.mapping import MappingEntry, MappingRelease, ReleaseStatus
from cairn_kernel.errors import MappingUnavailableError, ValidationError
from cairn_kernel.hex import TenantId
from cairn_kernel.hex.ports import Clock, IdGenerator, SystemClock, UuidIdGenerator
from cairn_kernel.tenancy import assert_tenant_allowed, current_tenant_context
from psycopg import ClientCursor
from psycopg.rows import dict_row

from cairn_modules.mappings.domain import (
    MappingProposalRecord,
    MappingReleaseRecord,
    MappingReleaseReview,
    require_legal_transition,
)


class FakeMappingRepository:
    """Thread-safe, process-local ``MappingRepository``."""

    def __init__(self, *, clock: Clock | None = None, id_generator: IdGenerator | None = None) -> None:
        self._clock = clock or SystemClock()
        self._ids = id_generator or UuidIdGenerator()
        self._lock = threading.Lock()
        self._records: dict[str, MappingReleaseRecord] = {}
        self._proposals: dict[str, list[MappingProposalRecord]] = {}

    def propose(
        self, release: MappingRelease, *, tenant_id: str, proposer_actor_id: str, rationale: str
    ) -> MappingReleaseRecord:
        assert_tenant_allowed(current_tenant_context(), TenantId(tenant_id))
        with self._lock:
            if release.version in self._records:
                raise ValidationError(f"mapping release {release.version} already exists")
            if release.status is not ReleaseStatus.DRAFT:
                raise ValidationError("a proposal must carry a release in DRAFT status")
            now = self._clock.now()
            reviews = (
                MappingReleaseReview(None, ReleaseStatus.DRAFT, proposer_actor_id, rationale, now),
                MappingReleaseReview(
                    ReleaseStatus.DRAFT, ReleaseStatus.IN_REVIEW, proposer_actor_id, rationale, now
                ),
            )
            record = MappingReleaseRecord(
                release=release, status=ReleaseStatus.IN_REVIEW, reviews=reviews
            )
            self._records[release.version] = record
            proposal = MappingProposalRecord(
                proposal_id=self._ids.new_id(),
                tenant_id=tenant_id,
                version=release.version,
                proposer_actor_id=proposer_actor_id,
                rationale=rationale,
                proposed_at=now,
            )
            self._proposals.setdefault(tenant_id, []).append(proposal)
            return record

    def list_proposals(self, tenant_id: str) -> tuple[MappingProposalRecord, ...]:
        assert_tenant_allowed(current_tenant_context(), TenantId(tenant_id))
        return tuple(self._proposals.get(tenant_id, ()))

    def review(
        self, version: str, *, approved: bool, reviewer_actor_id: str, rationale: str
    ) -> MappingReleaseRecord:
        with self._lock:
            record = self._require(version)
            target = ReleaseStatus.APPROVED if approved else ReleaseStatus.DRAFT
            require_legal_transition(record.status, target, version=version)
            review = MappingReleaseReview(
                record.status, target, reviewer_actor_id, rationale, self._clock.now()
            )
            updated = MappingReleaseRecord(
                release=record.release, status=target, reviews=record.reviews + (review,)
            )
            self._records[version] = updated
            return updated

    def publish(
        self, version: str, *, content_hash: str, actor_id: str, rationale: str = ""
    ) -> MappingReleaseRecord:
        with self._lock:
            record = self._require(version)
            if record.status is ReleaseStatus.PUBLISHED:
                if content_hash != record.content_hash:
                    raise ValidationError(
                        f"mapping release {version} is immutable; publish a new version"
                    )
                return record  # same-hash republish of an already-PUBLISHED version: a no-op
            if record.status is not ReleaseStatus.APPROVED:
                raise ValidationError(
                    f"mapping release {version} is {record.status.value}, not APPROVED"
                )
            if content_hash != record.content_hash:
                raise ValidationError(
                    f"mapping release {version} content_hash does not match the proposed content"
                )
            review = MappingReleaseReview(
                record.status, ReleaseStatus.PUBLISHED, actor_id, rationale, self._clock.now()
            )
            updated = MappingReleaseRecord(
                release=record.release,
                status=ReleaseStatus.PUBLISHED,
                reviews=record.reviews + (review,),
            )
            self._records[version] = updated
            return updated

    def retire(self, version: str, *, actor_id: str, rationale: str) -> MappingReleaseRecord:
        with self._lock:
            record = self._require(version)
            require_legal_transition(record.status, ReleaseStatus.RETIRED, version=version)
            review = MappingReleaseReview(
                record.status, ReleaseStatus.RETIRED, actor_id, rationale, self._clock.now()
            )
            updated = MappingReleaseRecord(
                release=record.release,
                status=ReleaseStatus.RETIRED,
                reviews=record.reviews + (review,),
            )
            self._records[version] = updated
            return updated

    def get(self, version: str) -> MappingReleaseRecord:
        return self._require(version)

    def get_published(self, version: str) -> MappingRelease:
        record = self._require(version)
        if record.status is not ReleaseStatus.PUBLISHED:
            raise MappingUnavailableError(f"mapping release {version} is not published")
        return record.release

    def list_releases(self) -> tuple[MappingReleaseRecord, ...]:
        return tuple(self._records[version] for version in sorted(self._records))

    def _require(self, version: str) -> MappingReleaseRecord:
        record = self._records.get(version)
        if record is None:
            raise MappingUnavailableError(f"mapping release {version} is not available")
        return record


def _entries_to_json(entries: tuple[MappingEntry, ...]) -> str:
    return json.dumps([entry.model_dump(mode="json") for entry in entries])


def _release_from_row(row: dict[str, Any]) -> MappingRelease:
    return MappingRelease(
        version=row["version"],
        released_at=row["released_at"],
        status=ReleaseStatus.DRAFT,  # the content's fixed, hash-stable baseline status
        entries=tuple(MappingEntry.model_validate(entry) for entry in row["entries"]),
    )


class PostgresMappingRepository:
    """The real ``MappingRepository`` adapter, against migration 0007's
    ``mapping_release``/``mapping_release_review``/``mapping_proposal``
    tables.

    ``mapping_release``/``mapping_release_review`` are classified GLOBAL
    (spec 8.1): no tenant context is needed to read or transition them,
    unlike ``cairn_adapters.persistence_postgres.audit.PostgresAuditSink``.
    ``mapping_proposal`` is Tenant-owned, RLS-forced -- ``propose``/
    ``list_proposals`` are the only two methods that need ``assertion``
    (the same signed tenant assertion ``cairn_set_tenant_context`` takes
    elsewhere in this codebase) bound first.
    """

    def __init__(self, dsn: str, *, assertion: str | None = None) -> None:
        self._dsn = dsn
        self._assertion = assertion

    def propose(
        self, release: MappingRelease, *, tenant_id: str, proposer_actor_id: str, rationale: str
    ) -> MappingReleaseRecord:
        if release.status is not ReleaseStatus.DRAFT:
            raise ValidationError("a proposal must carry a release in DRAFT status")
        if self._assertion is None:
            raise ValidationError("a tenant assertion is required to propose a mapping release")
        try:
            with psycopg.connect(self._dsn, cursor_factory=ClientCursor) as connection, connection.transaction():
                connection.execute("SELECT cairn_set_tenant_context(%s)", (self._assertion,))
                bound = connection.execute("SELECT cairn_current_tenant()").fetchone()
                if bound is None or str(bound[0]) != tenant_id:
                    raise ValidationError("tenant assertion does not match the given tenant_id")
                existing = connection.execute(
                    "SELECT 1 FROM mapping_release WHERE version = %s", (release.version,)
                ).fetchone()
                if existing is not None:
                    raise ValidationError(f"mapping release {release.version} already exists")
                connection.execute(
                    "INSERT INTO mapping_release"
                    " (version, content_hash, released_at, entries, proposed_by)"
                    " VALUES (%s, %s, %s, %s::jsonb, %s)",
                    (
                        release.version,
                        release.content_hash,
                        release.released_at,
                        _entries_to_json(release.entries),
                        proposer_actor_id,
                    ),
                )
                now = datetime.now(UTC)
                connection.execute(
                    "INSERT INTO mapping_release_review"
                    " (version, from_status, to_status, actor_id, rationale, occurred_at)"
                    " VALUES (%s, NULL, 'DRAFT', %s, %s, %s)",
                    (release.version, proposer_actor_id, rationale, now),
                )
                connection.execute(
                    "INSERT INTO mapping_release_review"
                    " (version, from_status, to_status, actor_id, rationale, occurred_at)"
                    " VALUES (%s, 'DRAFT', 'IN_REVIEW', %s, %s, %s)",
                    (release.version, proposer_actor_id, rationale, now),
                )
                connection.execute(
                    "INSERT INTO mapping_proposal"
                    " (tenant_id, version, proposer_actor_id, rationale, proposed_at)"
                    " VALUES (%s, %s, %s, %s, %s)",
                    (tenant_id, release.version, proposer_actor_id, rationale, now),
                )
        except psycopg.Error as exc:
            raise MappingUnavailableError("mapping registry unavailable") from exc
        return self.get(release.version)

    def list_proposals(self, tenant_id: str) -> tuple[MappingProposalRecord, ...]:
        if self._assertion is None:
            raise ValidationError("a tenant assertion is required to list mapping proposals")
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                connection.execute("SELECT cairn_set_tenant_context(%s)", (self._assertion,))
                bound = connection.execute("SELECT cairn_current_tenant()").fetchone()
                if bound is None or str(bound["cairn_current_tenant"]) != tenant_id:
                    raise ValidationError("tenant assertion does not match the given tenant_id")
                rows = connection.execute(
                    "SELECT proposal_id, tenant_id, version, proposer_actor_id, rationale,"
                    " proposed_at FROM mapping_proposal WHERE tenant_id = %s ORDER BY proposed_at",
                    (tenant_id,),
                ).fetchall()
        except psycopg.Error as exc:
            raise MappingUnavailableError("mapping registry unavailable") from exc
        return tuple(
            MappingProposalRecord(
                proposal_id=str(row["proposal_id"]),
                tenant_id=str(row["tenant_id"]),
                version=row["version"],
                proposer_actor_id=row["proposer_actor_id"],
                rationale=row["rationale"],
                proposed_at=row["proposed_at"],
            )
            for row in rows
        )

    def review(
        self, version: str, *, approved: bool, reviewer_actor_id: str, rationale: str
    ) -> MappingReleaseRecord:
        record = self.get(version)
        target = ReleaseStatus.APPROVED if approved else ReleaseStatus.DRAFT
        require_legal_transition(record.status, target, version=version)
        self._insert_transition(
            version,
            from_status=record.status,
            to_status=target,
            actor_id=reviewer_actor_id,
            rationale=rationale,
        )
        return self.get(version)

    def publish(
        self, version: str, *, content_hash: str, actor_id: str, rationale: str = ""
    ) -> MappingReleaseRecord:
        record = self.get(version)
        if record.status is ReleaseStatus.PUBLISHED:
            if content_hash != record.content_hash:
                raise ValidationError(
                    f"mapping release {version} is immutable; publish a new version"
                )
            return record
        if record.status is not ReleaseStatus.APPROVED:
            raise ValidationError(
                f"mapping release {version} is {record.status.value}, not APPROVED"
            )
        if content_hash != record.content_hash:
            raise ValidationError(
                f"mapping release {version} content_hash does not match the proposed content"
            )
        self._insert_transition(
            version,
            from_status=record.status,
            to_status=ReleaseStatus.PUBLISHED,
            actor_id=actor_id,
            rationale=rationale,
        )
        return self.get(version)

    def retire(self, version: str, *, actor_id: str, rationale: str) -> MappingReleaseRecord:
        record = self.get(version)
        require_legal_transition(record.status, ReleaseStatus.RETIRED, version=version)
        self._insert_transition(
            version,
            from_status=record.status,
            to_status=ReleaseStatus.RETIRED,
            actor_id=actor_id,
            rationale=rationale,
        )
        return self.get(version)

    def get(self, version: str) -> MappingReleaseRecord:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                release_row = connection.execute(
                    "SELECT version, released_at, entries FROM mapping_release"
                    " WHERE version = %s",
                    (version,),
                ).fetchone()
                if release_row is None:
                    raise MappingUnavailableError(f"mapping release {version} is not available")
                review_rows = connection.execute(
                    "SELECT from_status, to_status, actor_id, rationale, occurred_at"
                    " FROM mapping_release_review WHERE version = %s"
                    " ORDER BY review_seq",
                    (version,),
                ).fetchall()
        except psycopg.Error as exc:
            raise MappingUnavailableError("mapping registry unavailable") from exc

        release = _release_from_row(release_row)
        reviews = tuple(
            MappingReleaseReview(
                from_status=ReleaseStatus(row["from_status"]) if row["from_status"] else None,
                to_status=ReleaseStatus(row["to_status"]),
                actor_id=row["actor_id"],
                rationale=row["rationale"] or "",
                occurred_at=row["occurred_at"],
            )
            for row in review_rows
        )
        status = reviews[-1].to_status if reviews else ReleaseStatus.DRAFT
        return MappingReleaseRecord(release=release, status=status, reviews=reviews)

    def get_published(self, version: str) -> MappingRelease:
        record = self.get(version)
        if record.status is not ReleaseStatus.PUBLISHED:
            raise MappingUnavailableError(f"mapping release {version} is not published")
        return record.release

    def list_releases(self) -> tuple[MappingReleaseRecord, ...]:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                rows = connection.execute(
                    "SELECT version FROM mapping_release ORDER BY version"
                ).fetchall()
        except psycopg.Error as exc:
            raise MappingUnavailableError("mapping registry unavailable") from exc
        return tuple(self.get(row["version"]) for row in rows)

    def _insert_transition(
        self,
        version: str,
        *,
        from_status: ReleaseStatus,
        to_status: ReleaseStatus,
        actor_id: str,
        rationale: str,
    ) -> None:
        try:
            with psycopg.connect(self._dsn, cursor_factory=ClientCursor) as connection, connection.transaction():
                connection.execute(
                    "INSERT INTO mapping_release_review"
                    " (version, from_status, to_status, actor_id, rationale, occurred_at)"
                    " VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        version,
                        from_status.value,
                        to_status.value,
                        actor_id,
                        rationale,
                        datetime.now(UTC),
                    ),
                )
        except psycopg.Error as exc:
            raise MappingUnavailableError("mapping registry unavailable") from exc


__all__ = ["FakeMappingRepository", "PostgresMappingRepository"]
