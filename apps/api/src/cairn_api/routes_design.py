"""R2-08: design/plan export API (spec §16's R2-08 row: "Machine-readable
and human-readable exports").

Spec §9.2's endpoint table lists ``GET /v1/designs/{design_id}`` and
``GET /v1/designs/{design_id}/diagram`` but, at the time this story
landed, no ``/v1/designs/{design_id}/report`` route -- even though the
backlog row names "report" as one of the three export forms. This
brief's own resolution (decided by Allan for this run) is to add that
missing route here, as the documentation fix spec §9.2 itself still
needs (see this session's handover, not the spec file).

Every route below is Class A (read-only, workspace-scoped data,
ADR-010's "never crosses into a customer environment"): a design,
diagram, report, plan list or plan revision belonging to another tenant
is reported as ``NotFoundError``, never leaked as Forbidden or as real
data -- the same ambient-tenant-context discipline
``routes_assessment.py``/``routes_connections.py`` already establish.

``DesignRegistry`` is an in-memory, process-local store -- the same
simplification ``AssessmentService``/``ConnectionRegistry`` already make
elsewhere in this app. 703/705's real Postgres adapters
(``PostgresDesignRevisionRepository``/``PostgresPlanRevisionRepository``)
already exist; wiring this registry to them, and adding a write path that
actually calls ``generate_target_model``/``generate_roadmap``/
``compile_diagram``/``generate_iac_plan``, is later work -- this story's
own scope is the export shape (JSON bundle, diagram, report) spec §16's
R2-08 row asks for, read against whatever was already generated.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from cairn_kernel.errors import NotFoundError, UnauthenticatedError
from cairn_kernel.security import Principal
from cairn_modules.approvals.model import RevisionRecord
from cairn_modules.design.diagram import DiagramArtefact
from cairn_modules.design.target_model import TargetModel
from cairn_modules.planning.iac_plan import IaCPlanArtefact
from cairn_modules.planning.roadmap import MigrationRoadmap
from cairn_modules.reporting import build_design_export_bundle, render_design_report
from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder


def get_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise UnauthenticatedError("request is not authenticated")
    return principal


@dataclass(frozen=True, slots=True)
class DesignRecord:
    """One generated design, ready to export: 703's target model and
    its revision, 704's compiled diagram and 706's IaC preview, plus
    the id of the plan its roadmap was sequenced against."""

    tenant_id: str
    project_id: str
    plan_id: str
    target_model: TargetModel
    revision: RevisionRecord
    diagram: DiagramArtefact
    iac: IaCPlanArtefact


@dataclass(frozen=True, slots=True)
class PlanRecord:
    """One recorded plan revision: 705/706's roadmap plus the
    ``subject_revision`` row (``subject_kind="plan"``) that recorded
    it."""

    tenant_id: str
    project_id: str
    plan_id: str
    roadmap: MigrationRoadmap
    revision: RevisionRecord


class DesignRegistry:
    """In-memory, process-local store of generated designs and plan
    revisions this API exposes for export. Thread-safe for writes; reads
    never mutate state. Designs/plans are added directly (by whatever
    generated them), not through an HTTP write route in this story."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._designs: dict[str, DesignRecord] = {}
        self._plan_revisions: dict[str, list[PlanRecord]] = {}

    def put_design(self, design_id: str, record: DesignRecord) -> None:
        with self._lock:
            self._designs[design_id] = record

    def get_design(self, design_id: str) -> DesignRecord | None:
        return self._designs.get(design_id)

    def add_plan_revision(self, plan_id: str, record: PlanRecord) -> None:
        with self._lock:
            self._plan_revisions.setdefault(plan_id, []).append(record)

    def list_plan_revisions(self, plan_id: str) -> tuple[PlanRecord, ...]:
        return tuple(self._plan_revisions.get(plan_id, ()))

    def latest_plan_revisions_for_project(self, project_id: str) -> tuple[PlanRecord, ...]:
        """The most recent revision of every plan whose most recent
        revision belongs to ``project_id`` -- tenant filtering is the
        caller's job (same "filter after load, never before" discipline
        every other route in this module follows)."""
        latest: list[PlanRecord] = []
        for revisions in self._plan_revisions.values():
            if revisions and revisions[-1].project_id == project_id:
                latest.append(revisions[-1])
        return tuple(latest)


def register_design_routes(app: FastAPI, *, registry: DesignRegistry) -> None:
    """Register the R2-08 design/plan export routes directly on ``app``.

    Directly on ``app``, not via ``include_router`` -- see
    ``cairn_api.routes_projects.register_projects_routes`` for why.
    """
    router = app

    def _load_design(design_id: str, principal: Principal) -> DesignRecord:
        record = registry.get_design(design_id)
        if record is None or record.tenant_id != principal.tenant_id.value:
            raise NotFoundError(f"design {design_id} not found")
        return record

    def _load_visible_plan_revisions(plan_id: str, principal: Principal) -> tuple[PlanRecord, ...]:
        revisions = registry.list_plan_revisions(plan_id)
        visible = tuple(r for r in revisions if r.tenant_id == principal.tenant_id.value)
        if not visible:
            raise NotFoundError(f"plan {plan_id} not found")
        return visible

    @router.get("/v1/designs/{design_id}")
    def get_design(design_id: str, principal: Principal = Depends(get_principal)) -> dict:
        record = _load_design(design_id, principal)
        plan_revisions = _load_visible_plan_revisions(record.plan_id, principal)
        latest_plan = plan_revisions[-1]
        bundle = build_design_export_bundle(
            target_model=record.target_model,
            design_revision=record.revision,
            diagram=record.diagram,
            plan_id=record.plan_id,
            roadmap=latest_plan.roadmap,
            plan_revision=latest_plan.revision,
            iac=record.iac,
        )
        return jsonable_encoder(bundle)

    @router.get("/v1/designs/{design_id}/diagram")
    def get_design_diagram(design_id: str, principal: Principal = Depends(get_principal)) -> dict:
        record = _load_design(design_id, principal)
        diagram = record.diagram
        return jsonable_encoder(
            {
                "artefact_id": diagram.artefact_id,
                "kind": diagram.kind,
                "revision_id": diagram.revision_id,
                "revision_number": diagram.revision_number,
                "content_hash": diagram.content_hash,
                "rendered_content": diagram.rendered_content,
            }
        )

    @router.get("/v1/designs/{design_id}/report")
    def get_design_report(design_id: str, principal: Principal = Depends(get_principal)) -> dict:
        record = _load_design(design_id, principal)
        plan_revisions = _load_visible_plan_revisions(record.plan_id, principal)
        latest_plan = plan_revisions[-1]
        report = render_design_report(
            target_model=record.target_model,
            design_revision=record.revision,
            plan_id=record.plan_id,
            roadmap=latest_plan.roadmap,
            iac=record.iac,
        )
        return jsonable_encoder(report)

    @router.get("/v1/projects/{project_id}/plans")
    def list_plans(project_id: str, principal: Principal = Depends(get_principal)) -> list[dict]:
        records = registry.latest_plan_revisions_for_project(project_id)
        visible = [record for record in records if record.tenant_id == principal.tenant_id.value]
        return jsonable_encoder(
            [
                {
                    "plan_id": record.plan_id,
                    "revision_id": record.revision.revision_id,
                    "revision_number": record.revision.revision_number,
                    "content_hash": record.revision.content_hash,
                    "wave_count": len(record.roadmap.waves),
                }
                for record in visible
            ]
        )

    @router.get("/v1/plans/{plan_id}/revisions/{revision_number}")
    def get_plan_revision(
        plan_id: str, revision_number: int, principal: Principal = Depends(get_principal)
    ) -> dict:
        revisions = _load_visible_plan_revisions(plan_id, principal)
        match = next(
            (record for record in revisions if record.revision.revision_number == revision_number),
            None,
        )
        if match is None:
            raise NotFoundError(f"plan {plan_id} revision {revision_number} not found")
        return jsonable_encoder(
            {
                "plan_id": match.plan_id,
                "revision_id": match.revision.revision_id,
                "revision_number": match.revision.revision_number,
                "content_hash": match.revision.content_hash,
                "wave_count": len(match.roadmap.waves),
                "waves": match.roadmap.waves,
                "blocked_workload_ids": match.roadmap.blocked_workload_ids,
            }
        )


__all__ = ["DesignRecord", "DesignRegistry", "PlanRecord", "get_principal", "register_design_routes"]
