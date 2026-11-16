"""R2-06: migration roadmap and wave sequencing (spec §16's R2-06 row:
"Dependencies respected; constraints and risks shown").

Given a project's workloads (R1-07's ``Workload``/``Dependency`` grouping
and dependency capture), their 6R disposition decisions (R1-14's
``DispositionDecision`` accept/amend/reject flow) and the project's target
model (R2-04's ``TargetModel``), ``generate_roadmap`` produces an ordered
sequence of migration waves. Wave membership respects every declared
workload dependency: a workload is never placed in an earlier wave than
something it depends on (``Dependency.source_workload_id`` depends on
``Dependency.target_workload_id`` -- the same semantics R1-07's
``dependencies_of``/``dependents_of`` already establish). A cyclic
dependency cannot be sequenced at all and fails closed with
``DependencyCycleError`` rather than looping forever or silently dropping
the cycle (ADR's fail-closed-controls rule).

This story does not redo 6R classification (R1-14 already does that) and
does not re-resolve mappings (R2-04 already does that). It only consumes
their outputs. A workload whose disposition decision is not yet
``ACCEPTED``/``AMENDED``, or whose resources include one R2-04 could not
resolve (``UNRESOLVED``), is never silently scheduled as if everything
were fine: it is still placed in its dependency-respecting wave, but
carries one or more explicit ``RoadmapConstraint`` entries a reader sees
directly on that workload -- never inferred, never hidden.

Each roadmap generation is persisted as a ``subject_revision`` row with
``subject_kind="plan"`` -- the same generic table and the same
``DRAFT -> IMMUTABLE`` discipline (spec §11.3, ADR-009) R2-04 already uses
with ``subject_kind="design"`` (confirmed as the sibling value in the
703 handover), and spec §5.4's ``RevisionRepository | approvals/planning/
design`` row names ``planning`` as one of the table's three legitimate
owners.
"""

from __future__ import annotations

import json
import threading
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol

import psycopg
from cairn_contracts.estate import (
    DecisionStatus,
    Dependency,
    DependencyDirection,
    Disposition,
    DispositionDecision,
    Workload,
)
from cairn_kernel.errors import DependencyCycleError, ValidationError
from cairn_kernel.hex import TenantId
from cairn_kernel.hex.ports import Clock, IdGenerator, SystemClock, UuidIdGenerator
from cairn_kernel.hex.primitives import Port
from cairn_kernel.tenancy import assert_tenant_allowed, current_tenant_context
from psycopg.rows import dict_row

from cairn_modules.approvals.model import RevisionRecord
from cairn_modules.design.target_model import TargetModel, TargetResourceStatus

PLAN_SUBJECT_KIND = "plan"

#: 6R decision statuses a wave treats as a resolved disposition -- the
#: human reviewer has actually decided, not merely proposed (R1-14).
_ACCEPTED_DECISION_STATUSES = frozenset({DecisionStatus.ACCEPTED, DecisionStatus.AMENDED})


class RoadmapConstraintKind(str, Enum):
    """Why a workload is flagged within its wave, rather than scheduled
    without comment."""

    UNRESOLVED_MAPPING = "UNRESOLVED_MAPPING"
    PENDING_DISPOSITION = "PENDING_DISPOSITION"


@dataclass(frozen=True, slots=True)
class RoadmapConstraint:
    """One explicit, human-readable reason a workload is not simply
    ready to migrate -- surfaced on the workload itself, never left for
    a reader to infer from absence."""

    kind: RoadmapConstraintKind
    detail: str


@dataclass(frozen=True, slots=True)
class WaveWorkload:
    """One workload's placement within a wave, plus every constraint
    still open against it."""

    workload_id: str
    disposition: Disposition | None
    constraints: tuple[RoadmapConstraint, ...]

    @property
    def is_blocked(self) -> bool:
        return len(self.constraints) > 0


@dataclass(frozen=True, slots=True)
class MigrationWave:
    """One wave of the roadmap: workloads whose dependencies are all
    satisfied by an earlier wave, in ``workload_id`` order so repeated
    generation from the same inputs is byte-identical regardless of
    collection-iteration order."""

    wave_number: int
    workloads: tuple[WaveWorkload, ...]


@dataclass(frozen=True, slots=True)
class MigrationRoadmap:
    """The deterministic output of one roadmap generation: an ordered
    sequence of waves covering every given workload exactly once."""

    tenant_id: str
    project_id: str
    plan_id: str
    waves: tuple[MigrationWave, ...]

    @property
    def blocked_workload_ids(self) -> tuple[str, ...]:
        """Every workload carrying at least one open constraint,
        wave order then workload-id order."""
        return tuple(
            wave_workload.workload_id
            for wave in self.waves
            for wave_workload in wave.workloads
            if wave_workload.is_blocked
        )

    @property
    def content_hash(self) -> str:
        """A stable fingerprint of this roadmap's content, over a plain
        canonical-JSON projection -- the same construction
        ``TargetModel.content_hash`` uses (R2-04)."""
        import hashlib

        payload = {
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "plan_id": self.plan_id,
            "waves": [
                {
                    "wave_number": wave.wave_number,
                    "workloads": [
                        {
                            "workload_id": wl.workload_id,
                            "disposition": wl.disposition.value if wl.disposition else None,
                            "constraints": [
                                {"kind": c.kind.value, "detail": c.detail} for c in wl.constraints
                            ],
                        }
                        for wl in wave.workloads
                    ],
                }
                for wave in self.waves
            ],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _dependency_edges(
    workload_ids: Sequence[str], dependencies: Sequence[Dependency]
) -> dict[str, set[str]]:
    """``workload_id -> the set of workload_ids it depends on`` -- the
    edges a wave ordering must respect. ``source_workload_id`` depends on
    ``target_workload_id`` (R1-07's own ``dependencies_of``/
    ``dependents_of`` semantics); a ``BIDIRECTIONAL`` edge makes each side
    depend on the other, which is exactly the two-workload cycle this
    story's cyclic-dependency test exercises."""
    known = set(workload_ids)
    edges: dict[str, set[str]] = {workload_id: set() for workload_id in known}
    for dependency in dependencies:
        if dependency.source_workload_id not in known or dependency.target_workload_id not in known:
            continue
        edges[dependency.source_workload_id].add(dependency.target_workload_id)
        if dependency.direction is DependencyDirection.BIDIRECTIONAL:
            edges[dependency.target_workload_id].add(dependency.source_workload_id)
    return edges


def _compute_wave_numbers(
    workload_ids: Sequence[str], edges: Mapping[str, set[str]]
) -> dict[str, int]:
    """Layer every workload into the earliest wave whose number exceeds
    every one of its dependencies' wave numbers (longest-path
    topological layering, Kahn's algorithm by levels).

    Fails closed with ``DependencyCycleError`` the moment no unscheduled
    workload has all of its dependencies already scheduled -- a cycle,
    not a bug in the input order -- rather than looping forever or
    dropping the stuck workloads from the roadmap silently.
    """
    remaining = set(workload_ids)
    scheduled: set[str] = set()
    wave_of: dict[str, int] = {}
    wave_number = 1

    while remaining:
        ready = sorted(
            workload_id
            for workload_id in remaining
            if edges.get(workload_id, set()) <= scheduled
        )
        if not ready:
            stuck = ", ".join(sorted(remaining))
            raise DependencyCycleError(
                f"cyclic workload dependency detected; cannot sequence: {stuck}"
            )
        for workload_id in ready:
            wave_of[workload_id] = wave_number
        scheduled.update(ready)
        remaining.difference_update(ready)
        wave_number += 1

    return wave_of


def _workload_constraints(
    workload: Workload,
    *,
    decision: DispositionDecision | None,
    unresolved_resources: Mapping[str, str],
) -> tuple[Disposition | None, tuple[RoadmapConstraint, ...]]:
    constraints: list[RoadmapConstraint] = []

    for resource_id in workload.resource_ids:
        reason = unresolved_resources.get(resource_id)
        if reason is not None:
            constraints.append(
                RoadmapConstraint(
                    kind=RoadmapConstraintKind.UNRESOLVED_MAPPING,
                    detail=f"resource {resource_id} has no usable target mapping: {reason}",
                )
            )

    disposition: Disposition | None = None
    if decision is None:
        constraints.append(
            RoadmapConstraint(
                kind=RoadmapConstraintKind.PENDING_DISPOSITION,
                detail=f"workload {workload.workload_id} has no recorded 6R disposition decision",
            )
        )
    elif decision.status in _ACCEPTED_DECISION_STATUSES:
        disposition = decision.disposition
    else:
        constraints.append(
            RoadmapConstraint(
                kind=RoadmapConstraintKind.PENDING_DISPOSITION,
                detail=(
                    f"workload {workload.workload_id} disposition decision is "
                    f"{decision.status.value}, not yet accepted"
                ),
            )
        )

    return disposition, tuple(constraints)


def generate_roadmap(
    *,
    tenant_id: str,
    project_id: str,
    plan_id: str,
    workloads: Sequence[Workload],
    dependencies: Sequence[Dependency] = (),
    dispositions: Mapping[str, DispositionDecision] | None = None,
    target_model: TargetModel | None = None,
    revision: RevisionRecord | None = None,
) -> MigrationRoadmap:
    """Generate one deterministic ``MigrationRoadmap``.

    ``dispositions`` maps ``workload_id -> DispositionDecision`` for
    whatever decision currently exists for that workload (any status --
    this function itself decides what counts as "accepted" per workload,
    rather than requiring the caller to pre-filter, so an un-reviewed
    workload is surfaced as a constraint instead of silently vanishing
    from the roadmap). ``target_model`` is R2-04's output for this
    project; a resource ``generate_target_model`` could not resolve
    blocks the workload(s) that carry it, surfaced by resource id and the
    resolver's own reason.

    ``revision`` is the design revision (703's ``subject_revision`` row)
    ``target_model`` was recorded under -- the same revision-binding
    guard 704's ``build_diagram_model`` and 706's ``build_iac_plan_model``
    already enforce. When both ``revision`` and ``target_model`` are
    given, this fails fast with ``ValidationError`` if they don't belong
    to the same tenant/project or don't share a ``content_hash``, rather
    than silently sequencing a roadmap against a target model that isn't
    the one its own design revision actually records -- the exact
    artefact-level drift ``R-VER-01`` (708) can otherwise only catch
    after the fact. Passing only one of the two, or neither, behaves
    exactly as before this guard existed.

    Raises ``DependencyCycleError`` if the declared dependencies cannot be
    sequenced at all.
    """
    if revision is not None and target_model is not None:
        if revision.tenant_id != target_model.tenant_id or revision.project_id != target_model.project_id:
            raise ValidationError("revision does not belong to this target model's tenant/project")
        if revision.content_hash != target_model.content_hash:
            raise ValidationError(
                "revision.content_hash does not match target_model.content_hash -- "
                "the revision does not record this exact target model"
            )

    dispositions = dispositions or {}
    workload_ids = sorted(workload.workload_id for workload in workloads)
    edges = _dependency_edges(workload_ids, dependencies)
    wave_of = _compute_wave_numbers(workload_ids, edges)

    unresolved_resources: dict[str, str] = {}
    if target_model is not None:
        unresolved_resources = {
            entry.resource_id: (entry.reason or "")
            for entry in target_model.resources
            if entry.status is TargetResourceStatus.UNRESOLVED
        }

    workloads_by_id = {workload.workload_id: workload for workload in workloads}
    grouped: dict[int, list[WaveWorkload]] = defaultdict(list)
    for workload_id in workload_ids:
        workload = workloads_by_id[workload_id]
        disposition, constraints = _workload_constraints(
            workload,
            decision=dispositions.get(workload_id),
            unresolved_resources=unresolved_resources,
        )
        grouped[wave_of[workload_id]].append(
            WaveWorkload(
                workload_id=workload_id,
                disposition=disposition,
                constraints=constraints,
            )
        )

    waves = tuple(
        MigrationWave(
            wave_number=wave_number,
            workloads=tuple(sorted(grouped[wave_number], key=lambda wl: wl.workload_id)),
        )
        for wave_number in sorted(grouped)
    )

    return MigrationRoadmap(
        tenant_id=tenant_id,
        project_id=project_id,
        plan_id=plan_id,
        waves=waves,
    )


# --- persistence: subject_revision, subject_kind="plan" --------------------


def _input_versions(roadmap: MigrationRoadmap) -> tuple[tuple[str, str], ...]:
    """Project a ``MigrationRoadmap``'s shape into
    ``RevisionRecord.input_versions``'s ``tuple[tuple[str, str], ...]``
    shape -- the roadmap-equivalent of R2-04's recorded pattern/mapping
    versions: how many workloads, how many waves, how many are blocked."""
    workload_count = sum(len(wave.workloads) for wave in roadmap.waves)
    return (
        ("wave_count", str(len(roadmap.waves))),
        ("workload_count", str(workload_count)),
        ("blocked_workload_count", str(len(roadmap.blocked_workload_ids))),
    )


class PlanRevisionRepository(Port, Protocol):
    def create_revision(
        self,
        *,
        plan_id: str,
        roadmap: MigrationRoadmap,
        created_by: str,
    ) -> RevisionRecord:
        """Append a new revision for ``plan_id`` (``subject_kind="plan"``,
        ``subject_id=plan_id``, scoped to ``roadmap.tenant_id``/
        ``roadmap.project_id``) with the next ``revision_number`` in
        sequence. Never mutates a prior revision."""

    def list_revisions(
        self, *, tenant_id: str, project_id: str, plan_id: str
    ) -> tuple[RevisionRecord, ...]:
        """Every revision recorded for ``plan_id``, in ``revision_number``
        order."""

    def latest_revision(
        self, *, tenant_id: str, project_id: str, plan_id: str
    ) -> RevisionRecord | None:
        """The most recent revision for ``plan_id``, or ``None`` if none
        has been generated yet."""


class FakePlanRevisionRepository:
    """Thread-safe, process-local ``PlanRevisionRepository``, mirroring
    migration 0005's monotonic-per-subject and append-only invariants in
    memory -- the same pattern ``FakeDesignRevisionRepository`` uses for
    ``subject_kind="design"``, here for ``subject_kind="plan"``."""

    def __init__(self, *, clock: Clock | None = None, id_generator: IdGenerator | None = None) -> None:
        self._clock = clock or SystemClock()
        self._ids = id_generator or UuidIdGenerator()
        self._lock = threading.Lock()
        self._revisions: dict[tuple[str, str, str], list[RevisionRecord]] = {}

    def create_revision(
        self,
        *,
        plan_id: str,
        roadmap: MigrationRoadmap,
        created_by: str,
    ) -> RevisionRecord:
        assert_tenant_allowed(current_tenant_context(), TenantId(roadmap.tenant_id))
        key = (roadmap.tenant_id, roadmap.project_id, plan_id)
        with self._lock:
            existing = self._revisions.setdefault(key, [])
            next_number = len(existing) + 1
            record = RevisionRecord(
                revision_id=self._ids.new_id(),
                tenant_id=roadmap.tenant_id,
                project_id=roadmap.project_id,
                subject_kind=PLAN_SUBJECT_KIND,
                subject_id=plan_id,
                revision_number=next_number,
                content_hash=roadmap.content_hash,
                input_versions=_input_versions(roadmap),
                created_by=created_by,
                created_at=self._clock.now(),
            )
            existing.append(record)
            return record

    def list_revisions(
        self, *, tenant_id: str, project_id: str, plan_id: str
    ) -> tuple[RevisionRecord, ...]:
        assert_tenant_allowed(current_tenant_context(), TenantId(tenant_id))
        return tuple(self._revisions.get((tenant_id, project_id, plan_id), ()))

    def latest_revision(
        self, *, tenant_id: str, project_id: str, plan_id: str
    ) -> RevisionRecord | None:
        revisions = self.list_revisions(tenant_id=tenant_id, project_id=project_id, plan_id=plan_id)
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


class PostgresPlanRevisionRepository:
    """The real ``PlanRevisionRepository`` adapter, against migration
    0005's ``subject_revision`` table, used with ``subject_kind="plan"``.
    Mirrors ``PostgresDesignRevisionRepository`` exactly -- same dual
    tenant/project RLS bind, same reliance on the table's own monotonic
    and append-only triggers rather than reimplementing them here.
    """

    def __init__(self, dsn: str, *, assertion: str | None = None) -> None:
        self._dsn = dsn
        self._assertion = assertion

    def _bind_context(
        self, connection: psycopg.Connection, *, tenant_id: str, project_id: str
    ) -> None:
        if self._assertion is None:
            raise ValidationError("a tenant assertion is required for plan revisions")
        connection.execute("SELECT cairn_set_tenant_context(%s)", (self._assertion,))
        connection.execute("SELECT cairn_set_project_context(%s)", (project_id,))
        bound_tenant = connection.execute("SELECT cairn_current_tenant() AS tenant_id").fetchone()
        if bound_tenant is None or str(bound_tenant["tenant_id"]) != tenant_id:
            raise ValidationError("tenant assertion does not match the given tenant_id")
        bound_project = connection.execute("SELECT cairn_current_project() AS project_id").fetchone()
        if bound_project is None or str(bound_project["project_id"]) != project_id:
            raise ValidationError("tenant assertion does not match the given project_id")

    def create_revision(
        self,
        *,
        plan_id: str,
        roadmap: MigrationRoadmap,
        created_by: str,
    ) -> RevisionRecord:
        input_versions = dict(_input_versions(roadmap))
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection, connection.transaction():
                self._bind_context(
                    connection, tenant_id=roadmap.tenant_id, project_id=roadmap.project_id
                )
                existing_count = connection.execute(
                    "SELECT count(*) AS n FROM subject_revision"
                    " WHERE tenant_id = %s AND project_id = %s"
                    " AND subject_kind = %s AND subject_id = %s",
                    (roadmap.tenant_id, roadmap.project_id, PLAN_SUBJECT_KIND, plan_id),
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
                        roadmap.tenant_id,
                        roadmap.project_id,
                        PLAN_SUBJECT_KIND,
                        plan_id,
                        next_number,
                        roadmap.content_hash,
                        json.dumps(input_versions),
                        created_by,
                        datetime.now(UTC),
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            raise ValidationError(f"could not record plan revision: {exc}") from exc
        if row is None:
            raise ValidationError("plan revision insert returned no row")
        return _row_to_record(row)

    def list_revisions(
        self, *, tenant_id: str, project_id: str, plan_id: str
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
                    (tenant_id, project_id, PLAN_SUBJECT_KIND, plan_id),
                ).fetchall()
        except psycopg.Error as exc:
            raise ValidationError(f"could not list plan revisions: {exc}") from exc
        return tuple(_row_to_record(row) for row in rows)

    def latest_revision(
        self, *, tenant_id: str, project_id: str, plan_id: str
    ) -> RevisionRecord | None:
        revisions = self.list_revisions(tenant_id=tenant_id, project_id=project_id, plan_id=plan_id)
        return revisions[-1] if revisions else None


__all__ = [
    "PLAN_SUBJECT_KIND",
    "FakePlanRevisionRepository",
    "MigrationRoadmap",
    "MigrationWave",
    "PlanRevisionRepository",
    "PostgresPlanRevisionRepository",
    "RoadmapConstraint",
    "RoadmapConstraintKind",
    "WaveWorkload",
    "generate_roadmap",
]
