"""Tests for R1-14 6R classification and accept/amend/reject flow.

Covers the acceptance criterion: "Rationale and confidence stored;
decisions audited."

- classification test: a workload with an observed grouping fact
  classifies REHOST, one with none classifies RETAIN, both with a
  stored rationale and confidence;
- accept/amend/reject transition test per outcome;
- audit test: every transition is recorded via the R0-10 audit sink
  before it is committed, and an illegal transition is rejected
  without any audit entry or state change.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from cairn_contracts.estate import DecisionStatus, Disposition, FactStatus, FactValue, Workload
from cairn_kernel.errors import InvalidStateTransitionError, ValidationError
from cairn_kernel.testing.fakes import InMemoryAuditSink
from cairn_modules.planning import (
    accept_disposition,
    amend_disposition,
    classify_workload,
    propose_disposition,
    reject_disposition,
)

MOMENT = datetime(2026, 11, 14, 12, 0, 0, tzinfo=UTC)
TENANT = "tenant-1"
PROJECT = "project-1"


def _fact(*, observed: bool) -> FactValue:
    if observed:
        return FactValue(
            value="ClusterA",
            status=FactStatus.OBSERVED,
            source="rvtools",
            observed_at=MOMENT,
            ingested_at=MOMENT,
            confidence=None,
            mapping_version=None,
            provenance_ref="rvtools#0",
        )
    return FactValue(
        value=None,
        status=FactStatus.UNVERIFIED,
        source="",
        observed_at=None,
        ingested_at=MOMENT,
        confidence=None,
        mapping_version=None,
        provenance_ref="",
    )


def _workload(*, observed: bool, workload_id: str = "workload-1") -> Workload:
    return Workload(
        workload_id=workload_id,
        tenant_id=TENANT,
        project_id=PROJECT,
        name="cluster:ClusterA" if observed else "resource:r-1",
        environment="UNVERIFIED",
        owner=None,
        business_context=None,
        resource_ids=("r-1",),
        dependency_ids=(),
        facts={"cluster": _fact(observed=observed)},
        disposition=None,
        disposition_confidence=None,
        model_version="r1-07-grouping-v1",
        mapping_version="r1-07-grouping-v1",
    )


# --- classification -----------------------------------------------------------


def test_workload_with_observed_grouping_fact_classifies_rehost() -> None:
    disposition, rationale, confidence = classify_workload(_workload(observed=True))

    assert disposition is Disposition.REHOST
    assert rationale
    assert 0.0 < confidence <= 1.0


def test_workload_with_no_observed_grouping_fact_classifies_retain() -> None:
    disposition, rationale, confidence = classify_workload(_workload(observed=False))

    assert disposition is Disposition.RETAIN
    assert rationale
    assert 0.0 < confidence <= 1.0


def test_propose_disposition_stores_rationale_and_confidence_as_proposed() -> None:
    decision = propose_disposition(_workload(observed=True), decision_id="decision-1")

    assert decision.status is DecisionStatus.PROPOSED
    assert decision.disposition is Disposition.REHOST
    assert decision.rationale
    assert decision.confidence == 0.4
    assert decision.decided_by is None
    assert decision.decided_at is None


def test_classification_only_uses_the_spec_disposition_enum() -> None:
    for observed in (True, False):
        disposition, _, _ = classify_workload(_workload(observed=observed))
        assert isinstance(disposition, Disposition)


# --- accept/amend/reject transitions ------------------------------------------


def test_accept_moves_to_accepted_and_records_the_reviewer() -> None:
    decision = propose_disposition(_workload(observed=True), decision_id="decision-1")
    sink = InMemoryAuditSink()

    accepted = accept_disposition(
        decision, reviewer_actor_id="reviewer-1", audit_sink=sink, decided_at=MOMENT
    )

    assert accepted.status is DecisionStatus.ACCEPTED
    assert accepted.decided_by == "reviewer-1"
    assert accepted.decided_at == MOMENT
    assert accepted.disposition == decision.disposition


def test_reject_moves_to_rejected_and_requires_a_reason() -> None:
    decision = propose_disposition(_workload(observed=True), decision_id="decision-1")
    sink = InMemoryAuditSink()

    rejected = reject_disposition(
        decision,
        reviewer_actor_id="reviewer-1",
        audit_sink=sink,
        decided_at=MOMENT,
        reason="workload already scheduled for retirement",
    )

    assert rejected.status is DecisionStatus.REJECTED
    assert "rejected: workload already scheduled for retirement" in rejected.rationale

    with pytest.raises(ValidationError, match="reason"):
        reject_disposition(
            decision, reviewer_actor_id="reviewer-1", audit_sink=sink, decided_at=MOMENT, reason=""
        )


def test_amend_moves_to_amended_with_the_reviewers_own_values() -> None:
    decision = propose_disposition(_workload(observed=True), decision_id="decision-1")
    sink = InMemoryAuditSink()

    amended = amend_disposition(
        decision,
        reviewer_actor_id="reviewer-1",
        audit_sink=sink,
        decided_at=MOMENT,
        disposition=Disposition.REPLATFORM,
        rationale="workload actually needs managed-service migration, not lift-and-shift",
        confidence=0.8,
    )

    assert amended.status is DecisionStatus.AMENDED
    assert amended.disposition is Disposition.REPLATFORM
    assert amended.confidence == 0.8
    assert amended.rationale != decision.rationale


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_amend_rejects_an_out_of_range_confidence(confidence: float) -> None:
    decision = propose_disposition(_workload(observed=True), decision_id="decision-1")
    sink = InMemoryAuditSink()

    with pytest.raises(ValidationError, match="confidence"):
        amend_disposition(
            decision,
            reviewer_actor_id="reviewer-1",
            audit_sink=sink,
            decided_at=MOMENT,
            disposition=Disposition.RETIRE,
            rationale="irrelevant",
            confidence=confidence,
        )


# --- audit ---------------------------------------------------------------------


def test_each_transition_appends_exactly_one_audit_entry_before_the_state_changes() -> None:
    decision = propose_disposition(_workload(observed=True), decision_id="decision-1")
    sink = InMemoryAuditSink()

    accept_disposition(decision, reviewer_actor_id="reviewer-1", audit_sink=sink, decided_at=MOMENT)

    assert len(sink.entries) == 1
    entry = sink.entries[0]
    assert entry.action == "planning.disposition.accepted"
    assert entry.actor == "reviewer-1"
    assert entry.payload["decision_id"] == "decision-1"


def test_an_illegal_transition_is_rejected_with_no_audit_entry() -> None:
    decision = propose_disposition(_workload(observed=True), decision_id="decision-1")
    sink = InMemoryAuditSink()
    accepted = accept_disposition(
        decision, reviewer_actor_id="reviewer-1", audit_sink=sink, decided_at=MOMENT
    )
    assert len(sink.entries) == 1

    # ACCEPTED is terminal -- it cannot be accepted again.
    with pytest.raises(InvalidStateTransitionError):
        accept_disposition(
            accepted, reviewer_actor_id="reviewer-1", audit_sink=sink, decided_at=MOMENT
        )

    assert len(sink.entries) == 1
