"""The LLMOps observe/decide/act cost control loop (R5-02b, 815).

Closes the loop 814's ``ModelGateway`` opened: every call it makes is now
logged with a real ``cost_micro_usd`` (``cairn_kernel.model.cost``,
populated through the existing ``AiCallRecord``/``AiCallLogger`` path, no
new logging mechanism). This module is the "decide" and "act" half --
given a window of recently logged ``AiCallRecord``s and a configured cost
budget, it decides ``CONTINUE``/``THROTTLE``/``STOP``, and a ``THROTTLE``/
``STOP`` decision is fed back into 814's own ``RateLimiter``/
``CircuitBreaker`` state (``RateLimiter.exhaust``/``CircuitBreaker.
force_open``, both added by this unit) rather than inventing a third
blocking mechanism.

**Judgement call (control-loop decision shape):** the loop takes a plain
``Sequence[AiCallRecord]`` -- "a window of recent records" -- rather than
holding its own running counter or doing time-window filtering itself.
Windowing (which records count as "recent") is the caller's own choice
(e.g. the records a tenant's calls produced since the last evaluation, or
a time-bounded slice of a durable log) and is kept out of this module so
it stays a pure function of whatever records it is handed -- simple to
test, and reusable by any caller regardless of how it retains call
history.

Every ``THROTTLE``/``STOP`` decision is itself evidenced through
``cairn_kernel.evidence.seal_evidence`` -- the exact mechanism every other
governed decision in this codebase already uses, not a new one.
``CONTINUE`` is not sealed: it is the absence of a governed intervention,
not a decision that needs independent proof.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from cairn_kernel.errors import ValidationError
from cairn_kernel.evidence import (
    EvidenceEnvelope,
    EvidenceSigner,
    EvidenceSubject,
    ProvenanceRecord,
    seal_evidence,
)
from cairn_kernel.model.policy import CircuitBreaker, RateLimiter
from cairn_kernel.observability.ai import AiCallRecord

EVIDENCE_SUBJECT_KIND = "model_cost_control_decision"
PRODUCER = {"name": "cairn-model-cost-control-loop", "version": "r5-02b-v1"}


class CostControlDecision(str, Enum):
    CONTINUE = "CONTINUE"
    THROTTLE = "THROTTLE"
    STOP = "STOP"


@dataclass(frozen=True, slots=True)
class CostControlBudget:
    """A configured cost threshold pair for one evaluation window.

    Crossing ``throttle_threshold_micro_usd`` (but not
    ``stop_threshold_micro_usd``) decides ``THROTTLE``; crossing
    ``stop_threshold_micro_usd`` decides ``STOP`` -- it is always the more
    severe decision, ``STOP`` is never skipped in favour of ``THROTTLE``.
    """

    throttle_threshold_micro_usd: int
    stop_threshold_micro_usd: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.throttle_threshold_micro_usd, int)
            or isinstance(self.throttle_threshold_micro_usd, bool)
            or self.throttle_threshold_micro_usd <= 0
        ):
            raise ValidationError("throttle_threshold_micro_usd must be a positive integer")
        if (
            not isinstance(self.stop_threshold_micro_usd, int)
            or isinstance(self.stop_threshold_micro_usd, bool)
            or self.stop_threshold_micro_usd <= 0
        ):
            raise ValidationError("stop_threshold_micro_usd must be a positive integer")
        if self.stop_threshold_micro_usd < self.throttle_threshold_micro_usd:
            raise ValidationError(
                "stop_threshold_micro_usd must be >= throttle_threshold_micro_usd"
            )


@dataclass(frozen=True, slots=True)
class CostControlEvaluation:
    """The "observe/decide" half's result: what was decided, and the
    figures that justify it (also what gets sealed into evidence)."""

    decision: CostControlDecision
    total_cost_micro_usd: int
    call_count: int
    budget: CostControlBudget


def evaluate_cost_window(
    records: Sequence[AiCallRecord], budget: CostControlBudget
) -> CostControlEvaluation:
    """Pure "observe/decide": sum ``cost_micro_usd`` across ``records`` and
    compare to ``budget``. Holds no state and reaches no policy object --
    safe to call as often as a caller likes, including from a test with a
    synthetic record list it built itself."""

    total = sum(record.cost_micro_usd for record in records)
    if total >= budget.stop_threshold_micro_usd:
        decision = CostControlDecision.STOP
    elif total >= budget.throttle_threshold_micro_usd:
        decision = CostControlDecision.THROTTLE
    else:
        decision = CostControlDecision.CONTINUE
    return CostControlEvaluation(
        decision=decision,
        total_cost_micro_usd=total,
        call_count=len(records),
        budget=budget,
    )


def _policy_decision_dict(
    evaluation: CostControlEvaluation, *, tenant_id: str
) -> dict[str, object]:
    return {
        "kind": "model_cost_control",
        "decision": evaluation.decision.value,
        "tenant_id": tenant_id,
        "total_cost_micro_usd": evaluation.total_cost_micro_usd,
        "call_count": evaluation.call_count,
        "throttle_threshold_micro_usd": evaluation.budget.throttle_threshold_micro_usd,
        "stop_threshold_micro_usd": evaluation.budget.stop_threshold_micro_usd,
    }


@dataclass
class CostControlLoop:
    """The full observe/decide/act loop: evaluates a cost window, feeds a
    ``THROTTLE``/``STOP`` decision back into 814's existing
    ``RateLimiter``/``CircuitBreaker`` state, and seals that decision as
    evidence.
    """

    budget: CostControlBudget
    signer: EvidenceSigner
    producer: Mapping[str, str] = field(default_factory=lambda: dict(PRODUCER))

    def evaluate(self, records: Sequence[AiCallRecord]) -> CostControlEvaluation:
        return evaluate_cost_window(records, self.budget)

    def run(
        self,
        records: Sequence[AiCallRecord],
        *,
        tenant_id: str,
        project_id: str,
        now: datetime,
        package_id: str,
        rate_limiter: RateLimiter | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        previous_hash: str | None = None,
    ) -> tuple[CostControlEvaluation, EvidenceEnvelope | None]:
        """Run one full loop iteration: decide, act on 814's policy
        objects, and (for ``THROTTLE``/``STOP`` only) seal evidence.

        Acting happens before sealing, so the evidence envelope's own
        ``created_at``/contents describe a decision that has already been
        applied -- never a decision recorded but not enforced.
        """

        evaluation = self.evaluate(records)

        if evaluation.decision is CostControlDecision.THROTTLE and rate_limiter is not None:
            rate_limiter.exhaust(tenant_id, now=now)
        elif evaluation.decision is CostControlDecision.STOP and circuit_breaker is not None:
            circuit_breaker.force_open(now=now)

        if evaluation.decision is CostControlDecision.CONTINUE:
            return evaluation, None

        envelope = seal_evidence(
            signer=self.signer,
            package_id=package_id,
            tenant_id=tenant_id,
            project_id=project_id,
            subject=EvidenceSubject(kind=EVIDENCE_SUBJECT_KIND, id=package_id),
            created_at=now,
            producer=self.producer,
            provenance=tuple(
                ProvenanceRecord(
                    fact_ref=f"ai_call:{record.correlation_id}",
                    source="cairn-model-cost-control-loop",
                    observed_at=record.created_at,
                )
                for record in records
            ),
            policy_decisions=(_policy_decision_dict(evaluation, tenant_id=tenant_id),),
            model_calls=tuple(record.to_dict() for record in records),
            outcome="FAIL",  # a budget breach is a FAIL finding, not a PASS
            previous_hash=previous_hash,
        )
        return evaluation, envelope


__all__ = [
    "EVIDENCE_SUBJECT_KIND",
    "PRODUCER",
    "CostControlBudget",
    "CostControlDecision",
    "CostControlEvaluation",
    "CostControlLoop",
    "evaluate_cost_window",
]
