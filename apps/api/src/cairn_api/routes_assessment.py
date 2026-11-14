"""R1-15: async operation API for assessment runs.

A ``POST`` queues a run and advances it in the background (FastAPI's
``BackgroundTasks``, run after the response is sent) -- the client gets
the run id back immediately rather than blocking on the full pipeline;
a ``GET`` polls the run's current coverage/state. This is the "async
operation" half of R1-15; the pipeline itself is
``cairn_modules.assessment``.

Every handler checks the loaded run's tenant against the caller's own
tenant and raises ``NotFoundError`` on a mismatch (never leaks that a
run exists for another tenant) -- the same ambient-tenant-context
discipline ``cairn_api.AuthMiddleware`` establishes elsewhere, applied
by hand here since no persistent, tenant-scoped repository exists yet
for assessment runs (in-memory only, per ``AssessmentService``).
"""

from __future__ import annotations

import uuid

from cairn_contracts.finops import PriceListRelease
from cairn_contracts.posture import ControlCatalogueRelease
from cairn_kernel.errors import NotFoundError, UnauthenticatedError
from cairn_kernel.security import Principal
from cairn_modules.assessment import (
    AssessmentRun,
    AssessmentService,
    Stage,
    build_real_stages,
    coverage_report,
)
from cairn_modules.finops import TcoAssumptions
from fastapi import BackgroundTasks, Depends, FastAPI, Request
from pydantic import BaseModel


def get_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise UnauthenticatedError("request is not authenticated")
    return principal


class AssessmentRunFile(BaseModel):
    source_format: str
    content: str


class QueueAssessmentRunRequest(BaseModel):
    files: list[AssessmentRunFile] = []


class AssessmentRunResponse(BaseModel):
    run_id: str
    state: str
    coverage: float
    completed_stages: list[str]
    pending_stages: list[str]
    failures: list[dict]

    @classmethod
    def from_run(cls, run: AssessmentRun) -> AssessmentRunResponse:
        report = dict(coverage_report(run))
        return cls(
            run_id=report["run_id"],
            state=report["state"],
            coverage=report["coverage"],
            completed_stages=list(report["completed_stages"]),
            pending_stages=list(report["pending_stages"]),
            failures=[dict(failure) for failure in report["failures"]],
        )


def _require_same_tenant(run: AssessmentRun, principal: Principal) -> None:
    if run.tenant_id != principal.tenant_id.value:
        raise NotFoundError(f"assessment run {run.run_id} not found")


def register_assessment_routes(
    app: FastAPI,
    *,
    service: AssessmentService,
    control_catalogue: ControlCatalogueRelease,
    price_list: PriceListRelease,
) -> None:
    """Register the R1-15 assessment-run routes directly on ``app``.

    Directly on ``app``, not via ``include_router`` -- see
    ``cairn_api.routes_projects.register_projects_routes`` for why.

    ``control_catalogue``/``price_list`` are loaded once by the caller
    (``create_app``), not reloaded from disk on every request.
    """
    router = app

    def _build_stage_fns(files: list[AssessmentRunFile], *, run_id: str) -> dict[str, Stage]:
        return build_real_stages(
            ingestion_files=[(f.source_format, f.content) for f in files],
            billing_items=[],
            control_catalogue=control_catalogue,
            price_list=price_list,
            tco_assumptions=TcoAssumptions(horizon_periods=1, growth_rate=0.0, discount_rate=0.0),
            ingest_run_id=run_id,
            cost_currency="GBP",
            scenario_id=run_id,
        )

    @router.post(
        "/v1/projects/{project_id}/assessment-runs",
        response_model=AssessmentRunResponse,
        status_code=202,
    )
    def queue_assessment_run(
        project_id: str,
        payload: QueueAssessmentRunRequest,
        background_tasks: BackgroundTasks,
        principal: Principal = Depends(get_principal),
    ) -> AssessmentRunResponse:
        run_id = str(uuid.uuid4())
        run = service.queue_run(
            run_id=run_id, tenant_id=principal.tenant_id.value, project_id=project_id
        )
        stage_fns = _build_stage_fns(payload.files, run_id=run_id)
        background_tasks.add_task(service.advance_run, run_id, stage_fns=stage_fns)
        return AssessmentRunResponse.from_run(run)

    @router.get(
        "/v1/projects/{project_id}/assessment-runs/{run_id}",
        response_model=AssessmentRunResponse,
    )
    def get_assessment_run(
        project_id: str, run_id: str, principal: Principal = Depends(get_principal)
    ) -> AssessmentRunResponse:
        run = service.get_run(run_id)
        _require_same_tenant(run, principal)
        if run.project_id != project_id:
            raise NotFoundError(f"assessment run {run_id} not found in project {project_id}")
        return AssessmentRunResponse.from_run(run)


__all__ = ["get_principal", "register_assessment_routes"]
