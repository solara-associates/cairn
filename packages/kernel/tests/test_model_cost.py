"""R5-02b (815): real per-call cost accounting for ``ModelGateway``.

Covers ``cairn_kernel.model.cost`` directly (price table lookup, ceiling
cost computation, fail-closed on an unregistered pair) and
``ModelGateway``'s own wiring of it into the ``AiCallRecord`` it logs
(814's placeholder ``cost_micro_usd=0`` is now real for a priced call, and
still falls back to 0 -- never raises -- for an unpriced one).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from cairn_kernel.errors import ModelPriceUnavailableError, ValidationError
from cairn_kernel.model import (
    ModelGateway,
    ModelPriceRate,
    ModelPriceTable,
    ModelRequest,
    ModelResponse,
    SafetyMetadata,
    SafetyParameters,
    StructuredOutputExpectation,
    compute_cost_micro_usd,
    default_price_table,
)
from cairn_kernel.observability.ai import AiCallRecord
from cairn_kernel.testing.fakes import FixedClock

NOW = datetime(2026, 11, 17, tzinfo=UTC)


@dataclass
class _RecordingLogger:
    records: list[AiCallRecord] = field(default_factory=list)

    def record(self, call: AiCallRecord) -> None:
        self.records.append(call)


@dataclass
class _OneShotModelPort:
    response: ModelResponse

    def generate(self, request: ModelRequest) -> ModelResponse:
        return self.response


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
        tenant_id="tenant-1",
        correlation_id="corr-1",
    )


def _response(
    *,
    provider: str = "fake",
    model: str = "fake-model-v1",
    input_tokens: int = 10,
    output_tokens: int = 5,
) -> ModelResponse:
    return ModelResponse(
        output={"summary": "ok"},
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=1,
        safety=SafetyMetadata(flagged=False),
        correlation_id="corr-1",
        tenant_id="tenant-1",
    )


# --- ModelPriceRate / ModelPriceTable ----------------------------------------


def test_price_rate_rejects_negative_values() -> None:
    with pytest.raises(ValidationError):
        ModelPriceRate(input_micro_usd_per_1k_tokens=-1, output_micro_usd_per_1k_tokens=0)


def test_price_table_rate_for_unregistered_pair_raises() -> None:
    table = ModelPriceTable()
    with pytest.raises(ModelPriceUnavailableError):
        table.rate_for("anthropic", "claude-unknown")


def test_price_table_with_rate_returns_a_new_table_leaving_the_original_untouched() -> None:
    base = ModelPriceTable()
    rate = ModelPriceRate(input_micro_usd_per_1k_tokens=100, output_micro_usd_per_1k_tokens=200)
    updated = base.with_rate("anthropic", "claude-x", rate)
    assert updated.rate_for("anthropic", "claude-x") == rate
    with pytest.raises(ModelPriceUnavailableError):
        base.rate_for("anthropic", "claude-x")


# --- compute_cost_micro_usd ---------------------------------------------------


def test_compute_cost_micro_usd_is_exact_multiple_of_1k_tokens() -> None:
    table = ModelPriceTable().with_rate(
        "anthropic",
        "claude-x",
        ModelPriceRate(input_micro_usd_per_1k_tokens=1_000, output_micro_usd_per_1k_tokens=3_000),
    )
    cost = compute_cost_micro_usd(
        table, provider="anthropic", model="claude-x", input_tokens=2_000, output_tokens=1_000
    )
    assert cost == 2_000 * 1_000 // 1_000 + 1_000 * 3_000 // 1_000  # 2_000 + 3_000 = 5_000


def test_compute_cost_micro_usd_rounds_up_a_fractional_result() -> None:
    table = ModelPriceTable().with_rate(
        "anthropic",
        "claude-x",
        ModelPriceRate(input_micro_usd_per_1k_tokens=1, output_micro_usd_per_1k_tokens=0),
    )
    # 1 token * 1 micro-usd-per-1k = 0.001 micro-usd -- never silently zero.
    cost = compute_cost_micro_usd(
        table, provider="anthropic", model="claude-x", input_tokens=1, output_tokens=0
    )
    assert cost == 1


def test_compute_cost_micro_usd_zero_tokens_is_zero_cost() -> None:
    table = default_price_table()
    cost = compute_cost_micro_usd(
        table, provider="fake", model="fake-model-v1", input_tokens=0, output_tokens=0
    )
    assert cost == 0


def test_compute_cost_micro_usd_unregistered_pair_raises() -> None:
    table = ModelPriceTable()
    with pytest.raises(ModelPriceUnavailableError):
        compute_cost_micro_usd(table, provider="x", model="y", input_tokens=1, output_tokens=1)


# --- ModelGateway wiring -------------------------------------------------------


def test_gateway_logs_a_real_nonzero_cost_for_a_priced_call() -> None:
    logger = _RecordingLogger()
    adapter = _OneShotModelPort(response=_response(input_tokens=1_000, output_tokens=1_000))
    gateway = ModelGateway(adapter=adapter, clock=FixedClock(NOW), ai_call_logger=logger)
    gateway.generate(_request())
    assert logger.records[-1].cost_micro_usd > 0
    assert logger.records[-1].cost_micro_usd == 500 + 1_500  # default_price_table's fake rate


def test_gateway_falls_back_to_zero_cost_for_an_unpriced_model_rather_than_raising() -> None:
    logger = _RecordingLogger()
    adapter = _OneShotModelPort(response=_response(provider="anthropic", model="claude-unknown"))
    gateway = ModelGateway(adapter=adapter, clock=FixedClock(NOW), ai_call_logger=logger)
    response = gateway.generate(_request())  # does not raise despite no price registered
    assert response.output == {"summary": "ok"}
    assert logger.records[-1].cost_micro_usd == 0


def test_gateway_uses_a_caller_supplied_price_table() -> None:
    logger = _RecordingLogger()
    adapter = _OneShotModelPort(
        response=_response(provider="anthropic", model="claude-x", input_tokens=1_000)
    )
    table = ModelPriceTable().with_rate(
        "anthropic",
        "claude-x",
        ModelPriceRate(input_micro_usd_per_1k_tokens=42, output_micro_usd_per_1k_tokens=0),
    )
    gateway = ModelGateway(
        adapter=adapter, clock=FixedClock(NOW), ai_call_logger=logger, price_table=table
    )
    gateway.generate(_request())
    assert logger.records[-1].cost_micro_usd == 42
