"""R1-15: the worker's assessment-run advancement hook is real wiring,
not a stub -- it drives a genuine ``AssessmentService`` through a real
``OutboxStore``.
"""

from __future__ import annotations

from pathlib import Path

from cairn_kernel.outbox import InMemoryOutboxStore
from cairn_modules.assessment import InMemoryCheckpointStore, RunState, build_real_stages, queue_run
from cairn_modules.finops import TcoAssumptions, load_price_list_release
from cairn_modules.posture import load_control_catalogue_release
from cairn_worker import advance_assessment_run

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_advance_assessment_run_drives_a_real_run_to_completion() -> None:
    checkpoint_store = InMemoryCheckpointStore()
    outbox = InMemoryOutboxStore()
    queue_run(checkpoint_store, run_id="run-1", tenant_id="tenant-1", project_id="project-1")

    stage_fns = build_real_stages(
        ingestion_files=[],
        billing_items=[],
        control_catalogue=load_control_catalogue_release(REPO_ROOT / "controls" / "gcp-cis-seed.yaml"),
        price_list=load_price_list_release(REPO_ROOT / "pricing" / "gcp-price-list-seed.yaml"),
        tco_assumptions=TcoAssumptions(horizon_periods=1, growth_rate=0.0, discount_rate=0.0),
        ingest_run_id="worker-run-1",
        cost_currency="GBP",
        scenario_id="scenario-1",
    )

    run = advance_assessment_run(
        checkpoint_store=checkpoint_store, outbox=outbox, run_id="run-1", stage_fns=stage_fns
    )

    assert run.state is RunState.COMPLETED
    assert len(outbox.claim_pending(limit=1000)) > 0
