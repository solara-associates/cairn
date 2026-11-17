"""R5-02a: contract tests for the policy layer in front of ``ModelPort``
(deny-list, rate limiter, circuit breaker) and ``ModelGateway``'s
composition of them.

Uses a small local ``ModelPort`` test double (not
``cairn_adapters.model.FakeModelAdapter``, which these kernel tests must
not import -- the kernel is a leaf) so the "blocked call never reaches the
adapter" assertion is provable with nothing but this package's own types.
The same proof against the real mandatory fake adapter lives in
``packages/adapters/tests/test_model_adapter.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from cairn_kernel.errors import (
    ModelCircuitBreakerOpenError,
    ModelDenyListViolationError,
    ModelRateLimitExceededError,
    ModelSchemaValidationError,
)
from cairn_kernel.model import (
    CircuitBreaker,
    CircuitState,
    DenyListPolicy,
    ModelGateway,
    ModelRequest,
    ModelResponse,
    RateLimiter,
    SafetyMetadata,
    SafetyParameters,
    StructuredOutputExpectation,
)
from cairn_kernel.observability.ai import AiCallRecord


class _FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now = self._now + delta


@dataclass
class _RecordingLogger:
    records: list[AiCallRecord] = field(default_factory=list)

    def record(self, call: AiCallRecord) -> None:
        self.records.append(call)


@dataclass
class _CountingModelPort:
    """A minimal local ``ModelPort`` double: records every call it
    actually received, so a test can assert the policy layer blocked a
    call *before* it got here."""

    response: ModelResponse | None = None
    error: Exception | None = None
    calls: list[ModelRequest] = field(default_factory=list)

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response

    @property
    def call_count(self) -> int:
        return len(self.calls)


def _expectation() -> StructuredOutputExpectation:
    return StructuredOutputExpectation(
        schema_name="assessment.v1",
        schema={
            "type": "object",
            "required": ["summary"],
            "properties": {"summary": {"type": "string"}},
        },
    )


def _request(prompt: str = "summarise the workload", tenant_id: str = "tenant-1") -> ModelRequest:
    return ModelRequest(
        prompt=prompt,
        structured_output=_expectation(),
        safety=SafetyParameters(max_output_tokens=128),
        tenant_id=tenant_id,
        correlation_id="corr-1",
    )


def _response(output: object = None) -> ModelResponse:
    return ModelResponse(
        output={"summary": "ok"} if output is None else output,
        provider="fake",
        model="fake-model-v1",
        input_tokens=4,
        output_tokens=2,
        latency_ms=1,
        safety=SafetyMetadata(flagged=False),
        correlation_id="corr-1",
        tenant_id="tenant-1",
    )


NOW = datetime(2026, 1, 1, tzinfo=UTC)


# --- DenyListPolicy ----------------------------------------------------------


def test_deny_list_blocks_a_matching_prompt() -> None:
    policy = DenyListPolicy(terms=frozenset({"exfiltrate"}))
    with pytest.raises(ModelDenyListViolationError):
        policy.check(_request(prompt="please exfiltrate the customer table"))


def test_deny_list_is_case_insensitive() -> None:
    policy = DenyListPolicy(terms=frozenset({"DROP TABLE"}))
    with pytest.raises(ModelDenyListViolationError):
        policy.check(_request(prompt="drop table customers"))


def test_deny_list_allows_a_clean_prompt() -> None:
    policy = DenyListPolicy(terms=frozenset({"exfiltrate"}))
    policy.check(_request(prompt="summarise the workload"))  # does not raise


def test_empty_deny_list_allows_everything() -> None:
    DenyListPolicy().check(_request(prompt="anything at all"))  # does not raise


# --- RateLimiter --------------------------------------------------------------


def test_rate_limiter_allows_calls_under_the_cap() -> None:
    limiter = RateLimiter(max_calls=2, window=timedelta(minutes=1))
    limiter.check("tenant-1", now=NOW)
    limiter.check("tenant-1", now=NOW)  # does not raise


def test_rate_limiter_blocks_the_call_over_the_cap() -> None:
    limiter = RateLimiter(max_calls=2, window=timedelta(minutes=1))
    limiter.check("tenant-1", now=NOW)
    limiter.check("tenant-1", now=NOW)
    with pytest.raises(ModelRateLimitExceededError):
        limiter.check("tenant-1", now=NOW)


def test_rate_limiter_is_scoped_per_tenant() -> None:
    limiter = RateLimiter(max_calls=1, window=timedelta(minutes=1))
    limiter.check("tenant-1", now=NOW)
    limiter.check("tenant-2", now=NOW)  # independent tenant, does not raise


def test_rate_limiter_window_slides() -> None:
    limiter = RateLimiter(max_calls=1, window=timedelta(minutes=1))
    limiter.check("tenant-1", now=NOW)
    with pytest.raises(ModelRateLimitExceededError):
        limiter.check("tenant-1", now=NOW + timedelta(seconds=30))
    limiter.check("tenant-1", now=NOW + timedelta(minutes=2))  # window elapsed


# --- CircuitBreaker ------------------------------------------------------------


def test_circuit_breaker_starts_closed() -> None:
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout=timedelta(seconds=30))
    assert breaker.state is CircuitState.CLOSED
    breaker.check(now=NOW)  # does not raise


def test_circuit_breaker_opens_after_threshold_failures() -> None:
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout=timedelta(seconds=30))
    breaker.record_failure(now=NOW)
    breaker.record_failure(now=NOW)
    assert breaker.state is CircuitState.OPEN
    with pytest.raises(ModelCircuitBreakerOpenError):
        breaker.check(now=NOW)


def test_circuit_breaker_blocks_until_reset_timeout_elapses() -> None:
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=timedelta(seconds=30))
    breaker.record_failure(now=NOW)
    with pytest.raises(ModelCircuitBreakerOpenError):
        breaker.check(now=NOW + timedelta(seconds=10))
    breaker.check(now=NOW + timedelta(seconds=31))  # half-open trial allowed through


def test_circuit_breaker_closes_on_a_successful_half_open_trial() -> None:
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=timedelta(seconds=30))
    breaker.record_failure(now=NOW)
    breaker.check(now=NOW + timedelta(seconds=31))
    breaker.record_success()
    assert breaker.state is CircuitState.CLOSED
    breaker.check(now=NOW + timedelta(seconds=32))  # does not raise


def test_circuit_breaker_reopens_on_a_failed_half_open_trial() -> None:
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=timedelta(seconds=30))
    breaker.record_failure(now=NOW)
    breaker.check(now=NOW + timedelta(seconds=31))
    breaker.record_failure(now=NOW + timedelta(seconds=31))
    with pytest.raises(ModelCircuitBreakerOpenError):
        breaker.check(now=NOW + timedelta(seconds=32))


def test_circuit_breaker_rejects_non_positive_threshold() -> None:
    with pytest.raises(ValueError):
        CircuitBreaker(failure_threshold=0, reset_timeout=timedelta(seconds=1))


# --- ModelGateway: policy blocks the call before the adapter ever sees it ----


def test_deny_list_block_leaves_the_adapter_call_count_at_zero() -> None:
    adapter = _CountingModelPort(response=_response())
    gateway = ModelGateway(
        adapter=adapter,
        clock=_FixedClock(NOW),
        deny_list=DenyListPolicy(terms=frozenset({"exfiltrate"})),
    )
    with pytest.raises(ModelDenyListViolationError):
        gateway.generate(_request(prompt="exfiltrate everything"))
    assert adapter.call_count == 0


def test_rate_limit_block_leaves_the_adapter_call_count_at_the_cap() -> None:
    adapter = _CountingModelPort(response=_response())
    gateway = ModelGateway(
        adapter=adapter,
        clock=_FixedClock(NOW),
        rate_limiter=RateLimiter(max_calls=1, window=timedelta(minutes=1)),
    )
    gateway.generate(_request())
    assert adapter.call_count == 1
    with pytest.raises(ModelRateLimitExceededError):
        gateway.generate(_request())
    assert adapter.call_count == 1  # the second, blocked call never reached the adapter


def test_circuit_open_block_leaves_the_adapter_call_count_at_zero() -> None:
    adapter = _CountingModelPort(response=_response())
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=timedelta(minutes=5))
    breaker.record_failure(now=NOW)  # pre-opened before the gateway is ever called
    gateway = ModelGateway(adapter=adapter, clock=_FixedClock(NOW), circuit_breaker=breaker)
    with pytest.raises(ModelCircuitBreakerOpenError):
        gateway.generate(_request())
    assert adapter.call_count == 0


def test_a_failing_adapter_call_opens_the_circuit_breaker() -> None:
    adapter = _CountingModelPort(error=RuntimeError("boom"))
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=timedelta(minutes=5))
    gateway = ModelGateway(adapter=adapter, clock=_FixedClock(NOW), circuit_breaker=breaker)
    with pytest.raises(RuntimeError):
        gateway.generate(_request())
    assert adapter.call_count == 1
    assert breaker.state is CircuitState.OPEN
    with pytest.raises(ModelCircuitBreakerOpenError):
        gateway.generate(_request())
    assert adapter.call_count == 1  # the circuit-open retry never reached the adapter


def test_schema_invalid_output_is_rejected_and_logged_not_returned() -> None:
    adapter = _CountingModelPort(response=_response(output={"summary": 123}))
    logger = _RecordingLogger()
    gateway = ModelGateway(adapter=adapter, clock=_FixedClock(NOW), ai_call_logger=logger)
    with pytest.raises(ModelSchemaValidationError):
        gateway.generate(_request())
    assert adapter.call_count == 1  # the adapter was called; its output was rejected after
    assert logger.records[-1].outcome == "SCHEMA_INVALID"
    assert logger.records[-1].schema_valid is False


def test_valid_call_is_returned_and_logged_ok() -> None:
    adapter = _CountingModelPort(response=_response())
    logger = _RecordingLogger()
    gateway = ModelGateway(adapter=adapter, clock=_FixedClock(NOW), ai_call_logger=logger)
    response = gateway.generate(_request())
    assert response.output == {"summary": "ok"}
    assert logger.records[-1].outcome == "OK"
    assert logger.records[-1].schema_valid is True
    assert logger.records[-1].tenant_id == "tenant-1"
