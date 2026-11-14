"""R1-19 (full): cross-tenant and resilience tests for the R1-15
assessment orchestrator, beyond each story's own isolated test.

Scope, per the R1-19 brief: confirm the context-change protection R0's
tenancy kernel already proves synchronously (session s649,
``R-TENANT-03``) still holds through R1-15's async operation layer --
not re-litigating R-TENANT-03 itself, but proving the one new
concurrency surface R1-15 introduced (two tenants' runs advancing
through ``AssessmentService`` at the same time) never lets one
tenant's data reach another's. No component in this pipeline opens a
Postgres session (every R1-15 store is in-memory), so there is no RLS
boundary to attack here the way R-TENANT-03 attacks one at the DB
layer; what *is* real is whether ``AssessmentService``'s own in-memory
stores leak between two concurrently-advancing runs for different
tenants -- proven below by actually running them concurrently, not by
assuming the single-threaded case generalises.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path

from cairn_contracts.posture import ControlCatalogueRelease
from cairn_kernel.outbox import InMemoryOutboxStore
from cairn_modules.assessment import AssessmentService, InMemoryCheckpointStore, RunState
from cairn_modules.assessment.stages import build_real_stages
from cairn_modules.finops import TcoAssumptions, load_price_list_release
from cairn_modules.posture import load_control_catalogue_release

REPO_ROOT = Path(__file__).resolve().parents[3]
INGESTION_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "ingestion"
CONTROL_SEED = REPO_ROOT / "controls" / "gcp-cis-seed.yaml"
PRICE_LIST_SEED = REPO_ROOT / "pricing" / "gcp-price-list-seed.yaml"

MOMENT = datetime(2026, 11, 14, 12, 0, 0, tzinfo=UTC)

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
PROJECT_A = "project-a"
PROJECT_B = "project-b"

# Distinct, recognisable hostnames per tenant so a leaked workload is
# detectable by name, not just by count.
CSV_A = "hostname,ip_address,role\ntenant-a-web-01,10.0.1.10,web\n"
CSV_B = "hostname,ip_address,role\ntenant-b-db-01,10.0.2.20,db\n"


def _control_catalogue() -> ControlCatalogueRelease:
    return load_control_catalogue_release(CONTROL_SEED)


def _stage_fns(csv_content: str, *, run_id: str) -> dict:
    return build_real_stages(
        ingestion_files=[("csv", csv_content)],
        billing_items=[],
        control_catalogue=_control_catalogue(),
        price_list=load_price_list_release(PRICE_LIST_SEED),
        tco_assumptions=TcoAssumptions(horizon_periods=1, growth_rate=0.0, discount_rate=0.0),
        ingest_run_id=run_id,
        cost_currency="GBP",
        scenario_id=run_id,
        clock=lambda: MOMENT,
    )


def test_two_tenants_runs_advancing_concurrently_never_cross_contaminate() -> None:
    """The real concurrency risk R1-15's async operation API introduces:
    two different tenants' ``BackgroundTasks`` could, in a real
    deployment, run genuinely concurrently in the same process. Proven
    here with real OS threads (not just two sequential calls), with a
    ``Barrier`` forcing both to start their stage work in the same
    instant -- the strongest adversarial ordering a single-process
    deployment can produce.
    """
    service = AssessmentService(checkpoint_store=InMemoryCheckpointStore(), outbox=InMemoryOutboxStore())
    service.queue_run(run_id="run-a", tenant_id=TENANT_A, project_id=PROJECT_A)
    service.queue_run(run_id="run-b", tenant_id=TENANT_B, project_id=PROJECT_B)

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    errors: list[BaseException] = []

    def _advance(run_id: str, csv_content: str) -> None:
        try:
            barrier.wait(timeout=5)
            results[run_id] = service.advance_run(run_id, stage_fns=_stage_fns(csv_content, run_id=run_id))
        except BaseException as exc:  # noqa: BLE001 - surfaced to the main thread below
            errors.append(exc)

    thread_a = threading.Thread(target=_advance, args=("run-a", CSV_A))
    thread_b = threading.Thread(target=_advance, args=("run-b", CSV_B))
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=10)
    thread_b.join(timeout=10)

    assert not errors, f"concurrent advance_run raised: {errors}"
    run_a = results["run-a"]
    run_b = results["run-b"]
    assert run_a.state is RunState.COMPLETED
    assert run_b.state is RunState.COMPLETED

    # Each run's own tenant/project identity is exactly what it was queued with.
    assert run_a.tenant_id == TENANT_A and run_a.project_id == PROJECT_A
    assert run_b.tenant_id == TENANT_B and run_b.project_id == PROJECT_B

    # Every workload/resource/decision belongs to its own run's tenant and
    # project -- never the other one's, and never the other tenant's host.
    for run, tenant_id, project_id, other_hostname in (
        (run_a, TENANT_A, PROJECT_A, "tenant-b-db-01"),
        (run_b, TENANT_B, PROJECT_B, "tenant-a-web-01"),
    ):
        workloads = run.context.artifacts["workloads"]
        resources = run.context.artifacts["resources"]
        decisions = run.context.artifacts["disposition_decisions"]
        assert workloads and resources and decisions
        for workload in workloads:
            assert workload.tenant_id == tenant_id
            assert workload.project_id == project_id
            assert other_hostname not in workload.name
        for resource in resources:
            assert resource.tenant_id == tenant_id
            assert resource.project_id == project_id
        for decision in decisions:
            assert decision.tenant_id == tenant_id
            assert decision.project_id == project_id

    # Loading each run back by id returns exactly that run, never the
    # other -- the checkpoint store itself never mixed the two up.
    assert service.get_run("run-a").tenant_id == TENANT_A
    assert service.get_run("run-b").tenant_id == TENANT_B


def test_disposition_decisions_and_evidence_package_agree_on_tenant_and_project_end_to_end() -> None:
    """Resilience across stories, not just one story's own isolated test:
    a single run's R1-14 decisions and R1-17 evidence package must agree
    on tenant/project identity with the run itself and with R1-06's
    resources/workloads that produced them, all the way through.
    """
    from cairn_kernel.evidence.signing import FAKE_ALGORITHM
    from cairn_modules.evidence_service import build_evidence_package

    class _FakeSigner:
        key_id = "test-key-1"
        algorithm = FAKE_ALGORITHM

        def sign(self, payload: bytes) -> bytes:
            import hashlib

            return hashlib.sha256(payload).digest()

    service = AssessmentService(checkpoint_store=InMemoryCheckpointStore(), outbox=InMemoryOutboxStore())
    service.queue_run(run_id="run-full-chain", tenant_id=TENANT_A, project_id=PROJECT_A)
    run = service.advance_run("run-full-chain", stage_fns=_stage_fns(CSV_A, run_id="run-full-chain"))

    assert run.state is RunState.COMPLETED
    workloads = run.context.artifacts["workloads"]
    decisions = run.context.artifacts["disposition_decisions"]
    assert {w.workload_id for w in workloads} == {d.workload_id for d in decisions}
    assert all(d.tenant_id == run.tenant_id and d.project_id == run.project_id for d in decisions)

    envelope, report = build_evidence_package(
        run, package_id="pkg-1", signer=_FakeSigner(), created_at=MOMENT
    )
    assert envelope.tenant_id == run.tenant_id
    assert envelope.project_id == run.project_id
    assert envelope.subject.id == run.project_id
    assert report.evidence_package_hash == envelope.payload_hash
    assert report.tenant_id == run.tenant_id and report.project_id == run.project_id
