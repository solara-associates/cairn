"""Tests for R1-17 signed evidence package for an assessment run.

Covers the acceptance criterion: "Package verifies independently;
tamper detected."

- tamper test: reuses R0-11's exact pattern against this new evidence
  subject type -- a tampered output hash fails `verify_envelope`;
- independent-verification test: a fresh `FakeEvidenceVerifier`, with
  no access to the signer, verifies the package offline;
- chain-head test: multiple evidence packages for the same project
  (the recurring subject) over time, correctly linked and verified as
  one chain.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from cairn_kernel.evidence import EvidenceOutput, verify_chain, verify_envelope
from cairn_kernel.testing import FakeEvidenceSigner, FakeEvidenceVerifier
from cairn_modules.assessment import (
    InMemoryCheckpointStore,
    RunState,
    advance_run,
    build_real_stages,
    queue_run,
)
from cairn_modules.evidence_service import EVIDENCE_SUBJECT_KIND, build_evidence_package
from cairn_modules.finops import BillingLineItem, TcoAssumptions, load_price_list_release
from cairn_modules.posture import load_control_catalogue_release

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


def _run(run_id: str):
    store = InMemoryCheckpointStore()
    queue_run(store, run_id=run_id, tenant_id=TENANT, project_id=PROJECT)
    stage_fns = build_real_stages(
        ingestion_files=[("csv", (INGESTION_FIXTURES / "golden.csv").read_text())],
        billing_items=[_billing_item("row-1")],
        control_catalogue=load_control_catalogue_release(CONTROL_SEED),
        price_list=load_price_list_release(PRICE_LIST_SEED),
        tco_assumptions=TcoAssumptions(horizon_periods=3, growth_rate=0.02, discount_rate=0.1),
        ingest_run_id=run_id,
        cost_currency="GBP",
        scenario_id=run_id,
        clock=lambda: MOMENT,
    )
    return advance_run(store, run_id, stage_fns=stage_fns)


# --- sealing and the R1-16 report hand-off ------------------------------------


def test_build_evidence_package_seals_a_verifiable_package_and_fills_the_report() -> None:
    run = _run("run-1")
    assert run.state is RunState.COMPLETED

    envelope, report = build_evidence_package(
        run, package_id="pkg-1", signer=FakeEvidenceSigner(), created_at=MOMENT
    )

    assert envelope.subject.kind == EVIDENCE_SUBJECT_KIND
    assert envelope.subject.id == PROJECT
    assert envelope.outcome == "PASS"
    assert envelope.versions["control_catalogue"] == "2026.11.1"

    result = verify_envelope(envelope, verifier=FakeEvidenceVerifier())
    assert result.outcome == "PASS"

    assert report.evidence_package_hash == envelope.payload_hash
    assert f"Evidence package hash: {envelope.payload_hash}" in report.rendered_text
    assert "PENDING" not in report.rendered_text


def test_incomplete_run_seals_as_unverified_not_pass() -> None:
    def failing_cost_stage(context):
        raise RuntimeError("simulated failure")

    store = InMemoryCheckpointStore()
    queue_run(store, run_id="run-1", tenant_id=TENANT, project_id=PROJECT)
    stage_fns = build_real_stages(
        ingestion_files=[("csv", (INGESTION_FIXTURES / "golden.csv").read_text())],
        billing_items=[_billing_item("row-1")],
        control_catalogue=load_control_catalogue_release(CONTROL_SEED),
        price_list=load_price_list_release(PRICE_LIST_SEED),
        tco_assumptions=TcoAssumptions(horizon_periods=1, growth_rate=0.0, discount_rate=0.0),
        ingest_run_id="run-1",
        cost_currency="GBP",
        scenario_id="run-1",
    )
    stage_fns["cost"] = failing_cost_stage
    run = advance_run(store, "run-1", stage_fns=stage_fns)
    assert run.state is RunState.CHECKPOINTED

    envelope, _ = build_evidence_package(
        run, package_id="pkg-1", signer=FakeEvidenceSigner(), created_at=MOMENT
    )
    assert envelope.outcome == "UNVERIFIED"


# --- tamper detection, reusing R0-11's exact pattern --------------------------


def test_payload_tamper_is_detected() -> None:
    run = _run("run-1")
    envelope, _ = build_evidence_package(
        run, package_id="pkg-1", signer=FakeEvidenceSigner(), created_at=MOMENT
    )

    tampered = replace(
        envelope, outputs=(EvidenceOutput(kind="assessment_report", ref=run.run_id, hash="0" * 64),)
    )

    result = verify_envelope(tampered, verifier=FakeEvidenceVerifier())
    assert result.outcome == "FAIL"
    assert not result.hash_valid
    assert result.reason == "payload hash does not match the envelope"


def test_signature_tamper_is_detected() -> None:
    run = _run("run-1")
    envelope, _ = build_evidence_package(
        run, package_id="pkg-1", signer=FakeEvidenceSigner(), created_at=MOMENT
    )

    tampered = replace(envelope, signature=replace(envelope.signature, value="not-a-real-signature"))

    result = verify_envelope(tampered, verifier=FakeEvidenceVerifier())
    assert result.outcome == "FAIL"
    assert not result.signature_valid


# --- independent, offline verification ----------------------------------------


def test_package_verifies_independently_offline() -> None:
    """A verifier built with no reference to the signer instance used to
    seal the package -- same key material, independently constructed --
    still verifies it. No network call, no shared in-process object.
    """
    run = _run("run-1")
    envelope, _ = build_evidence_package(
        run, package_id="pkg-1", signer=FakeEvidenceSigner(), created_at=MOMENT
    )

    independent_verifier = FakeEvidenceVerifier()
    result = verify_envelope(envelope, verifier=independent_verifier)

    assert result.valid
    assert result.hash_valid and result.signature_valid and result.chain_valid


# --- chain-head across multiple packages for the same subject over time -----


def test_chain_head_across_multiple_assessment_runs_of_the_same_project() -> None:
    first_run = _run("run-1")
    first_envelope, _ = build_evidence_package(
        first_run, package_id="pkg-1", signer=FakeEvidenceSigner(), created_at=MOMENT
    )

    second_run = _run("run-2")
    second_envelope, _ = build_evidence_package(
        second_run,
        package_id="pkg-2",
        signer=FakeEvidenceSigner(),
        created_at=datetime(2026, 12, 14, 12, 0, 0, tzinfo=UTC),
        previous_hash=first_envelope.payload_hash,
    )

    assert first_envelope.subject == second_envelope.subject
    assert second_envelope.previous_hash == first_envelope.payload_hash

    result = verify_chain(
        [first_envelope, second_envelope],
        verifier=FakeEvidenceVerifier(),
        expected_head_hash=second_envelope.payload_hash,
    )

    assert result.outcome == "PASS"
    assert result.packages_checked == 2
    assert result.latest_hash == second_envelope.payload_hash


def test_chain_detects_a_tampered_member_across_assessment_runs() -> None:
    first_run = _run("run-1")
    first_envelope, _ = build_evidence_package(
        first_run, package_id="pkg-1", signer=FakeEvidenceSigner(), created_at=MOMENT
    )
    second_run = _run("run-2")
    second_envelope, _ = build_evidence_package(
        second_run,
        package_id="pkg-2",
        signer=FakeEvidenceSigner(),
        created_at=datetime(2026, 12, 14, 12, 0, 0, tzinfo=UTC),
        previous_hash=first_envelope.payload_hash,
    )

    tampered_first = replace(
        first_envelope,
        outputs=(EvidenceOutput(kind="assessment_report", ref=first_run.run_id, hash="0" * 64),),
    )

    result = verify_chain([tampered_first, second_envelope], verifier=FakeEvidenceVerifier())
    assert result.outcome == "FAIL"
    assert not result.hash_valid
