"""Tests for R1-16 assessment report renderer.

Covers the acceptance criterion: "Report includes coverage,
assumptions, versions."

- rendering test against a fixture run: coverage, assumptions and
  versions all appear, both as structured fields and in the rendered
  text;
- incomplete-run test: a run that stopped partway through renders the
  gap visibly (explicit UNVERIFIED/empty, never a crash or a silently
  dropped section).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cairn_modules.assessment import (
    InMemoryCheckpointStore,
    RunState,
    advance_run,
    build_real_stages,
    queue_run,
)
from cairn_modules.finops import BillingLineItem, TcoAssumptions, load_price_list_release
from cairn_modules.posture import load_control_catalogue_release
from cairn_modules.reporting import render_report

REPO_ROOT = Path(__file__).resolve().parents[3]
INGESTION_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "ingestion"
CONTROL_SEED = REPO_ROOT / "controls" / "gcp-cis-seed.yaml"
PRICE_LIST_SEED = REPO_ROOT / "pricing" / "gcp-price-list-seed.yaml"

MOMENT = datetime(2026, 11, 14, 12, 0, 0, tzinfo=UTC)
TENANT = "tenant-1"
PROJECT = "project-1"


def _billing_item(source_id: str) -> BillingLineItem:
    return BillingLineItem(
        source_id=source_id,
        provider="gcp",
        tenant_id=TENANT,
        project_id=PROJECT,
        account_id="gcp-billing-acct-1",
        service="Compute Engine",
        region="europe-west2",
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 1, 1, tzinfo=UTC),
        currency="GBP",
        amount_minor=100_000,
        tags={"env": "prod"},
        raw_ref=f"gcp://acct/billing/{source_id}",
    )


def _build_stage_fns():
    return build_real_stages(
        ingestion_files=[("csv", (INGESTION_FIXTURES / "golden.csv").read_text())],
        billing_items=[_billing_item("row-1")],
        control_catalogue=load_control_catalogue_release(CONTROL_SEED),
        price_list=load_price_list_release(PRICE_LIST_SEED),
        tco_assumptions=TcoAssumptions(horizon_periods=3, growth_rate=0.02, discount_rate=0.1),
        ingest_run_id="run-1",
        cost_currency="GBP",
        scenario_id="scenario-1",
        clock=lambda: MOMENT,
    )


def _completed_run():
    store = InMemoryCheckpointStore()
    queue_run(store, run_id="run-1", tenant_id=TENANT, project_id=PROJECT)
    return advance_run(store, "run-1", stage_fns=_build_stage_fns())


# --- a completed run's report includes coverage, assumptions, versions ------


def test_report_includes_coverage_assumptions_and_versions() -> None:
    run = _completed_run()
    assert run.state is RunState.COMPLETED

    report = render_report(run)

    # Coverage
    assert report.run_coverage.state == "COMPLETED"
    assert report.run_coverage.coverage == 1.0
    assert report.posture_coverage.total_controls == 7
    assert report.cost_coverage.total_amount_minor == 100_000

    # Assumptions, explicit
    assert report.tco_assumptions.horizon_periods == 3
    assert report.tco_assumptions.growth_rate == 0.02
    assert report.tco_assumptions.discount_rate == 0.1

    # Versions
    assert report.versions.control_catalogue_version == "2026.11.1"
    assert report.versions.price_list_version == "2026.11.1"
    assert report.versions.parser_versions == ("csv-adapter-1.0.0",)
    assert report.versions.workload_derivation_version
    assert report.versions.classification_version

    # ADR-008 placeholder, not yet filled in
    assert report.evidence_package_hash is None

    text = report.rendered_text
    assert "Stages completed: 100%" in text
    assert "Growth rate: 0.02" in text
    assert "Control catalogue: 2026.11.1" in text
    assert "Price list: 2026.11.1" in text
    assert "PENDING -- R1-17 fills this in" in text


def test_mapping_release_version_is_honestly_not_recorded() -> None:
    """R1-15's pipeline never uses the R0-14 mapping registry -- the
    report must say so plainly, not fabricate a version.
    """
    run = _completed_run()
    report = render_report(run)

    assert report.versions.mapping_release_version is None
    assert "not recorded -- this pipeline does not use the mapping registry" in report.rendered_text


# --- an incomplete run renders its coverage gap visibly -----------------------


def test_incomplete_run_renders_the_gap_visibly_not_a_crash() -> None:
    def failing_cost_stage(context):
        raise RuntimeError("simulated failure")

    stage_fns = _build_stage_fns()
    stage_fns["cost"] = failing_cost_stage

    store = InMemoryCheckpointStore()
    queue_run(store, run_id="run-1", tenant_id=TENANT, project_id=PROJECT)
    run = advance_run(store, "run-1", stage_fns=stage_fns)

    assert run.state is RunState.CHECKPOINTED
    assert "cost" in run.pending_stages

    report = render_report(run)

    # What ran (ingestion, estate, posture) is present.
    assert report.posture_coverage.total_controls == 7
    # What didn't (cost, tco, classification) is explicit, not fabricated.
    assert report.cost_coverage.total_amount_minor is None
    assert report.tco_assumptions.horizon_periods is None
    assert report.versions.price_list_version is None

    text = report.rendered_text
    assert "UNVERIFIED -- stage did not run" in text
    assert "Pending stages: cost, tco, classification" in text
    assert "simulated failure" in text
