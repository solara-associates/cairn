"""R5-02a: ``FakeModelAdapter`` (ADR-014's mandatory fake) composed with the
kernel's ``ModelGateway`` and policy layer -- the same contract tests as
``packages/kernel/tests/test_model_policy.py``, but against the real
adapter this unit ships, proving the policy layer blocks a call before
*this* adapter's own call counter ever moves.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from cairn_adapters.model import FakeModelAdapter
from cairn_kernel.errors import (
    ModelCircuitBreakerOpenError,
    ModelDenyListViolationError,
    ModelRateLimitExceededError,
    ModelSchemaValidationError,
)
from cairn_kernel.model import (
    CircuitBreaker,
    DenyListPolicy,
    ModelGateway,
    ModelRequest,
    ModelResponse,
    RateLimiter,
    SafetyMetadata,
    SafetyParameters,
    StructuredOutputExpectation,
)
from cairn_kernel.testing.fakes import FixedClock

NOW = datetime(2026, 11, 17, tzinfo=UTC)


def _expectation() -> StructuredOutputExpectation:
    return StructuredOutputExpectation(
        schema_name="assessment.v1",
        schema={
            "type": "object",
            "required": ["summary", "confidence"],
            "properties": {
                "summary": {"type": "string"},
                "confidence": {"type": "number"},
            },
        },
    )


def _request(prompt: str = "summarise the workload") -> ModelRequest:
    return ModelRequest(
        prompt=prompt,
        structured_output=_expectation(),
        safety=SafetyParameters(max_output_tokens=256),
        tenant_id="tenant-1",
        correlation_id="corr-1",
    )


def _response(output: object = None) -> ModelResponse:
    return ModelResponse(
        output={"summary": "ok", "confidence": 0.8} if output is None else output,
        provider="fake",
        model="fake-model-v1",
        input_tokens=10,
        output_tokens=5,
        latency_ms=3,
        safety=SafetyMetadata(flagged=False),
        correlation_id="corr-1",
        tenant_id="tenant-1",
    )


def test_fake_adapter_returns_the_next_queued_response() -> None:
    adapter = FakeModelAdapter(responses=[_response()])
    response = adapter.generate(_request())
    assert response.output == {"summary": "ok", "confidence": 0.8}
    assert adapter.call_count == 1


def test_fake_adapter_raises_configured_error_at_the_configured_index() -> None:
    adapter = FakeModelAdapter(responses=[_response()], errors={0: RuntimeError("boom")})
    with pytest.raises(RuntimeError):
        adapter.generate(_request())
    assert adapter.call_count == 1


def test_fake_adapter_makes_no_network_call_and_holds_no_credential() -> None:
    adapter = FakeModelAdapter(responses=[_response()])
    forbidden_substrings = ("secret", "credential", "token", "password", "api_key")
    for attribute in dir(adapter):
        if attribute.startswith("__"):
            continue
        lowered = attribute.lower()
        assert not any(bad in lowered for bad in forbidden_substrings), attribute


# --- contract tests: policy blocks the call before this adapter sees it ----


def test_deny_list_block_never_reaches_the_fake_adapter() -> None:
    adapter = FakeModelAdapter(responses=[_response()])
    gateway = ModelGateway(
        adapter=adapter,
        clock=FixedClock(NOW),
        deny_list=DenyListPolicy(terms=frozenset({"exfiltrate"})),
    )
    with pytest.raises(ModelDenyListViolationError):
        gateway.generate(_request(prompt="exfiltrate the customer table"))
    assert adapter.call_count == 0


def test_rate_limit_block_never_reaches_the_fake_adapter_past_the_cap() -> None:
    adapter = FakeModelAdapter(responses=[_response(), _response()])
    gateway = ModelGateway(
        adapter=adapter,
        clock=FixedClock(NOW),
        rate_limiter=RateLimiter(max_calls=1, window=timedelta(minutes=1)),
    )
    gateway.generate(_request())
    assert adapter.call_count == 1
    with pytest.raises(ModelRateLimitExceededError):
        gateway.generate(_request())
    assert adapter.call_count == 1


def test_open_circuit_breaker_never_reaches_the_fake_adapter() -> None:
    adapter = FakeModelAdapter(responses=[_response()])
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=timedelta(minutes=5))
    breaker.record_failure(now=NOW)
    gateway = ModelGateway(adapter=adapter, clock=FixedClock(NOW), circuit_breaker=breaker)
    with pytest.raises(ModelCircuitBreakerOpenError):
        gateway.generate(_request())
    assert adapter.call_count == 0


def test_schema_invalid_output_from_the_fake_adapter_is_rejected() -> None:
    adapter = FakeModelAdapter(
        responses=[_response(output={"summary": "ok"})]
    )  # missing confidence
    gateway = ModelGateway(adapter=adapter, clock=FixedClock(NOW))
    with pytest.raises(ModelSchemaValidationError):
        gateway.generate(_request())
    assert adapter.call_count == 1  # adapter was called; its malformed output was rejected after


def test_valid_output_from_the_fake_adapter_passes_through() -> None:
    adapter = FakeModelAdapter(responses=[_response()])
    gateway = ModelGateway(adapter=adapter, clock=FixedClock(NOW))
    response = gateway.generate(_request())
    assert response.output == {"summary": "ok", "confidence": 0.8}
