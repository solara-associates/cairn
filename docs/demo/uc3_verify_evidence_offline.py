"""Demo pack companion script for use case 3 (migration assessment).

Runs the real R1 assessment pipeline (ingestion -> estate normalization ->
posture -> cost/TCO -> 6R) against the same golden RVTools/HVTools fixtures
the console demo uses, seals a signed evidence package, then verifies it
*offline* -- no network call, no server process -- using an independent
verifier object that never touches the signer.

This is the same `cairn_kernel.evidence.verify_envelope` function that
governs every evidence package CAIRN produces; nothing here is a stub or a
simplified reimplementation of the real verification path.

Honest limit, stated here because the demo pack says to state it plainly:
the signer/verifier pair below (`FakeEvidenceSigner`/`FakeEvidenceVerifier`)
share a fixed, publicly-known demo key. That is the right choice for this
script: it proves the *verification logic* is real, in a process that
never saw the signer run. It is not the same key the API uses when you
run `docker compose up` -- that default setup signs with
`_LocalEvidenceSigner` (apps/api/src/cairn_api/app.py), a random
process-local HMAC key that is never exported by any route and does not
survive a restart. So the console's own evidence screen cannot be
independently verified by a second, separate process out of the box --
only a real GCP KMS-backed signer (CAIRN_KMS_* env vars, unconfigured in
this cloud-free demo) makes that possible. Say this on screen, don't
imply the console's "Export signed evidence package" button alone proves
offline verification.

Run: uv run python docs/demo/uc3_verify_evidence_offline.py
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cairn_kernel.evidence import verify_envelope
from cairn_kernel.testing.fakes import FakeEvidenceSigner, FakeEvidenceVerifier
from cairn_modules.assessment import (
    InMemoryCheckpointStore,
    RunState,
    advance_run,
    build_real_stages,
    queue_run,
)
from cairn_modules.evidence_service import build_evidence_package
from cairn_modules.finops import BillingLineItem, TcoAssumptions, load_price_list_release
from cairn_modules.posture import load_control_catalogue_release

REPO_ROOT = Path(__file__).resolve().parents[2]
INGESTION_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "ingestion"
CONTROL_SEED = REPO_ROOT / "controls" / "gcp-cis-seed.yaml"
PRICE_LIST_SEED = REPO_ROOT / "pricing" / "gcp-price-list-seed.yaml"

MOMENT = datetime(2026, 11, 20, 12, 0, 0, tzinfo=UTC)
TENANT = "demo-tenant"
PROJECT = "uc3-migration-assessment-demo"


def _billing_item(source_id: str) -> BillingLineItem:
    return BillingLineItem(
        source_id=source_id,
        provider="gcp",
        tenant_id=TENANT,
        project_id=PROJECT,
        account_id="demo-billing-acct",
        service="Compute Engine",
        region="europe-west2",
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 1, 1, tzinfo=UTC),
        currency="GBP",
        amount_minor=250_000,
        tags={"env": "prod"},
        raw_ref=f"gcp://acct/billing/{source_id}",
    )


def main() -> None:
    run_id = "uc3-demo-run-1"
    store = InMemoryCheckpointStore()
    queue_run(store, run_id=run_id, tenant_id=TENANT, project_id=PROJECT)

    stage_fns = build_real_stages(
        ingestion_files=[
            ("rvtools", (INGESTION_FIXTURES / "golden.rvtools.csv").read_text()),
            ("hvtools", (INGESTION_FIXTURES / "golden.hvtools.csv").read_text()),
        ],
        billing_items=[_billing_item("row-1"), _billing_item("row-2")],
        control_catalogue=load_control_catalogue_release(CONTROL_SEED),
        price_list=load_price_list_release(PRICE_LIST_SEED),
        tco_assumptions=TcoAssumptions(horizon_periods=3, growth_rate=0.02, discount_rate=0.1),
        ingest_run_id=run_id,
        cost_currency="GBP",
        scenario_id=run_id,
        clock=lambda: MOMENT,
    )
    run = advance_run(store, run_id, stage_fns=stage_fns)
    assert run.state is RunState.COMPLETED, f"run did not complete: {run.state}"
    print(
        f"assessment run completed: {len(run.context.artifacts.get('workloads', ()))} workload(s) derived"
    )

    signer = FakeEvidenceSigner()
    envelope, report = build_evidence_package(
        run, package_id="uc3-demo-pkg-1", signer=signer, created_at=MOMENT
    )
    print(f"evidence package sealed: {envelope.package_id}")
    print(f"  payload hash:  {envelope.payload_hash}")
    print(f"  signed with:   {envelope.signature.key_id} ({envelope.signature.algorithm})")
    print(f"  previous hash: {envelope.previous_hash or 'none -- first package for this project'}")

    # Independent verifier: a fresh object, never shares the `signer`
    # instance above -- this is the "no access to the signer" check the
    # demo-readiness gate's evidence step requires.
    verifier = FakeEvidenceVerifier()
    result = verify_envelope(envelope, verifier=verifier, expected_previous_hash=None)
    print(f"offline verification: {result.outcome}")
    assert result.valid, f"verification failed: {result.reason}"
    print(f"  report excerpt: {report.rendered_text.splitlines()[0]!r}")


if __name__ == "__main__":
    main()
