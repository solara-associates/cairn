"""R3-04: unified diff artefact and preview API.

Spec §16's R3-04 row: "Diff retrievable; no source mutation". Spec §9's
endpoint table:

- ``POST /v1/projects/{id}/transformations`` -- "Scan and produce
  preview", ``ENGINEER+``, Class B.
- ``GET /v1/transformations/{run_id}`` -- "Run summary", ``VIEWER+``,
  Class A.
- ``GET /v1/transformations/{run_id}/diff`` -- "Unified diff artefact",
  ``VIEWER+``, Class A.

Classification (``cairn_kernel.classification.matrix``): the POST route
triggers 721's ``RepositorySourcePort.fetch`` (reads a customer's
repository, never writes to it -- ADR-010/R3-01's own "no write-back"
discipline) and 726's ``TransformationPort.transform`` (computes a
manifest, applies nothing) and then records that manifest as CAIRN's
own workspace state (726's ``TransformationRunRepository``) -- it never
crosses into a customer environment with a write, so it is Class B
``WORKSPACE_MUTATION``/``INTERNAL_MUTATION`` with no compensation
contract, the same reasoning every prior story's own-workspace-only
write route in this module uses (``routes_design.py``'s
``POST /v1/projects/{project_id}/designs``, ``routes_connections.py``'s
connection-create route). The two GET routes only read that already-
recorded state, so both are Class A ``READ_ONLY``, the same as every
other read route in this app.

Role gating: this codebase's existing RBAC discipline
(``cairn_kernel.security.require_roles``, see ``cairn_modules.projects.
service.ProjectService``/``cairn_modules.mappings.service.
MappingService``) expresses an "X+" role requirement from spec §12.1's
table as the explicit tuple of roles at or above ``X`` in that table's
own listed order (``TENANT_ADMIN``, ``PROJECT_OWNER``, ``ARCHITECT``,
``ENGINEER``, ``REVIEWER``, ``AUDITOR``, ``VIEWER``) -- ``Role``'s own
enum member order matches that table exactly. ``ENGINEER+`` is read the
same way ``ProjectService.MANAGE_ROLES``/``MappingService.PROPOSE_
ROLES`` already read their own "X only"/"X+" spec cells: the roles at or
above ``ENGINEER`` in that order (``TENANT_ADMIN``, ``PROJECT_OWNER``,
``ARCHITECT``, ``ENGINEER`` -- matching spec §12.1's own ``ENGINEER``
row, "Create ingestions/transformations"). ``VIEWER+`` is read the same
way ``ProjectService.READ_ROLES``/``MappingService.READ_ROLES`` already
read "any granted tenant role" -- ``VIEWER`` is the least-privileged row
in that table, so every role satisfies "VIEWER or higher".

Tenant isolation: every route below applies the same "filter after
load, 404 never Forbidden" discipline ``routes_design.py``'s
``_load_design``/``_load_visible_design_revisions`` already use -- a
run belonging to another tenant is reported as ``NotFoundError`` (404),
never leaked as data or as a 403, per spec §12.2.

Persistence/registry split: 726's ``TransformationRunRepository``
(``record_run``) is the real append-only record of this run (its port
has no ``get_run(run_id)`` method -- its two reads,
``list_runs``/``latest_run``, are scoped by ``(tenant_id, project_id)``,
not by a bare ``run_id``). ``GET /v1/transformations/{run_id}`` and its
``/diff`` child take only a ``run_id`` with no project id in the path
(spec §9's own row shape), so this module keeps its own in-memory,
process-local ``TransformationRegistry`` index (run_id -> the record
plus the exact ``SourceFile`` sequence 721's port fetched for it) for
direct by-run-id lookup, the same simplification ``routes_design.py``'s
``DesignRegistry`` already makes for ``GET /v1/designs/{design_id}``
(no project id in that path either) -- 726's real repository is still
the one source of truth that gets written to; this index only serves
reads this story's two GET routes need and 726's port protocol does not
shape for.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from cairn_contracts.transformation import RepositoryRef, SourceFile
from cairn_kernel.errors import NotFoundError, UnauthenticatedError
from cairn_kernel.security import Principal, Role, require_roles
from cairn_modules.transformation.diff import TransformationDiff, render_transformation_diff
from cairn_modules.transformation.engine import TransformationPort
from cairn_modules.transformation.runs import TransformationRunRecord, TransformationRunRepository
from cairn_modules.transformation.source import RepositorySourcePort
from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict

CREATE_ROLES: tuple[Role, ...] = (
    Role.TENANT_ADMIN,
    Role.PROJECT_OWNER,
    Role.ARCHITECT,
    Role.ENGINEER,
)
"""Spec §12.1's ``ENGINEER`` row ("Create ingestions/transformations")
read as ``ENGINEER+``: every role at or above ``ENGINEER`` in that
table's own order. See this module's own docstring for the full
reasoning -- the same judgement call ``ProjectService.MANAGE_ROLES``/
``MappingService.PROPOSE_ROLES`` already make for their own "X+" spec
cells."""

READ_ROLES: tuple[Role, ...] = tuple(Role)
"""``VIEWER+`` read as "any granted tenant role" -- ``VIEWER`` is the
least-privileged row in spec §12.1's table, matching
``ProjectService.READ_ROLES``/``MappingService.READ_ROLES``."""


def get_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise UnauthenticatedError("request is not authenticated")
    return principal


@dataclass(frozen=True, slots=True)
class _IndexedRun:
    """One recorded run plus the exact ``SourceFile`` sequence 721's
    port fetched for it, kept together so ``GET .../diff`` never has to
    re-fetch (and risk re-fetching something different) from the
    customer repository to render the artefact."""

    record: TransformationRunRecord
    files: tuple[SourceFile, ...]


class TransformationRegistry:
    """In-memory, process-local index of recorded runs, keyed by
    ``run_id`` -- the same "real repository is the source of truth; this
    index only serves the reads this story's routes need" simplification
    ``routes_design.py``'s ``DesignRegistry`` already makes. Thread-safe
    for writes; reads never mutate state."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, _IndexedRun] = {}

    def put_run(self, record: TransformationRunRecord, files: tuple[SourceFile, ...]) -> None:
        with self._lock:
            self._runs[record.run_id] = _IndexedRun(record=record, files=files)

    def get_run(self, run_id: str) -> _IndexedRun | None:
        return self._runs.get(run_id)


class CreateTransformationRequest(BaseModel):
    """Spec §9's ``POST /v1/projects/{id}/transformations`` body: the
    one ``RepositoryRef`` (Git ref or uploaded archive, spec §16's R3-01
    tagged union) to scan. This route does not accept raw source text --
    721's ``RepositorySourcePort`` is always the one path a source file's
    content enters this pipeline through, so a diff's provenance always
    traces back to a real fetched ref, never to text a caller typed
    directly into this request."""

    model_config = ConfigDict(extra="forbid")

    repository_ref: RepositoryRef


def _run_summary(record: TransformationRunRecord) -> dict[str, Any]:
    manifest = record.manifest
    return {
        "run_id": record.run_id,
        "project_id": record.project_id,
        "run_number": record.run_number,
        "source_file_ids": list(manifest.source_file_ids),
        "applied_count": manifest.applied_count,
        "skipped_count": manifest.skipped_count,
        "unsupported_count": manifest.unsupported_count,
        "created_by": record.created_by,
        "created_at": record.created_at,
    }


def _diff_summary(diff: TransformationDiff) -> dict[str, Any]:
    return {
        "run_id": diff.run_id,
        "source_file_ids": list(diff.source_file_ids),
        "applied_count": diff.applied_count,
        "skipped_count": diff.skipped_count,
        "unsupported_count": diff.unsupported_count,
        "files": [
            {
                "source_file_id": file_diff.source_file_id,
                "changed": file_diff.changed,
                "unified_diff": file_diff.unified_diff,
                "original_content": file_diff.original_content,
                "rendered_content": file_diff.rendered_content,
                "applied_count": file_diff.applied_count,
                "skipped_count": file_diff.skipped_count,
                "unsupported_count": file_diff.unsupported_count,
                "entries": [
                    {
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
                    for entry in file_diff.entries
                ],
            }
            for file_diff in diff.files
        ],
    }


def register_transformation_routes(
    app: FastAPI,
    *,
    registry: TransformationRegistry,
    source_port: RepositorySourcePort,
    transformation_port: TransformationPort,
    run_repository: TransformationRunRepository,
) -> None:
    """Register the R3-04 transformation routes directly on ``app``.

    Directly on ``app``, not via ``include_router`` -- see
    ``cairn_api.routes_projects.register_projects_routes`` for why.
    """

    router = app

    def _load_indexed_run(run_id: str, principal: Principal) -> _IndexedRun:
        indexed = registry.get_run(run_id)
        if indexed is None or indexed.record.tenant_id != principal.tenant_id.value:
            raise NotFoundError(f"transformation run {run_id} not found")
        return indexed

    @router.post("/v1/projects/{project_id}/transformations")
    def create_transformation(
        project_id: str,
        payload: CreateTransformationRequest,
        principal: Principal = Depends(get_principal),
    ) -> dict:
        require_roles(principal, *CREATE_ROLES)
        tenant_id = principal.tenant_id.value
        files = tuple(source_port.fetch(payload.repository_ref))
        manifest = transformation_port.transform(files)
        record = run_repository.record_run(
            tenant_id=tenant_id,
            project_id=project_id,
            manifest=manifest,
            created_by=principal.subject,
        )
        registry.put_run(record, files)
        return jsonable_encoder(_run_summary(record))

    @router.get("/v1/transformations/{run_id}")
    def get_transformation(run_id: str, principal: Principal = Depends(get_principal)) -> dict:
        require_roles(principal, *READ_ROLES)
        indexed = _load_indexed_run(run_id, principal)
        return jsonable_encoder(_run_summary(indexed.record))

    @router.get("/v1/transformations/{run_id}/diff")
    def get_transformation_diff(
        run_id: str, principal: Principal = Depends(get_principal)
    ) -> dict:
        require_roles(principal, *READ_ROLES)
        indexed = _load_indexed_run(run_id, principal)
        diff = render_transformation_diff(
            run_id=run_id, files=indexed.files, manifest=indexed.record.manifest
        )
        return jsonable_encoder(_diff_summary(diff))


__all__ = [
    "CREATE_ROLES",
    "READ_ROLES",
    "CreateTransformationRequest",
    "TransformationRegistry",
    "get_principal",
    "register_transformation_routes",
]
