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
from datetime import UTC, datetime

from cairn_contracts.estate import Disposition
from cairn_contracts.finops import PriceListRelease
from cairn_contracts.posture import ControlCatalogueRelease
from cairn_kernel.errors import NotFoundError, UnauthenticatedError, ValidationError
from cairn_kernel.evidence import EvidenceSigner
from cairn_kernel.security import AuditSink, Principal
from cairn_modules.assessment import (
    AssessmentRun,
    AssessmentService,
    Stage,
    build_real_stages,
    coverage_report,
)
from cairn_modules.evidence_service import build_evidence_package
from cairn_modules.finops import TcoAssumptions
from cairn_modules.planning import accept_disposition, amend_disposition, reject_disposition
from cairn_modules.reporting import render_report
from fastapi import BackgroundTasks, Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
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


class ReviewDecisionRequest(BaseModel):
    reason: str | None = None


class AmendDecisionRequest(BaseModel):
    disposition: Disposition
    rationale: str
    confidence: float


def register_assessment_routes(
    app: FastAPI,
    *,
    service: AssessmentService,
    control_catalogue: ControlCatalogueRelease,
    price_list: PriceListRelease,
    audit_sink: AuditSink,
    evidence_signer: EvidenceSigner,
) -> None:
    """Register the R1-15..R1-17 assessment-run routes directly on ``app``.

    Directly on ``app``, not via ``include_router`` -- see
    ``cairn_api.routes_projects.register_projects_routes`` for why.

    ``control_catalogue``/``price_list`` are loaded once by the caller
    (``create_app``), not reloaded from disk on every request.

    Beyond R1-15's own queue/poll routes, this also exposes: R1-06..
    R1-14's stage artifacts for inspection (``/results``), R1-14's
    accept/amend/reject review flow (``/decisions/{id}/...``), R1-16's
    rendered report (``/report``) and R1-17's signed evidence package
    (``/evidence-package``) -- the R1-18 console journey's own read/
    review surface. ``_evidence_chain`` holds, per project, the most
    recently sealed envelope's ``payload_hash`` so a second assessment
    of the same project chains to the first (R1-17's own "subject
    outlives a single run" design) -- in-memory only, the same
    simplification every other store in this app makes until a real
    persistence adapter is wired in.
    """
    router = app
    _evidence_chain: dict[str, str] = {}

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

    def _load_run(project_id: str, run_id: str, principal: Principal) -> AssessmentRun:
        run = service.get_run(run_id)
        _require_same_tenant(run, principal)
        if run.project_id != project_id:
            raise NotFoundError(f"assessment run {run_id} not found in project {project_id}")
        return run

    @router.get("/v1/projects/{project_id}/assessment-runs/{run_id}/results")
    def get_assessment_run_results(
        project_id: str, run_id: str, principal: Principal = Depends(get_principal)
    ) -> dict[str, object]:
        """Every R1-06..R1-14 stage artifact this run has produced so far.

        A stage that has not completed yet (or failed before producing
        output) is simply absent from ``artifacts`` here -- the same
        honesty ``coverage_report``'s ``pending_stages``/``failures``
        already give for the run as a whole, now per-artifact.
        """
        run = _load_run(project_id, run_id, principal)
        return jsonable_encoder(
            {
                "run_id": run.run_id,
                "coverage": coverage_report(run),
                "resources": run.context.artifacts.get("resources"),
                "workloads": run.context.artifacts.get("workloads"),
                "dependencies": run.context.artifacts.get("dependencies"),
                "posture_assessment": run.context.artifacts.get("posture_assessment"),
                "cost_baseline": run.context.artifacts.get("cost_baseline"),
                "tco_result": run.context.artifacts.get("tco_result"),
                "disposition_decisions": run.context.artifacts.get("disposition_decisions"),
            }
        )

    @router.get("/v1/projects/{project_id}/assessment-runs/{run_id}/report")
    def get_assessment_report(
        project_id: str, run_id: str, principal: Principal = Depends(get_principal)
    ) -> dict[str, object]:
        run = _load_run(project_id, run_id, principal)
        return jsonable_encoder(render_report(run))

    def _review(
        project_id: str,
        run_id: str,
        decision_id: str,
        principal: Principal,
        apply: callable,
    ) -> dict[str, object]:
        run = _load_run(project_id, run_id, principal)
        decision = service.get_decision(run_id, decision_id)
        if decision.workload_id not in {
            workload.workload_id for workload in run.context.artifacts.get("workloads", ())
        }:
            raise NotFoundError(f"disposition decision {decision_id} not found on run {run_id}")
        reviewed = apply(decision)
        service.review_decision(run_id, decision_id, reviewed)
        return jsonable_encoder(reviewed)

    @router.post(
        "/v1/projects/{project_id}/assessment-runs/{run_id}/decisions/{decision_id}/accept"
    )
    def accept_decision(
        project_id: str,
        run_id: str,
        decision_id: str,
        principal: Principal = Depends(get_principal),
    ) -> dict[str, object]:
        return _review(
            project_id,
            run_id,
            decision_id,
            principal,
            lambda decision: accept_disposition(
                decision,
                reviewer_actor_id=principal.subject,
                audit_sink=audit_sink,
                decided_at=datetime.now(UTC),
            ),
        )

    @router.post(
        "/v1/projects/{project_id}/assessment-runs/{run_id}/decisions/{decision_id}/reject"
    )
    def reject_decision(
        project_id: str,
        run_id: str,
        decision_id: str,
        payload: ReviewDecisionRequest,
        principal: Principal = Depends(get_principal),
    ) -> dict[str, object]:
        if not payload.reason or not payload.reason.strip():
            raise ValidationError("a reason is required to reject a disposition decision")
        return _review(
            project_id,
            run_id,
            decision_id,
            principal,
            lambda decision: reject_disposition(
                decision,
                reviewer_actor_id=principal.subject,
                audit_sink=audit_sink,
                decided_at=datetime.now(UTC),
                reason=payload.reason,
            ),
        )

    @router.post(
        "/v1/projects/{project_id}/assessment-runs/{run_id}/decisions/{decision_id}/amend"
    )
    def amend_decision(
        project_id: str,
        run_id: str,
        decision_id: str,
        payload: AmendDecisionRequest,
        principal: Principal = Depends(get_principal),
    ) -> dict[str, object]:
        return _review(
            project_id,
            run_id,
            decision_id,
            principal,
            lambda decision: amend_disposition(
                decision,
                reviewer_actor_id=principal.subject,
                audit_sink=audit_sink,
                decided_at=datetime.now(UTC),
                disposition=payload.disposition,
                rationale=payload.rationale,
                confidence=payload.confidence,
            ),
        )

    @router.post("/v1/projects/{project_id}/assessment-runs/{run_id}/evidence-package")
    def build_run_evidence_package(
        project_id: str, run_id: str, principal: Principal = Depends(get_principal)
    ) -> dict[str, object]:
        run = _load_run(project_id, run_id, principal)
        package_id = f"{run.project_id}:{run.run_id}"
        envelope, report = build_evidence_package(
            run,
            package_id=package_id,
            signer=evidence_signer,
            created_at=datetime.now(UTC),
            previous_hash=_evidence_chain.get(run.project_id),
        )
        _evidence_chain[run.project_id] = envelope.payload_hash
        return jsonable_encoder({"envelope": envelope.to_dict(), "report": report})


__all__ = ["get_principal", "register_assessment_routes"]
