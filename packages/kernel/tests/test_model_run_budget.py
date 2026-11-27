"""R6-04: ``RunBudgetPolicy`` in ``ModelGateway`` (ADR-019 §5, gateway
half).

Uses the same local ``ModelPort``/clock/logger test doubles as
``test_model_policy.py`` (not ``cairn_adapters.model.FakeModelAdapter``,
which this kernel package must not import).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from cairn_kernel.errors import RunBudgetExceededError, ValidationError
from cairn_kernel.model import (
    ModelGateway,
    ModelRequest,
    ModelResponse,
    RunBudgetLimits,
    RunBudgetPolicy,
    SafetyMetadata,
    SafetyParameters,
    StructuredOutputExpectation,
)
from cairn_kernel.observability.ai import AiCallRecord

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class _FixedClock:
    def now(self) -> datetime:
        return NOW


@dataclass
class _RecordingLogger:
    records: list[AiCallRecord] = field(default_factory=list)

    def record(self, call: AiCallRecord) -> None:
        self.records.append(call)


@dataclass
class _CountingModelPort:
    response: ModelResponse | None = None
    calls: list[ModelRequest] = field(default_factory=list)

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls.append(request)
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


def _request(agent_run_id: str | None = "run-1") -> ModelRequest:
    return ModelRequest(
        prompt="summarise the workload",
        structured_output=_expectation(),
        safety=SafetyParameters(max_output_tokens=128),
        tenant_id="tenant-1",
        correlation_id="corr-1",
        agent_run_id=agent_run_id,
    )


def _response(input_tokens: int = 4, output_tokens: int = 2) -> ModelResponse:
    return ModelResponse(
        output={"summary": "ok"},
        provider="fake",
        model="fake-model-v1",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=1,
        safety=SafetyMetadata(flagged=False),
        correlation_id="corr-1",
        tenant_id="tenant-1",
    )


# --- RunBudgetLimits ----------------------------------------------------------


def test_run_budget_limits_missing_a_dimension_raises() -> None:
    with pytest.raises(ValidationError):
        RunBudgetLimits(max_total_tokens=None, max_cost_micro_usd=100)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        RunBudgetLimits(max_total_tokens=100, max_cost_micro_usd=0)


# --- RunBudgetPolicy -----------------------------------------------------------


def test_policy_refuses_a_request_with_no_registered_budget() -> None:
    policy = RunBudgetPolicy()
    with pytest.raises(RunBudgetExceededError):
        policy.check(_request())


def test_policy_allows_a_request_under_budget() -> None:
    policy = RunBudgetPolicy()
    policy.register("run-1", RunBudgetLimits(max_total_tokens=100, max_cost_micro_usd=100))
    policy.check(_request())  # does not raise


def test_policy_blocks_once_consumption_reaches_the_token_limit() -> None:
    policy = RunBudgetPolicy()
    policy.register("run-1", RunBudgetLimits(max_total_tokens=5, max_cost_micro_usd=1_000_000))
    policy.record("run-1", tokens=5, cost_micro_usd=0)
    with pytest.raises(RunBudgetExceededError):
        policy.check(_request())


def test_policy_blocks_once_consumption_reaches_the_cost_limit() -> None:
    policy = RunBudgetPolicy()
    policy.register("run-1", RunBudgetLimits(max_total_tokens=1_000_000, max_cost_micro_usd=10))
    policy.record("run-1", tokens=0, cost_micro_usd=10)
    with pytest.raises(RunBudgetExceededError):
        policy.check(_request())


def test_policy_ignores_a_request_with_no_agent_run_id() -> None:
    policy = RunBudgetPolicy()
    policy.check(_request(agent_run_id=None))  # does not raise; not an agent call


# --- ModelGateway: the block happens before the adapter ----------------------


def test_a_request_on_an_exhausted_run_raises_and_the_adapter_is_never_called() -> None:
    adapter = _CountingModelPort(response=_response())
    policy = RunBudgetPolicy()
    policy.register("run-1", RunBudgetLimits(max_total_tokens=5, max_cost_micro_usd=1_000_000))
    policy.record("run-1", tokens=5, cost_micro_usd=0)
    gateway = ModelGateway(adapter=adapter, clock=_FixedClock(), run_budget_policy=policy)

    with pytest.raises(RunBudgetExceededError):
        gateway.generate(_request())
    assert adapter.call_count == 0


def test_a_request_with_an_agent_run_id_and_no_registered_budget_is_refused() -> None:
    adapter = _CountingModelPort(response=_response())
    gateway = ModelGateway(adapter=adapter, clock=_FixedClock())  # default, empty RunBudgetPolicy
    with pytest.raises(RunBudgetExceededError):
        gateway.generate(_request())
    assert adapter.call_count == 0


def test_a_request_with_no_agent_run_id_is_unaffected() -> None:
    adapter = _CountingModelPort(response=_response())
    gateway = ModelGateway(adapter=adapter, clock=_FixedClock())
    gateway.generate(_request(agent_run_id=None))  # does not raise
    assert adapter.call_count == 1


def test_the_refusal_is_logged_with_the_run_id_on_it() -> None:
    adapter = _CountingModelPort(response=_response())
    logger = _RecordingLogger()
    gateway = ModelGateway(adapter=adapter, clock=_FixedClock(), ai_call_logger=logger)
    with pytest.raises(RunBudgetExceededError):
        gateway.generate(_request(agent_run_id="run-1"))
    assert logger.records[-1].outcome == "RUN_BUDGET_EXCEEDED"
    assert logger.records[-1].agent_run_id == "run-1"


def test_a_successful_call_debits_the_run_budget_so_a_later_call_is_blocked() -> None:
    adapter = _CountingModelPort(response=_response(input_tokens=3, output_tokens=2))
    policy = RunBudgetPolicy()
    policy.register("run-1", RunBudgetLimits(max_total_tokens=5, max_cost_micro_usd=1_000_000))
    gateway = ModelGateway(adapter=adapter, clock=_FixedClock(), run_budget_policy=policy)

    gateway.generate(_request())  # consumes 5 tokens, exactly at the limit
    assert adapter.call_count == 1

    with pytest.raises(RunBudgetExceededError):
        gateway.generate(_request())
    assert adapter.call_count == 1  # the second, blocked call never reached the adapter
