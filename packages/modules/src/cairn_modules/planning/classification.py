"""R1-14: 6R disposition classification and accept/amend/reject flow.

Classifies each R1-07 ``Workload`` into one of the spec's own 6R
dispositions (``cairn_contracts.estate.Disposition`` --
REHOST/REPLATFORM/REFACTOR/REPURCHASE/RETIRE/RETAIN, ADR-003 -- no
invented category names) with a stored rationale and confidence, then
runs the proposed classification through a human accept/amend/reject
review. Every transition is audited before it is committed (ADR-008
audit-before-effect, ADR-010 Class B workspace mutation).

The classifier itself is a conservative, honestly-labelled default,
not a sophisticated analysis engine: no workload-specific signal
beyond "was any grouping fact actually observed" exists at this
story's dependency boundary (R1-07 only, no posture/cost/dependency
scoring wired in yet). A workload with no observed grouping fact is
RETAIN at low confidence (insufficient detail to recommend action); a
workload with an observed grouping fact is REHOST at modest confidence
(the standard conservative default absent deeper review). Both
rationales say so explicitly, so a reviewer never mistakes this for a
real analysis result.
"""

from __future__ import annotations

from datetime import datetime

from cairn_contracts.estate import (
    DecisionStatus,
    Disposition,
    DispositionDecision,
    FactStatus,
    Workload,
)
from cairn_kernel.errors import InvalidStateTransitionError, ValidationError
from cairn_kernel.hex import OperationClass, ProjectId, TenantId
from cairn_kernel.security import AuditEntry, AuditSink

#: Names this classifier's ruleset, not a trained/fitted model -- see the
#: module docstring. Recorded on every decision's `model_version`/
#: `mapping_version`, which the contract requires as plain strings.
CLASSIFIER_VERSION = "r1-14-conservative-default-v1"

# ADR-008/ADR-010: a proposed decision may be accepted, amended or
# rejected by a human reviewer; every other state is terminal.
ALLOWED_DECISION_TRANSITIONS: dict[DecisionStatus, frozenset[DecisionStatus]] = {
    DecisionStatus.PROPOSED: frozenset(
        {DecisionStatus.ACCEPTED, DecisionStatus.AMENDED, DecisionStatus.REJECTED}
    ),
    DecisionStatus.ACCEPTED: frozenset(),
    DecisionStatus.AMENDED: frozenset(),
    DecisionStatus.REJECTED: frozenset(),
}


def _validate_transition(current: DecisionStatus, target: DecisionStatus) -> None:
    allowed = ALLOWED_DECISION_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidStateTransitionError(
            f"disposition decision cannot move from {current.value} to {target.value}"
        )


def _validate_confidence(confidence: float) -> None:
    if not 0.0 <= confidence <= 1.0:
        raise ValidationError("confidence must be between 0.0 and 1.0")


def _has_observed_grouping_fact(workload: Workload) -> bool:
    return any(fact.status is not FactStatus.UNVERIFIED for fact in workload.facts.values())


def classify_workload(workload: Workload) -> tuple[Disposition, str, float]:
    """The conservative default disposition, rationale and confidence for
    ``workload``. See the module docstring for what this is -- and isn't.
    """
    if _has_observed_grouping_fact(workload):
        rehost_rationale = (
            "Estate detail was observed for this workload (a grouping fact was "
            "actually recorded, not just UNVERIFIED). Defaulting to lift-and-shift "
            "(REHOST) pending workload-specific review -- this is a conservative "
            "default, not a sophisticated analysis."
        )
        return (Disposition.REHOST, rehost_rationale, 0.4)

    retain_rationale = (
        "No estate detail was observed for this workload -- every grouping fact "
        "is UNVERIFIED. Retaining in place rather than recommending a migration "
        "action with insufficient information."
    )
    return (Disposition.RETAIN, retain_rationale, 0.2)


def propose_disposition(workload: Workload, *, decision_id: str) -> DispositionDecision:
    """Propose a 6R disposition for ``workload`` (status PROPOSED, not yet
    reviewed by a human -- ``decided_by``/``decided_at`` are unset).
    """
    disposition, rationale, confidence = classify_workload(workload)
    return DispositionDecision(
        decision_id=decision_id,
        tenant_id=workload.tenant_id,
        project_id=workload.project_id,
        workload_id=workload.workload_id,
        disposition=disposition,
        rationale=rationale,
        confidence=confidence,
        status=DecisionStatus.PROPOSED,
        decided_by=None,
        decided_at=None,
        model_version=CLASSIFIER_VERSION,
        mapping_version=CLASSIFIER_VERSION,
    )


def _audit_transition(
    audit_sink: AuditSink,
    decision: DispositionDecision,
    *,
    action: str,
    reviewer_actor_id: str,
    payload: dict[str, object],
) -> None:
    entry = AuditEntry(
        tenant_id=TenantId(decision.tenant_id),
        project_id=ProjectId(decision.project_id),
        actor=reviewer_actor_id,
        action=action,
        operation_class=OperationClass.WORKSPACE_MUTATION,
        payload=payload,
    )
    # ADR-008 audit-before-effect: appended before the decision below is
    # replaced. A raised AuditUnavailableError propagates and the decision
    # is left unchanged -- the transition fails closed.
    audit_sink.append(entry)


def accept_disposition(
    decision: DispositionDecision,
    *,
    reviewer_actor_id: str,
    audit_sink: AuditSink,
    decided_at: datetime,
) -> DispositionDecision:
    """A human reviewer accepts the decision as proposed, unchanged."""
    if not reviewer_actor_id.strip():
        raise ValidationError("reviewer actor id is required to accept a disposition decision")
    _validate_transition(decision.status, DecisionStatus.ACCEPTED)

    _audit_transition(
        audit_sink,
        decision,
        action="planning.disposition.accepted",
        reviewer_actor_id=reviewer_actor_id,
        payload={
            "decision_id": decision.decision_id,
            "workload_id": decision.workload_id,
            "disposition": decision.disposition.value,
        },
    )
    return decision.model_copy(
        update={"status": DecisionStatus.ACCEPTED, "decided_by": reviewer_actor_id, "decided_at": decided_at}
    )


def reject_disposition(
    decision: DispositionDecision,
    *,
    reviewer_actor_id: str,
    audit_sink: AuditSink,
    decided_at: datetime,
    reason: str,
) -> DispositionDecision:
    """A human reviewer rejects the decision; ``reason`` is required and
    recorded both in the audit entry and on the decision's rationale.
    """
    if not reviewer_actor_id.strip():
        raise ValidationError("reviewer actor id is required to reject a disposition decision")
    if not reason.strip():
        raise ValidationError("a reason is required to reject a disposition decision")
    _validate_transition(decision.status, DecisionStatus.REJECTED)

    _audit_transition(
        audit_sink,
        decision,
        action="planning.disposition.rejected",
        reviewer_actor_id=reviewer_actor_id,
        payload={
            "decision_id": decision.decision_id,
            "workload_id": decision.workload_id,
            "reason": reason,
        },
    )
    return decision.model_copy(
        update={
            "status": DecisionStatus.REJECTED,
            "decided_by": reviewer_actor_id,
            "decided_at": decided_at,
            "rationale": f"{decision.rationale} | rejected: {reason}",
        }
    )


def amend_disposition(
    decision: DispositionDecision,
    *,
    reviewer_actor_id: str,
    audit_sink: AuditSink,
    decided_at: datetime,
    disposition: Disposition,
    rationale: str,
    confidence: float,
) -> DispositionDecision:
    """A human reviewer amends the decision to a different disposition,
    with their own rationale and confidence -- the proposed values are
    replaced, not merged with the reviewer's.
    """
    if not reviewer_actor_id.strip():
        raise ValidationError("reviewer actor id is required to amend a disposition decision")
    if not rationale.strip():
        raise ValidationError("a rationale is required to amend a disposition decision")
    _validate_confidence(confidence)
    _validate_transition(decision.status, DecisionStatus.AMENDED)

    _audit_transition(
        audit_sink,
        decision,
        action="planning.disposition.amended",
        reviewer_actor_id=reviewer_actor_id,
        payload={
            "decision_id": decision.decision_id,
            "workload_id": decision.workload_id,
            "previous_disposition": decision.disposition.value,
            "disposition": disposition.value,
        },
    )
    return decision.model_copy(
        update={
            "status": DecisionStatus.AMENDED,
            "decided_by": reviewer_actor_id,
            "decided_at": decided_at,
            "disposition": disposition,
            "rationale": rationale,
            "confidence": confidence,
        }
    )


__all__ = [
    "ALLOWED_DECISION_TRANSITIONS",
    "CLASSIFIER_VERSION",
    "accept_disposition",
    "amend_disposition",
    "classify_workload",
    "propose_disposition",
    "reject_disposition",
]
