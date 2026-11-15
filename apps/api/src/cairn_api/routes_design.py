"""R2-08/R2-09: design/plan generation and export API.

R2-08 (merged earlier) added the **read-only** export routes below --
``GET /v1/designs/{design_id}``, its ``/diagram`` and ``/report``
children, and the plan-list/plan-revision routes -- against a
``DesignRegistry`` seeded directly (no write route existed yet; see that
story's own handover). R2-09 ("design console screens") is the first
caller that actually needs to *drive* a design from a browser, so this
story adds the write routes 707 left out, following the exact same
generation recipe ``apps/api/tests/test_design_api.py`` already proves
at the module level (``generate_target_model`` -> ``compile_diagram``/
``generate_iac_plan`` -> ``generate_roadmap``, in a single
``RevisionRecord`` chain per generation):

- ``GET /v1/patterns`` -- the published pattern catalogue (id, category,
  parameter schema), for a console's pattern-select screen.
- ``POST /v1/projects/{project_id}/designs`` -- generate a brand-new
  design (revision 1): resolves every given resource through the
  configured mapping release, compiles a diagram and an IaC preview, and
  sequences the given workloads/decisions into a migration roadmap under
  a new plan.
- ``POST /v1/designs/{design_id}/regenerate`` -- regenerate the *same*
  design with new parameters: a new, higher-numbered revision, built
  from the exact estate/workloads/decisions/pattern/mapping-release the
  first generation recorded. The previous revision is never replaced or
  deleted -- ``GET .../revisions`` and ``GET .../revisions/{n}`` make
  every revision independently retrievable, so a console can show the
  new design next to the old one for comparison (spec §16's R2-09 row:
  "regenerate... old one still visible/comparable").
- ``GET /v1/designs/{design_id}/iac`` -- the IaC plan preview's own
  rendered text and per-resource PLANNED/GAP detail (706), mirroring the
  existing ``/diagram`` route's shape.

``GET /v1/designs/{design_id}/diagram`` additionally now returns each
compiled shape's ``marker`` (``EXACT``/``APPROXIMATE``/``UNAVAILABLE``/
``UNRESOLVED``, 704's own distinct-marker rule) and ``detail`` -- the
exact per-resource data a console needs to make resolved/approximate/
unavailable/unresolved **visibly** distinct on screen, not just present
in the underlying export bundle.

Every route is tenant-scoped exactly like the rest of this module: a
design/plan belonging to another tenant is ``NotFoundError`` (404),
never leaked as data or as Forbidden. The two write routes are Class B
``INTERNAL_MUTATION`` (CAIRN's own workspace state only -- a design, plan
and IaC *preview*; ADR-010's "never applied, never crosses into a
customer environment" is untouched by this story) and are classified as
such in ``cairn_kernel.classification.matrix``.

``DesignRegistry`` remains in-memory and process-local, the same
simplification ``AssessmentService``/``ConnectionRegistry`` already make
elsewhere in this app; 703/705's real Postgres adapters
(``PostgresDesignRevisionRepository``/``PostgresPlanRevisionRepository``)
are not wired in here -- out of this story's own scope, same as 707 left
it.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cairn_contracts.estate import (
    DecisionStatus,
    Dependency,
    Disposition,
    DispositionDecision,
    FactStatus,
    Resource,
    Workload,
)
from cairn_contracts.mapping import MappingRelease
from cairn_contracts.mapping.pattern import Pattern, PatternCatalogueRelease
from cairn_kernel.errors import NotFoundError, UnauthenticatedError
from cairn_kernel.security import Principal
from cairn_modules.approvals.model import RevisionRecord
from cairn_modules.design.diagram import DiagramArtefact, DiagramRendererPort, compile_diagram
from cairn_modules.design.target_model import TargetModel, generate_target_model
from cairn_modules.planning.iac_plan import (
    IAC_PLAN_DISCLAIMER,
    IaCGeneratorPort,
    IaCPlanArtefact,
    generate_iac_plan,
)
from cairn_modules.planning.roadmap import MigrationRoadmap, generate_roadmap
from cairn_modules.reporting import build_design_export_bundle, render_design_report
from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field


def get_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise UnauthenticatedError("request is not authenticated")
    return principal


@dataclass(frozen=True, slots=True)
class DesignRecord:
    """One generated design revision, ready to export: 703's target
    model and its revision, 704's compiled diagram and 706's IaC
    preview, plus the id of the plan its roadmap was sequenced against."""

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


@dataclass(frozen=True, slots=True)
class DesignInputs:
    """The exact inputs a design's first generation used, kept so a
    later ``regenerate`` can rebuild from the same estate/workloads/
    decisions/pattern/mapping-release with only the parameters changed --
    never re-asked of the caller, and never silently substituted."""

    tenant_id: str
    project_id: str
    plan_id: str
    pattern: Pattern
    pattern_catalogue_version: str
    mapping_release: MappingRelease
    target_provider: str
    resources: tuple[Resource, ...]
    workloads: tuple[Workload, ...]
    dependencies: tuple[Dependency, ...]
    dispositions: dict[str, DispositionDecision]


class DesignRegistry:
    """In-memory, process-local store of generated designs and plan
    revisions this API exposes for generation and export. Thread-safe
    for writes; reads never mutate state."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._design_revisions: dict[str, list[DesignRecord]] = {}
        self._design_inputs: dict[str, DesignInputs] = {}
        self._plan_revisions: dict[str, list[PlanRecord]] = {}

    def put_design(self, design_id: str, record: DesignRecord) -> None:
        """Append one more revision of ``design_id``. Despite the name
        (kept for 707's own already-merged callers), this never replaces
        an existing revision -- every call adds a new entry, so the
        previous revision stays retrievable via ``list_design_revisions``."""
        with self._lock:
            self._design_revisions.setdefault(design_id, []).append(record)

    def get_design(self, design_id: str) -> DesignRecord | None:
        """The *latest* revision of ``design_id``, or ``None``."""
        revisions = self._design_revisions.get(design_id)
        return revisions[-1] if revisions else None

    def list_design_revisions(self, design_id: str) -> tuple[DesignRecord, ...]:
        return tuple(self._design_revisions.get(design_id, ()))

    def put_design_inputs(self, design_id: str, inputs: DesignInputs) -> None:
        with self._lock:
            self._design_inputs[design_id] = inputs

    def get_design_inputs(self, design_id: str) -> DesignInputs | None:
        return self._design_inputs.get(design_id)

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


# --- request/response payloads for the two write routes -------------------


class ResourceInput(BaseModel):
    """Minimal estate input a console supplies directly for one design
    generation -- this story does not wire a real ingested-estate lookup
    (no such read API exists yet for R1-06's canonical estate store), so
    the caller states the resources it wants resolved, the same way the
    existing assessment-run route already takes files directly rather
    than reading from a separate store."""

    model_config = ConfigDict(extra="forbid")

    resource_id: str
    provider: str
    service: str
    account_id: str = "unspecified"
    region: str = "unspecified"
    resource_type: str = "unspecified"
    native_id: str | None = None
    name: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class WorkloadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workload_id: str
    name: str
    environment: str = "UNVERIFIED"
    resource_ids: list[str] = Field(default_factory=list)


class DecisionInput(BaseModel):
    """One already-accepted 6R disposition for a workload (R1-14's own
    accept/amend/reject flow is out of this story's scope -- a design is
    generated against whatever disposition the caller already has)."""

    model_config = ConfigDict(extra="forbid")

    workload_id: str
    disposition: Disposition
    rationale: str = ""
    confidence: float = Field(default=0.8, ge=0, le=1)


class CreateDesignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern_id: str
    target_provider: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    resources: list[ResourceInput] = Field(default_factory=list)
    workloads: list[WorkloadInput] = Field(default_factory=list)
    decisions: list[DecisionInput] = Field(default_factory=list)


class RegenerateDesignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parameters: dict[str, Any] = Field(default_factory=dict)


def _resource_from_input(payload: ResourceInput, *, tenant_id: str, project_id: str) -> Resource:
    return Resource(
        resource_id=payload.resource_id,
        tenant_id=tenant_id,
        project_id=project_id,
        provider=payload.provider,
        account_id=payload.account_id,
        region=payload.region,
        service=payload.service,
        resource_type=payload.resource_type,
        native_id=payload.native_id or payload.resource_id,
        name=payload.name,
        tags=dict(payload.tags),
        facts={},
        provenance=(),
        status=FactStatus.OBSERVED,
    )


def _workload_from_input(payload: WorkloadInput, *, tenant_id: str, project_id: str) -> Workload:
    return Workload(
        workload_id=payload.workload_id,
        tenant_id=tenant_id,
        project_id=project_id,
        name=payload.name,
        environment=payload.environment,
        owner=None,
        business_context=None,
        resource_ids=tuple(payload.resource_ids),
        dependency_ids=(),
        facts={},
        disposition=None,
        disposition_confidence=None,
        model_version="r2-09-console-v1",
        mapping_version="r2-09-console-v1",
    )


def _decision_from_input(
    payload: DecisionInput, *, tenant_id: str, project_id: str, decided_by: str
) -> DispositionDecision:
    return DispositionDecision(
        decision_id=f"console-decision-{payload.workload_id}",
        tenant_id=tenant_id,
        project_id=project_id,
        workload_id=payload.workload_id,
        disposition=payload.disposition,
        rationale=payload.rationale or f"{payload.disposition.value} via console",
        confidence=payload.confidence,
        status=DecisionStatus.ACCEPTED,
        decided_by=decided_by,
        decided_at=datetime.now(UTC),
        model_version="r2-09-console-v1",
        mapping_version="r2-09-console-v1",
    )


def _encode_bundle(bundle: Any) -> dict:
    """``jsonable_encoder`` on a dataclass serializes declared fields
    only -- ``DesignExportBundle.version_stamps_consistent`` is a
    ``@property``, not a field, so it is silently dropped by a plain
    ``jsonable_encoder(bundle)`` call. A console inspecting caveats
    needs this exact round-trip property on the wire (spec §16's R2-10
    row this bundle exists to support), so it is added back explicitly
    here rather than only ever being checked in-process."""
    encoded = jsonable_encoder(bundle)
    encoded["version_stamps_consistent"] = bundle.version_stamps_consistent
    return encoded


def _require_pattern(catalogue: PatternCatalogueRelease, pattern_id: str) -> Pattern:
    for pattern in catalogue.patterns:
        if pattern.id == pattern_id:
            return pattern
    raise NotFoundError(f"pattern {pattern_id} is not in the catalogue")


def _build_design(
    *,
    tenant_id: str,
    project_id: str,
    design_id: str,
    plan_id: str,
    revision_number: int,
    pattern: Pattern,
    pattern_catalogue_version: str,
    mapping_release: MappingRelease,
    target_provider: str,
    parameters: dict[str, Any],
    resources: tuple[Resource, ...],
    workloads: tuple[Workload, ...],
    dependencies: tuple[Dependency, ...],
    dispositions: dict[str, DispositionDecision],
    created_by: str,
    diagram_renderer: DiagramRendererPort,
    iac_generator: IaCGeneratorPort,
) -> tuple[DesignRecord, PlanRecord]:
    """The one generation recipe both write routes below share: 703's
    target model, then 704's diagram and 706's IaC preview compiled from
    the same design revision, then 705's roadmap sequenced into a plan
    revision carrying the same revision number -- so a design's Nth
    revision and its plan's Nth revision are always the matching pair."""
    target_model = generate_target_model(
        tenant_id=tenant_id,
        project_id=project_id,
        design_id=design_id,
        estate=resources,
        pattern=pattern,
        pattern_catalogue_version=pattern_catalogue_version,
        mapping_release=mapping_release,
        target_provider=target_provider,
        parameters=parameters,
    )
    created_at = datetime.now(UTC)
    design_revision = RevisionRecord(
        revision_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        project_id=project_id,
        subject_kind="design",
        subject_id=design_id,
        revision_number=revision_number,
        content_hash=target_model.content_hash,
        input_versions=(
            ("pattern_id", target_model.pattern_id),
            ("pattern_catalogue_version", pattern_catalogue_version),
            ("mapping_release_version", mapping_release.version),
        ),
        created_by=created_by,
        created_at=created_at,
    )
    diagram = compile_diagram(
        target_model=target_model, revision=design_revision, renderer=diagram_renderer
    )
    iac = generate_iac_plan(
        target_model=target_model, revision=design_revision, generator=iac_generator
    )
    roadmap = generate_roadmap(
        tenant_id=tenant_id,
        project_id=project_id,
        plan_id=plan_id,
        workloads=workloads,
        dependencies=dependencies,
        dispositions=dispositions,
        target_model=target_model,
    )
    plan_revision = RevisionRecord(
        revision_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        project_id=project_id,
        subject_kind="plan",
        subject_id=plan_id,
        revision_number=revision_number,
        content_hash=roadmap.content_hash,
        input_versions=(("wave_count", str(len(roadmap.waves))),),
        created_by=created_by,
        created_at=created_at,
    )
    design_record = DesignRecord(
        tenant_id=tenant_id,
        project_id=project_id,
        plan_id=plan_id,
        target_model=target_model,
        revision=design_revision,
        diagram=diagram,
        iac=iac,
    )
    plan_record = PlanRecord(
        tenant_id=tenant_id,
        project_id=project_id,
        plan_id=plan_id,
        roadmap=roadmap,
        revision=plan_revision,
    )
    return design_record, plan_record


def _design_summary(design_record: DesignRecord, plan_record: PlanRecord) -> dict[str, Any]:
    target_model = design_record.target_model
    shapes = design_record.diagram.model.shapes
    return {
        "design_id": target_model.design_id,
        "plan_id": design_record.plan_id,
        "revision_number": design_record.revision.revision_number,
        "content_hash": target_model.content_hash,
        "pattern_id": target_model.pattern_id,
        "target_provider": target_model.target_provider,
        "parameters": dict(target_model.parameters),
        "resources": [
            {
                "shape_id": shape.shape_id,
                "source_provider": shape.source_provider,
                "source_service": shape.source_service,
                "target_provider": shape.target_provider,
                "target_service": shape.target_service,
                "marker": shape.marker.value,
                "detail": shape.detail,
            }
            for shape in shapes
        ],
        "wave_count": len(plan_record.roadmap.waves),
        "blocked_workload_ids": list(plan_record.roadmap.blocked_workload_ids),
    }


def register_design_routes(
    app: FastAPI,
    *,
    registry: DesignRegistry,
    pattern_catalogue: PatternCatalogueRelease,
    mapping_release: MappingRelease,
    diagram_renderer: DiagramRendererPort,
    iac_generator: IaCGeneratorPort,
) -> None:
    """Register the R2-08/R2-09 design/plan generation and export routes
    directly on ``app``.

    Directly on ``app``, not via ``include_router`` -- see
    ``cairn_api.routes_projects.register_projects_routes`` for why.
    """
    router = app

    def _load_design(design_id: str, principal: Principal) -> DesignRecord:
        record = registry.get_design(design_id)
        if record is None or record.tenant_id != principal.tenant_id.value:
            raise NotFoundError(f"design {design_id} not found")
        return record

    def _load_visible_design_revisions(
        design_id: str, principal: Principal
    ) -> tuple[DesignRecord, ...]:
        revisions = registry.list_design_revisions(design_id)
        visible = tuple(r for r in revisions if r.tenant_id == principal.tenant_id.value)
        if not visible:
            raise NotFoundError(f"design {design_id} not found")
        return visible

    def _load_visible_plan_revisions(plan_id: str, principal: Principal) -> tuple[PlanRecord, ...]:
        revisions = registry.list_plan_revisions(plan_id)
        visible = tuple(r for r in revisions if r.tenant_id == principal.tenant_id.value)
        if not visible:
            raise NotFoundError(f"plan {plan_id} not found")
        return visible

    @router.get("/v1/patterns")
    def list_patterns(_principal: Principal = Depends(get_principal)) -> list[dict]:
        return jsonable_encoder(
            [
                {
                    "id": pattern.id,
                    "name": pattern.name,
                    "category": pattern.category.value,
                    "description": pattern.description,
                    "parameters": [
                        {
                            "name": parameter.name,
                            "type": parameter.type.value,
                            "description": parameter.description,
                            "required": parameter.required,
                            "default": parameter.default,
                            "allowed_values": list(parameter.allowed_values) or None,
                        }
                        for parameter in pattern.parameters
                    ],
                }
                for pattern in pattern_catalogue.patterns
            ]
        )

    @router.post("/v1/projects/{project_id}/designs")
    def create_design(
        project_id: str,
        payload: CreateDesignRequest,
        principal: Principal = Depends(get_principal),
    ) -> dict:
        pattern = _require_pattern(pattern_catalogue, payload.pattern_id)
        tenant_id = principal.tenant_id.value
        design_id = str(uuid.uuid4())
        plan_id = str(uuid.uuid4())
        resources = tuple(
            _resource_from_input(resource, tenant_id=tenant_id, project_id=project_id)
            for resource in payload.resources
        )
        workloads = tuple(
            _workload_from_input(workload, tenant_id=tenant_id, project_id=project_id)
            for workload in payload.workloads
        )
        dispositions = {
            decision.workload_id: _decision_from_input(
                decision, tenant_id=tenant_id, project_id=project_id, decided_by=principal.subject
            )
            for decision in payload.decisions
        }
        design_record, plan_record = _build_design(
            tenant_id=tenant_id,
            project_id=project_id,
            design_id=design_id,
            plan_id=plan_id,
            revision_number=1,
            pattern=pattern,
            pattern_catalogue_version=pattern_catalogue.version,
            mapping_release=mapping_release,
            target_provider=payload.target_provider,
            parameters=payload.parameters,
            resources=resources,
            workloads=workloads,
            dependencies=(),
            dispositions=dispositions,
            created_by=principal.subject,
            diagram_renderer=diagram_renderer,
            iac_generator=iac_generator,
        )
        registry.put_design(design_id, design_record)
        registry.add_plan_revision(plan_id, plan_record)
        registry.put_design_inputs(
            design_id,
            DesignInputs(
                tenant_id=tenant_id,
                project_id=project_id,
                plan_id=plan_id,
                pattern=pattern,
                pattern_catalogue_version=pattern_catalogue.version,
                mapping_release=mapping_release,
                target_provider=payload.target_provider,
                resources=resources,
                workloads=workloads,
                dependencies=(),
                dispositions=dispositions,
            ),
        )
        return jsonable_encoder(_design_summary(design_record, plan_record))

    @router.post("/v1/designs/{design_id}/regenerate")
    def regenerate_design(
        design_id: str,
        payload: RegenerateDesignRequest,
        principal: Principal = Depends(get_principal),
    ) -> dict:
        inputs = registry.get_design_inputs(design_id)
        existing_revisions = _load_visible_design_revisions(design_id, principal)
        if inputs is None or inputs.tenant_id != principal.tenant_id.value:
            raise NotFoundError(f"design {design_id} not found")
        next_revision_number = existing_revisions[-1].revision.revision_number + 1
        design_record, plan_record = _build_design(
            tenant_id=inputs.tenant_id,
            project_id=inputs.project_id,
            design_id=design_id,
            plan_id=inputs.plan_id,
            revision_number=next_revision_number,
            pattern=inputs.pattern,
            pattern_catalogue_version=inputs.pattern_catalogue_version,
            mapping_release=inputs.mapping_release,
            target_provider=inputs.target_provider,
            parameters=payload.parameters,
            resources=inputs.resources,
            workloads=inputs.workloads,
            dependencies=inputs.dependencies,
            dispositions=inputs.dispositions,
            created_by=principal.subject,
            diagram_renderer=diagram_renderer,
            iac_generator=iac_generator,
        )
        registry.put_design(design_id, design_record)
        registry.add_plan_revision(inputs.plan_id, plan_record)
        return jsonable_encoder(_design_summary(design_record, plan_record))

    @router.get("/v1/designs/{design_id}/revisions")
    def list_design_revisions_route(
        design_id: str, principal: Principal = Depends(get_principal)
    ) -> list[dict]:
        revisions = _load_visible_design_revisions(design_id, principal)
        return jsonable_encoder(
            [
                {
                    "revision_id": record.revision.revision_id,
                    "revision_number": record.revision.revision_number,
                    "content_hash": record.revision.content_hash,
                    "created_at": record.revision.created_at,
                    "parameters": dict(record.target_model.parameters),
                }
                for record in revisions
            ]
        )

    @router.get("/v1/designs/{design_id}/revisions/{revision_number}")
    def get_design_revision_route(
        design_id: str, revision_number: int, principal: Principal = Depends(get_principal)
    ) -> dict:
        revisions = _load_visible_design_revisions(design_id, principal)
        match = next(
            (r for r in revisions if r.revision.revision_number == revision_number), None
        )
        if match is None:
            raise NotFoundError(f"design {design_id} revision {revision_number} not found")
        plan_revisions = _load_visible_plan_revisions(match.plan_id, principal)
        plan_match = next(
            (p for p in plan_revisions if p.revision.revision_number == revision_number), None
        )
        if plan_match is None:
            raise NotFoundError(
                f"design {design_id} revision {revision_number} has no matching plan revision"
            )
        bundle = build_design_export_bundle(
            target_model=match.target_model,
            design_revision=match.revision,
            diagram=match.diagram,
            plan_id=match.plan_id,
            roadmap=plan_match.roadmap,
            plan_revision=plan_match.revision,
            iac=match.iac,
        )
        return _encode_bundle(bundle)

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
        return _encode_bundle(bundle)

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
                "shapes": [
                    {
                        "shape_id": shape.shape_id,
                        "source_provider": shape.source_provider,
                        "source_service": shape.source_service,
                        "target_provider": shape.target_provider,
                        "target_service": shape.target_service,
                        "marker": shape.marker.value,
                        "detail": shape.detail,
                    }
                    for shape in diagram.model.shapes
                ],
            }
        )

    @router.get("/v1/designs/{design_id}/iac")
    def get_design_iac(design_id: str, principal: Principal = Depends(get_principal)) -> dict:
        record = _load_design(design_id, principal)
        iac = record.iac
        return jsonable_encoder(
            {
                "artefact_id": iac.artefact_id,
                "kind": iac.kind,
                "revision_id": iac.revision_id,
                "revision_number": iac.revision_number,
                "content_hash": iac.content_hash,
                "disclaimer": IAC_PLAN_DISCLAIMER,
                "rendered_content": iac.rendered_content,
                "gap_resource_ids": list(iac.gap_resource_ids),
                "resources": [
                    {
                        "resource_id": resource.resource_id,
                        "source_provider": resource.source_provider,
                        "source_service": resource.source_service,
                        "target_provider": resource.target_provider,
                        "target_service": resource.target_service,
                        "status": resource.status.value,
                        "approximate": resource.approximate,
                        "detail": resource.detail,
                    }
                    for resource in iac.model.resources
                ],
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


__all__ = [
    "CreateDesignRequest",
    "DecisionInput",
    "DesignInputs",
    "DesignRecord",
    "DesignRegistry",
    "PlanRecord",
    "RegenerateDesignRequest",
    "ResourceInput",
    "WorkloadInput",
    "get_principal",
    "register_design_routes",
]
