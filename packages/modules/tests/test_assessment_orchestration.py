"""Tests for R1-15 assessment orchestration and async operation API.

Covers the acceptance criterion: "End-to-end run completes; failures
resumable."

- end-to-end test: a full run against real fixtures from every stage
  (R1-04 ingestion through R1-14 classification) completes;
- resume-after-failure test: a stage injected to fail once, at every
  stage boundary, leaves the run resumable at exactly that stage, and
  a second ``advance_run`` call completes it;
- outbox-flow test: stage-transition events actually flow through the
  real R1-23 ``OutboxStore``/``OutboxDispatcher``, not a bypass that
  calls an ``EventPublisher`` directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cairn_contracts.posture import ControlCatalogueRelease
from cairn_kernel.errors import InvalidStateTransitionError
from cairn_kernel.outbox import InMemoryOutboxStore, OutboxDispatcher, OutboxPublishError
from cairn_kernel.testing.fakes import FixedClock, InMemoryAuditSink
from cairn_modules.assessment import (
    STAGES,
    AssessmentService,
    InMemoryCheckpointStore,
    RunState,
    advance_run,
    build_real_stages,
    queue_run,
)
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


def _control_catalogue() -> ControlCatalogueRelease:
    return load_control_catalogue_release(CONTROL_SEED)


def _build_stage_fns() -> dict:
    return build_real_stages(
        ingestion_files=[("csv", (INGESTION_FIXTURES / "golden.csv").read_text())],
        billing_items=[_billing_item("row-1"), _billing_item("row-2")],
        control_catalogue=_control_catalogue(),
        price_list=load_price_list_release(PRICE_LIST_SEED),
        tco_assumptions=TcoAssumptions(horizon_periods=3, growth_rate=0.02, discount_rate=0.1),
        ingest_run_id="assessment-run-1",
        cost_currency="GBP",
        scenario_id="scenario-1",
        clock=lambda: MOMENT,
    )


# --- end-to-end ----------------------------------------------------------------


def test_end_to_end_run_against_real_fixtures_from_every_stage_completes() -> None:
    store = InMemoryCheckpointStore()
    queue_run(store, run_id="run-1", tenant_id=TENANT, project_id=PROJECT)

    run = advance_run(store, "run-1", stage_fns=_build_stage_fns())

    assert run.state is RunState.COMPLETED
    assert run.completed_stages == STAGES
    assert run.coverage == 1.0
    assert not run.failed_outcomes

    assert len(run.context.artifacts["resources"]) == 2  # golden.csv: web-01, db-01
    assert len(run.context.artifacts["workloads"]) >= 1
    assert run.context.artifacts["posture_assessment"].release_version == _control_catalogue().version
    assert run.context.artifacts["cost_baseline"].total_amount_minor == 200_000
    assert run.context.artifacts["tco_result"].price_list_version == "2026.11.1"
    assert len(run.context.artifacts["disposition_decisions"]) == len(run.context.artifacts["workloads"])


# --- resume after failure, at every stage boundary -----------------------------


@dataclass
class _FailOnceGuard:
    """Makes one stage raise exactly once, then delegate to the real stage."""

    real_stages: dict
    stage_to_fail: str
    calls: list[str] = field(default_factory=list)

    def wrap(self) -> dict:
        wrapped = dict(self.real_stages)
        real = wrapped[self.stage_to_fail]

        def failing_once(context):
            self.calls.append(self.stage_to_fail)
            if len(self.calls) == 1:
                raise RuntimeError(f"simulated failure at stage {self.stage_to_fail}")
            return real(context)

        wrapped[self.stage_to_fail] = failing_once
        return wrapped


@pytest.mark.parametrize("stage_to_fail", STAGES)
def test_run_resumes_from_exactly_the_failed_stage(stage_to_fail: str) -> None:
    store = InMemoryCheckpointStore()
    queue_run(store, run_id="run-1", tenant_id=TENANT, project_id=PROJECT)
    guard = _FailOnceGuard(real_stages=_build_stage_fns(), stage_to_fail=stage_to_fail)

    failed_run = advance_run(store, "run-1", stage_fns=guard.wrap())

    assert failed_run.state is RunState.CHECKPOINTED
    assert stage_to_fail not in failed_run.completed_stages
    assert stage_to_fail in failed_run.pending_stages
    assert failed_run.failed_outcomes[-1].stage == stage_to_fail

    resumed_run = advance_run(store, "run-1", stage_fns=guard.wrap())

    assert resumed_run.state is RunState.COMPLETED
    assert resumed_run.completed_stages == STAGES
    # The failed stage was retried exactly once more, not skipped.
    assert guard.calls.count(stage_to_fail) == 2


def test_a_completed_run_is_not_resumable() -> None:
    store = InMemoryCheckpointStore()
    queue_run(store, run_id="run-1", tenant_id=TENANT, project_id=PROJECT)
    advance_run(store, "run-1", stage_fns=_build_stage_fns())

    with pytest.raises(InvalidStateTransitionError):
        advance_run(store, "run-1", stage_fns=_build_stage_fns())


# --- outbox: real dispatcher, not a bypass -------------------------------------


@dataclass
class _RecordingPublisher:
    published: list = field(default_factory=list)
    fail_next: bool = False

    def publish(self, message) -> None:
        if self.fail_next:
            self.fail_next = False
            raise OutboxPublishError("simulated transport failure")
        self.published.append(message)


def test_stage_transition_events_flow_through_the_real_outbox_dispatcher() -> None:
    outbox = InMemoryOutboxStore()
    publisher = _RecordingPublisher()
    audit = InMemoryAuditSink()
    dispatcher = OutboxDispatcher(
        store=outbox, publisher=publisher, audit_sink=audit, clock=FixedClock(MOMENT)
    )

    service = AssessmentService(
        checkpoint_store=InMemoryCheckpointStore(), outbox=outbox, clock=lambda: MOMENT
    )
    service.queue_run(run_id="run-1", tenant_id=TENANT, project_id=PROJECT)
    run = service.advance_run("run-1", stage_fns=_build_stage_fns())
    assert run.state is RunState.COMPLETED

    # Nothing has been delivered to the publisher yet -- enqueue and
    # dispatch are separate steps, exactly like R1-23's own model.
    assert publisher.published == []
    assert len(outbox.claim_pending(limit=1000)) > 0

    report = dispatcher.dispatch_pending()

    assert report.dead_lettered == []
    assert len(publisher.published) == len(report.dispatched)
    assert outbox.claim_pending(limit=1000) == []  # every message now dispatched

    event_types = {message.event_type for message in publisher.published}
    assert "assessment.run.running" in event_types
    assert "assessment.run.completed" in event_types
    assert all(message.tenant_id == TENANT for message in publisher.published)
    assert all(message.project_id == PROJECT for message in publisher.published)
