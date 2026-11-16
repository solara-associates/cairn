"""R3-04: unified diff artefact and preview API.

Spec §16's R3-04 row: "Diff retrievable; no source mutation". Spec §9's
endpoint table:

- ``POST /v1/projects/{id}/transformations`` -- "Scan and produce
  preview", ``ENGINEER+``, Class B.
- ``GET /v1/transformations/{run_id}`` -- "Run summary", ``VIEWER+``,
  Class A.
- ``GET /v1/transformations/{run_id}/diff`` -- "Unified diff artefact",
  ``VIEWER+``, Class A.

729/R3-05 adds a fourth route to this same module (reading it as merged
first, per that unit's brief):

- ``POST /v1/transformations/{run_id}:validate`` -- "Run validation",
  ``ENGINEER+``, Class B (spec §9's own row). Runs every configured
  ``ValidationPort`` check (``cairn_modules.transformation.validation``)
  against this run's already-recorded manifest and diff -- never against
  a re-fetched copy of the customer repository, and never applying
  anything to a real file either (the same "proposed, never applied"
  discipline 726/728 already established) -- and records the aggregated
  ``ValidationRun`` on this module's own registry. Spec S16/R3-05's
  acceptance text, "failures block approval", is a real control, not
  advisory text: ``cairn_modules.transformation.validation.
  require_validation_passed`` raises when any check failed, and is the
  gate a later unit (731's sandbox) is expected to call before treating a
  run as safe to execute. This route itself never calls that gate to
  refuse its own response -- "run validation" is reporting the outcome,
  not an approval action in its own right (spec §9 has no approval route
  for transformations yet; that is R4's ``:decide`` shape, out of this
  unit's scope) -- so a failing run still gets a 200 here, with
  ``approved: false`` and every failing check's reason visible to the
  caller, the same "never silently swallow a failure" discipline every
  other result shape in this codebase already uses.

732/R3-07 adds two more routes to this same module (reading it as merged
first, per that unit's brief, touching neither 728's nor 729's own
entries):

- ``POST /v1/transformations/{run_id}/evidence-package`` -- seals
  730's ``build_transformation_evidence_package`` for this run,
  mirroring ``cairn_api.routes_assessment.build_run_evidence_package``'s
  own route exactly (same per-``(tenant_id, project_id)``
  ``previous_hash`` chaining, same ``{"envelope": ..., "report": ...}``
  response shape -- here the "report" half is this run's own summary/
  diff/validation reflection rather than a rendered text report, since
  R3 has no rendered-report story of its own). Not in spec §9's own
  endpoint table (neither is the assessment route this mirrors) -- the
  same judgement call R1-17/R1-18 already made for evidence export
  having no dedicated spec table row of its own. Class B
  ``WORKSPACE_MUTATION``/``INTERNAL_MUTATION`` (sealing and signing is
  this app's own workspace action; it reads a customer repository
  nowhere in this call path), ``ENGINEER+`` -- the same role cell as
  every other mutation in this module.
- ``POST /v1/transformations/{run_id}/review-comments`` / ``GET
  /v1/transformations/{run_id}/review-comments`` -- spec S16/R3-07's own
  acceptance text, "Engineer can review, comment, request changes", as a
  lightweight, append-only annotation thread (``cairn_modules.
  transformation.review``) attached to the run -- not a new approval
  workflow of its own (spec §9 has no transformation approval route
  yet, same scope line 729's own docstring above already draws for
  ``:validate``). The POST route's role gate deliberately includes
  ``Role.REVIEWER`` alongside ``CREATE_ROLES`` -- spec §12.1's own
  ``REVIEWER`` row ("Approve/reject, accept exceptions (separation of
  duties)") is the one role elsewhere in this spec whose entire
  capability *is* this action, so excluding it here (just because
  ``REVIEWER`` sits below ``ENGINEER`` in that table's listed privilege
  order) would silently lock out the role spec §12.1 names for exactly
  this purpose -- named explicitly as a judgement call, the same
  discipline this module's docstring already uses for its "X+" readings
  elsewhere. A failing (``REQUEST_CHANGES``) review visibly blocks
  further progress, not advisory text: every response from both routes
  carries the thread's own ``RunReviewThread.blocked`` property
  alongside the comment list, so a console (or any other caller) never
  has to recompute "is this run blocked by review" from raw comment
  order itself.

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

import dataclasses
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cairn_contracts.transformation import RepositoryRef, SourceFile
from cairn_kernel.errors import NotFoundError, UnauthenticatedError
from cairn_kernel.evidence import EvidenceSigner
from cairn_kernel.security import Principal, Role, require_roles
from cairn_modules.transformation.diff import TransformationDiff, render_transformation_diff
from cairn_modules.transformation.engine import TransformationPort
from cairn_modules.transformation.evidence import build_transformation_evidence_package
from cairn_modules.transformation.review import (
    ReviewComment,
    ReviewDecisionKind,
    RunReviewThread,
    add_review_comment,
)
from cairn_modules.transformation.runs import TransformationRunRecord, TransformationRunRepository
from cairn_modules.transformation.source import RepositorySourcePort
from cairn_modules.transformation.validation import (
    ValidationPort,
    ValidationRequest,
    ValidationRun,
    run_validation,
)
from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, field_validator

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

VALIDATE_ROLES: tuple[Role, ...] = CREATE_ROLES
"""Spec §9's ``POST /v1/transformations/{run_id}:validate`` row is
``ENGINEER+`` -- the exact same role cell as the create route, so this is
the same tuple, not a re-derivation that could silently drift from it."""

EVIDENCE_ROLES: tuple[Role, ...] = CREATE_ROLES
"""Sealing a transformation run's evidence package is this module's own
workspace mutation, same role cell as every other mutation route here."""

REVIEW_ROLES: tuple[Role, ...] = (*CREATE_ROLES, Role.REVIEWER)
"""``ENGINEER+`` (this story's own acceptance text names ``ENGINEER`` by
name) plus ``Role.REVIEWER`` -- spec §12.1's own capability row for
``REVIEWER`` ("Approve/reject, accept exceptions (separation of
duties)") is this exact action, named explicitly here rather than
silently excluded just because that role sits below ``ENGINEER`` in
spec §12.1's listed privilege order. See this module's own docstring for
the full reasoning."""


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
    customer repository to render the artefact.

    ``validation`` is ``None`` until 729's ``:validate`` route has been
    called for this run at least once -- a run is not implicitly
    "validated: passed" just because nothing has checked it yet; the
    absence of a ``ValidationRun`` is reported as such, never silently
    read as approval.
    """

    record: TransformationRunRecord
    files: tuple[SourceFile, ...]
    repository_ref: RepositoryRef | None = None
    validation: ValidationRun | None = None
    review_thread: RunReviewThread | None = None


class TransformationRegistry:
    """In-memory, process-local index of recorded runs, keyed by
    ``run_id`` -- the same "real repository is the source of truth; this
    index only serves the reads this story's routes need" simplification
    ``routes_design.py``'s ``DesignRegistry`` already makes. Thread-safe
    for writes; reads never mutate state."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, _IndexedRun] = {}

    def put_run(
        self,
        record: TransformationRunRecord,
        files: tuple[SourceFile, ...],
        *,
        repository_ref: RepositoryRef | None = None,
    ) -> None:
        with self._lock:
            self._runs[record.run_id] = _IndexedRun(
                record=record,
                files=files,
                repository_ref=repository_ref,
                review_thread=RunReviewThread(run_id=record.run_id),
            )

    def put_validation(self, run_id: str, validation: ValidationRun) -> None:
        """Record 729's aggregated ``ValidationRun`` against an already-
        recorded run. Raises ``NotFoundError`` if ``run_id`` is unknown --
        never fabricates an entry for a run that was never recorded."""

        with self._lock:
            existing = self._runs.get(run_id)
            if existing is None:
                raise NotFoundError(f"transformation run {run_id} not found")
            self._runs[run_id] = dataclasses.replace(existing, validation=validation)

    def add_review_comment(self, run_id: str, comment: ReviewComment) -> RunReviewThread:
        """Appends 732's ``ReviewComment`` to this run's own thread.
        Raises ``NotFoundError`` if ``run_id`` is unknown -- never
        fabricates a thread for a run that was never recorded."""

        with self._lock:
            existing = self._runs.get(run_id)
            if existing is None:
                raise NotFoundError(f"transformation run {run_id} not found")
            thread = existing.review_thread or RunReviewThread(run_id=run_id)
            thread = add_review_comment(thread, comment)
            self._runs[run_id] = dataclasses.replace(existing, review_thread=thread)
            return thread

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


class CreateReviewCommentRequest(BaseModel):
    """Spec S16/R3-07's own acceptance text, "Engineer can review,
    comment, request changes" -- ``decision`` defaults to a plain
    ``COMMENT`` (an annotation with no decision at all is still a valid
    review action, e.g. "nit: naming" with no blocking intent), and a
    caller names ``REQUEST_CHANGES``/``APPROVE`` explicitly when the
    comment also carries one of those two decisions."""

    model_config = ConfigDict(extra="forbid")

    decision: ReviewDecisionKind = ReviewDecisionKind.COMMENT
    body: str

    @field_validator("body")
    @classmethod
    def _body_is_not_blank(cls, value: str) -> str:
        # Caught here, at the request boundary, as a real 422 -- rather
        # than left to surface as an unhandled 500 from
        # ``ReviewComment.__post_init__``'s own (defense-in-depth) guard
        # of the same invariant.
        if not value.strip():
            raise ValueError("a review comment must have a non-empty body")
        return value


def _run_summary(
    record: TransformationRunRecord,
    *,
    validation: ValidationRun | None = None,
    review_thread: RunReviewThread | None = None,
) -> dict[str, Any]:
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
        "validation": _validation_summary(validation) if validation is not None else None,
        "review": _review_summary(review_thread) if review_thread is not None else None,
    }


def _validation_summary(validation: ValidationRun) -> dict[str, Any]:
    return {
        "run_id": validation.run_id,
        "approved": validation.approved,
        "results": [
            {"check_id": result.check_id, "passed": result.passed, "reason": result.reason}
            for result in validation.results
        ],
    }


def _review_summary(thread: RunReviewThread) -> dict[str, Any]:
    """732's own response shape -- every response from the review routes
    carries ``blocked``/``reviewed`` alongside the raw comment list, so a
    caller never has to recompute "is this run blocked by review" from
    comment order itself (see this module's own docstring)."""

    return {
        "run_id": thread.run_id,
        "blocked": thread.blocked,
        "reviewed": thread.reviewed,
        "comments": [
            {
                "reviewer_actor_id": comment.reviewer_actor_id,
                "decision": comment.decision.value,
                "body": comment.body,
                "created_at": comment.created_at,
            }
            for comment in thread.comments
        ],
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
    evidence_signer: EvidenceSigner,
    validation_checks: tuple[ValidationPort, ...] = (),
) -> None:
    """Register the R3-04 transformation routes directly on ``app``.

    Directly on ``app``, not via ``include_router`` -- see
    ``cairn_api.routes_projects.register_projects_routes`` for why.
    """

    router = app
    # 732/R3-07's evidence-package route: the same per-(tenant, project)
    # ``previous_hash`` chain discipline ``cairn_api.routes_assessment.
    # register_assessment_routes``'s own closure-local ``_evidence_chain``
    # already uses, kept separately from that module's own dict -- a
    # transformation run's evidence chain and an assessment run's
    # evidence chain are two different subjects/chains, never merged.
    _evidence_chain: dict[tuple[str, str], str] = {}

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
        registry.put_run(record, files, repository_ref=payload.repository_ref)
        return jsonable_encoder(_run_summary(record))

    @router.get("/v1/transformations/{run_id}")
    def get_transformation(run_id: str, principal: Principal = Depends(get_principal)) -> dict:
        require_roles(principal, *READ_ROLES)
        indexed = _load_indexed_run(run_id, principal)
        return jsonable_encoder(
            _run_summary(
                indexed.record,
                validation=indexed.validation,
                review_thread=indexed.review_thread,
            )
        )

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

    @router.post("/v1/transformations/{run_id}:validate")
    def validate_transformation(
        run_id: str, principal: Principal = Depends(get_principal)
    ) -> dict:
        require_roles(principal, *VALIDATE_ROLES)
        indexed = _load_indexed_run(run_id, principal)
        diff = render_transformation_diff(
            run_id=run_id, files=indexed.files, manifest=indexed.record.manifest
        )
        request = ValidationRequest(
            run_id=run_id, files=indexed.files, manifest=indexed.record.manifest, diff=diff
        )
        validation_run = run_validation(request, checks=validation_checks)
        registry.put_validation(run_id, validation_run)
        return jsonable_encoder(_validation_summary(validation_run))

    @router.post("/v1/transformations/{run_id}/evidence-package")
    def build_run_evidence_package(
        run_id: str, principal: Principal = Depends(get_principal)
    ) -> dict[str, Any]:
        require_roles(principal, *EVIDENCE_ROLES)
        indexed = _load_indexed_run(run_id, principal)
        diff = render_transformation_diff(
            run_id=run_id, files=indexed.files, manifest=indexed.record.manifest
        )
        package_id = f"{indexed.record.project_id}:{indexed.record.run_id}"
        # Keyed by (tenant_id, project_id), the same reasoning
        # ``routes_assessment.build_run_evidence_package`` already names
        # explicitly: project_id is never independently validated against
        # real project ownership on this path, so two different tenants
        # naming the same project_id must never chain their evidence
        # packages together.
        chain_key = (indexed.record.tenant_id, indexed.record.project_id)
        envelope = build_transformation_evidence_package(
            indexed.record,
            package_id=package_id,
            signer=evidence_signer,
            created_at=datetime.now(UTC),
            files=indexed.files,
            repository_ref=indexed.repository_ref,
            diff=diff,
            validation=indexed.validation,
            previous_hash=_evidence_chain.get(chain_key),
        )
        _evidence_chain[chain_key] = envelope.payload_hash
        report = _run_summary(
            indexed.record,
            validation=indexed.validation,
            review_thread=indexed.review_thread,
        )
        return jsonable_encoder({"envelope": envelope.to_dict(), "report": report})

    @router.post("/v1/transformations/{run_id}/review-comments")
    def create_review_comment(
        run_id: str,
        payload: CreateReviewCommentRequest,
        principal: Principal = Depends(get_principal),
    ) -> dict[str, Any]:
        require_roles(principal, *REVIEW_ROLES)
        _load_indexed_run(run_id, principal)
        comment = ReviewComment(
            run_id=run_id,
            reviewer_actor_id=principal.subject,
            decision=payload.decision,
            body=payload.body,
            created_at=datetime.now(UTC),
        )
        thread = registry.add_review_comment(run_id, comment)
        return jsonable_encoder(_review_summary(thread))

    @router.get("/v1/transformations/{run_id}/review-comments")
    def list_review_comments(
        run_id: str, principal: Principal = Depends(get_principal)
    ) -> dict[str, Any]:
        require_roles(principal, *READ_ROLES)
        indexed = _load_indexed_run(run_id, principal)
        thread = indexed.review_thread or RunReviewThread(run_id=run_id)
        return jsonable_encoder(_review_summary(thread))


__all__ = [
    "CREATE_ROLES",
    "EVIDENCE_ROLES",
    "READ_ROLES",
    "REVIEW_ROLES",
    "VALIDATE_ROLES",
    "CreateReviewCommentRequest",
    "CreateTransformationRequest",
    "TransformationRegistry",
    "get_principal",
    "register_transformation_routes",
]
