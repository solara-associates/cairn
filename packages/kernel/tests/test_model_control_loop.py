"""R5-02b (815): the LLMOps cost control loop -- observe/decide/act.

- a synthetic cost-spike fixture (canned ``AiCallRecord``s, never a real
  spend) that crosses the configured threshold triggers THROTTLE or STOP
  within the same test;
- that decision actually changes 814's own ``RateLimiter``/
  ``CircuitBreaker`` state -- proved the same "adapter call count stays
  put" way 814's own tests prove a block, here via ``ModelGateway`` +
  ``FakeModelAdapter``;
- the THROTTLE/STOP decision produces a sealed evidence record that
  verifies independently (round-trip), the same pattern R3/R4's own
  evidence tests use.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from cairn_adapters.model import FakeModelAdapter
from cairn_kernel.errors import (
    ModelCircuitBreakerOpenError,
    ModelRateLimitExceededError,
    ValidationError,
)
from cairn_kernel.evidence import verify_envelope
from cairn_kernel.model import (
    CircuitBreaker,
    CostControlBudget,
    CostControlDecision,
    CostControlLoop,
    ModelGateway,
    ModelRequest,
    RateLimiter,
    SafetyMetadata,
    SafetyParameters,
    StructuredOutputExpectation,
    evaluate_cost_window,
)
from cairn_kernel.observability.ai import AiCallRecord
from cairn_kernel.testing import FakeEvidenceSigner, FakeEvidenceVerifier
from cairn_kernel.testing.fakes import FixedClock

NOW = datetime(2026, 11, 17, tzinfo=UTC)
TENANT = "tenant-1"
PROJECT = "project-1"


def _call_record(cost_micro_usd: int, *, correlation_id: str = "corr-1") -> AiCallRecord:
    return AiCallRecord(
        provider="fake",
        model="fake-model-v1",
        input_hash="a" * 64,
        schema_valid=True,
        outcome="OK",
        latency_ms=1,
        input_tokens=100,
        output_tokens=50,
        cost_micro_usd=cost_micro_usd,
        correlation_id=correlation_id,
        tenant_id=TENANT,
        created_at=NOW,
    )


# --- evaluate_cost_window: pure decision ------------------------------------


def test_budget_rejects_a_stop_threshold_below_throttle() -> None:
    with pytest.raises(ValidationError):
        CostControlBudget(throttle_threshold_micro_usd=1_000, stop_threshold_micro_usd=500)


def test_cost_under_both_thresholds_continues() -> None:
    budget = CostControlBudget(throttle_threshold_micro_usd=1_000, stop_threshold_micro_usd=5_000)
    evaluation = evaluate_cost_window([_call_record(100)], budget)
    assert evaluation.decision is CostControlDecision.CONTINUE


def test_a_synthetic_cost_spike_crossing_the_throttle_threshold_decides_throttle() -> None:
    budget = CostControlBudget(throttle_threshold_micro_usd=1_000, stop_threshold_micro_usd=10_000)
    spike = [_call_record(400, correlation_id=f"corr-{i}") for i in range(3)]  # totals 1_200
    evaluation = evaluate_cost_window(spike, budget)
    assert evaluation.decision is CostControlDecision.THROTTLE
    assert evaluation.total_cost_micro_usd == 1_200


def test_a_synthetic_cost_spike_crossing_the_stop_threshold_decides_stop() -> None:
    budget = CostControlBudget(throttle_threshold_micro_usd=1_000, stop_threshold_micro_usd=5_000)
    spike = [_call_record(2_000, correlation_id=f"corr-{i}") for i in range(3)]  # totals 6_000
    evaluation = evaluate_cost_window(spike, budget)
    assert evaluation.decision is CostControlDecision.STOP
    assert evaluation.total_cost_micro_usd == 6_000


# --- CostControlLoop.run: act on 814's own RateLimiter/CircuitBreaker -------


def _expectation() -> StructuredOutputExpectation:
    return StructuredOutputExpectation(
        schema_name="assessment.v1",
        schema={
            "type": "object",
            "required": ["summary"],
            "properties": {"summary": {"type": "string"}},
        },
    )


def _request() -> ModelRequest:
    return ModelRequest(
        prompt="summarise the workload",
        structured_output=_expectation(),
        safety=SafetyParameters(max_output_tokens=128),
        tenant_id=TENANT,
        correlation_id="corr-1",
    )


def _response():
    from cairn_kernel.model import ModelResponse

    return ModelResponse(
        output={"summary": "ok"},
        provider="fake",
        model="fake-model-v1",
        input_tokens=100,
        output_tokens=50,
        latency_ms=1,
        safety=SafetyMetadata(flagged=False),
        correlation_id="corr-1",
        tenant_id=TENANT,
    )


def test_throttle_decision_exhausts_the_rate_limiter_and_blocks_the_next_gateway_call() -> None:
    adapter = FakeModelAdapter(responses=[_response(), _response()])
    rate_limiter = RateLimiter(max_calls=5, window=timedelta(minutes=1))
    gateway = ModelGateway(adapter=adapter, clock=FixedClock(NOW), rate_limiter=rate_limiter)

    # Baseline: well under the limiter's own cap, a call goes straight through.
    gateway.generate(_request())
    assert adapter.call_count == 1

    loop = CostControlLoop(
        budget=CostControlBudget(
            throttle_threshold_micro_usd=1_000, stop_threshold_micro_usd=10_000
        ),
        signer=FakeEvidenceSigner(),
    )
    spike = [
        _call_record(400, correlation_id=f"corr-{i}") for i in range(3)
    ]  # totals 1_200: THROTTLE
    evaluation, envelope = loop.run(
        spike,
        tenant_id=TENANT,
        project_id=PROJECT,
        now=NOW,
        package_id="cost-control-1",
        rate_limiter=rate_limiter,
    )
    assert evaluation.decision is CostControlDecision.THROTTLE
    assert envelope is not None

    # The throttle decision -- not a change to max_calls or a new mechanism
    # -- is what now blocks the next call through the *same* rate limiter.
    with pytest.raises(ModelRateLimitExceededError):
        gateway.generate(_request())
    assert adapter.call_count == 1  # the throttled call never reached the adapter


def test_stop_decision_force_opens_the_circuit_breaker_and_blocks_the_next_gateway_call() -> None:
    adapter = FakeModelAdapter(responses=[_response(), _response()])
    breaker = CircuitBreaker(failure_threshold=5, reset_timeout=timedelta(minutes=5))
    gateway = ModelGateway(adapter=adapter, clock=FixedClock(NOW), circuit_breaker=breaker)

    gateway.generate(_request())
    assert adapter.call_count == 1
    assert breaker.state.value == "CLOSED"

    loop = CostControlLoop(
        budget=CostControlBudget(
            throttle_threshold_micro_usd=1_000, stop_threshold_micro_usd=5_000
        ),
        signer=FakeEvidenceSigner(),
    )
    spike = [
        _call_record(2_000, correlation_id=f"corr-{i}") for i in range(3)
    ]  # totals 6_000: STOP
    evaluation, envelope = loop.run(
        spike,
        tenant_id=TENANT,
        project_id=PROJECT,
        now=NOW,
        package_id="cost-control-2",
        circuit_breaker=breaker,
    )
    assert evaluation.decision is CostControlDecision.STOP
    assert envelope is not None

    with pytest.raises(ModelCircuitBreakerOpenError):
        gateway.generate(_request())
    assert adapter.call_count == 1  # the stopped call never reached the adapter


def test_continue_decision_leaves_policy_state_untouched_and_seals_nothing() -> None:
    rate_limiter = RateLimiter(max_calls=5, window=timedelta(minutes=1))
    loop = CostControlLoop(
        budget=CostControlBudget(
            throttle_threshold_micro_usd=10_000, stop_threshold_micro_usd=50_000
        ),
        signer=FakeEvidenceSigner(),
    )
    evaluation, envelope = loop.run(
        [_call_record(100)],
        tenant_id=TENANT,
        project_id=PROJECT,
        now=NOW,
        package_id="cost-control-3",
        rate_limiter=rate_limiter,
    )
    assert evaluation.decision is CostControlDecision.CONTINUE
    assert envelope is None
    rate_limiter.check(TENANT, now=NOW)  # still well under cap -- untouched by the loop


# --- evidence: THROTTLE/STOP decisions verify independently ----------------


def test_throttle_decision_evidence_verifies_independently() -> None:
    loop = CostControlLoop(
        budget=CostControlBudget(
            throttle_threshold_micro_usd=1_000, stop_threshold_micro_usd=10_000
        ),
        signer=FakeEvidenceSigner(),
    )
    spike = [_call_record(1_200)]
    _, envelope = loop.run(
        spike, tenant_id=TENANT, project_id=PROJECT, now=NOW, package_id="cost-control-4"
    )
    assert envelope is not None

    # A fresh verifier, sharing no in-process object with the signer.
    verification = verify_envelope(envelope, verifier=FakeEvidenceVerifier())
    assert verification.valid, verification
    assert envelope.policy_decisions[0]["decision"] == "THROTTLE"
    assert envelope.model_calls[0]["correlation_id"] == "corr-1"


def test_stop_decision_evidence_tamper_is_detected() -> None:
    loop = CostControlLoop(
        budget=CostControlBudget(
            throttle_threshold_micro_usd=1_000, stop_threshold_micro_usd=5_000
        ),
        signer=FakeEvidenceSigner(),
    )
    spike = [_call_record(6_000)]
    _, envelope = loop.run(
        spike, tenant_id=TENANT, project_id=PROJECT, now=NOW, package_id="cost-control-5"
    )
    assert envelope is not None
    verification = verify_envelope(envelope, verifier=FakeEvidenceVerifier())
    assert verification.valid

    tampered_decisions = (dict(envelope.policy_decisions[0], decision="CONTINUE"),)
    tampered = replace(envelope, policy_decisions=tampered_decisions)
    tampered_verification = verify_envelope(tampered, verifier=FakeEvidenceVerifier())
    assert not tampered_verification.valid
