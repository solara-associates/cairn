import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

import pytest
from cairn_kernel.errors import ValidationError
from cairn_kernel.observability import (
    REQUIRED_LOG_FIELDS,
    AiCallRecord,
    JsonAiCallLogger,
    JsonLogFormatter,
    RedMetrics,
    RedMiddleware,
    RedTimer,
    StructuredLogger,
    configure_tracing,
    correlation_from_header,
    correlation_scope,
    current_correlation_id,
    extract_trace_context,
    hash_identifier,
    inject_trace_context,
    log_context,
    tracer_for,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

CREATED_AT = datetime(2026, 11, 13, 10, 0, tzinfo=UTC)


def _metric_data(reader: InMemoryMetricReader) -> dict[str, Any]:
    data = reader.get_metrics_data()
    metrics: dict[str, Any] = {}
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                metrics[metric.name] = metric.data
    return metrics


def _log_record(context: dict[str, object]) -> logging.LogRecord:
    record = logging.LogRecord(
        "cairn", logging.INFO, __file__, 1, "project.updated", (), None
    )
    record.context = context
    return record


def ai_call(**overrides: object) -> AiCallRecord:
    values: dict[str, object] = {
        "provider": "fake",
        "model": "fake-1",
        "input_hash": "a" * 64,
        "schema_valid": True,
        "outcome": "SUCCESS",
        "latency_ms": 12,
        "input_tokens": 10,
        "output_tokens": 5,
        "cost_micro_usd": 3,
        "correlation_id": "corr-1",
        "tenant_id": "tenant-1",
        "project_id": "project-1",
        "agent_run_id": "run-1",
        "created_at": CREATED_AT,
    }
    values.update(overrides)
    return AiCallRecord(**values)  # type: ignore[arg-type]


def test_trace_context_continues_across_a_service_boundary() -> None:
    exporter = InMemorySpanExporter()
    provider = configure_tracing("api", exporter=exporter, set_global=False)
    tracer = tracer_for(provider, "test")

    with tracer.start_as_current_span("api.request") as parent:
        carrier = inject_trace_context({"x-existing": "1"})
        parent_span = parent.get_span_context()

    assert carrier["x-existing"] == "1"
    assert "traceparent" in carrier

    remote = extract_trace_context(carrier)
    with tracer.start_as_current_span("worker.task", context=remote) as child:
        child_span = child.get_span_context()

    assert child_span.trace_id == parent_span.trace_id
    assert child.parent is not None
    assert child.parent.span_id == parent_span.span_id
    provider.shutdown()


def test_correlation_id_prefers_a_header_and_generates_when_missing() -> None:
    assert correlation_from_header("  corr-1 ") == "corr-1"
    first = correlation_from_header(None)
    second = correlation_from_header("")
    assert first and second
    assert first != second


def test_correlation_scope_sets_and_restores_the_id() -> None:
    with correlation_scope("outer"):
        assert current_correlation_id() == "outer"
        with correlation_scope("inner"):
            assert current_correlation_id() == "inner"
        assert current_correlation_id() == "outer"
    assert current_correlation_id() is None


def test_red_metrics_record_rate_errors_and_duration() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    red = RedMetrics(provider.get_meter("test"), service="api")

    red.record(operation="GET /v1/health", duration_ms=10)
    red.record(operation="GET /v1/health", duration_ms=30, failed=True)
    with RedTimer(red, "job.ingest"):
        pass

    data = _metric_data(reader)
    assert sum(point.value for point in data["cairn.red.requests"].data_points) == 3
    assert sum(point.value for point in data["cairn.red.errors"].data_points) == 1
    duration = data["cairn.red.duration"]
    assert sum(point.count for point in duration.data_points) == 3
    assert sum(point.sum for point in duration.data_points) >= 40
    provider.shutdown()


def test_red_metrics_reject_blank_operation_and_negative_duration() -> None:
    provider = MeterProvider()
    red = RedMetrics(provider.get_meter("test"), service="api")
    with pytest.raises(ValueError):
        red.record(operation="", duration_ms=1)
    with pytest.raises(ValueError):
        red.record(operation="GET /v1/health", duration_ms=-1)
    provider.shutdown()


def test_red_middleware_records_a_server_error() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    red = RedMetrics(provider.get_meter("test"), service="api")

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 503, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b""}

    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(
        RedMiddleware(app, red)(
            {"type": "http", "method": "GET", "path": "/v1/health"},
            receive,
            send,
        )
    )

    data = _metric_data(reader)
    assert sum(point.value for point in data["cairn.red.errors"].data_points) == 1
    assert sent[0]["status"] == 503
    provider.shutdown()


def test_log_context_hashes_the_tenant_and_keeps_required_fields() -> None:
    context = log_context(
        correlation_id="corr-1",
        tenant_id="tenant-1",
        project_id="project-1",
        operation_id="op-1",
        hash_tenant=True,
    )
    assert set(REQUIRED_LOG_FIELDS) <= set(context)
    assert context["correlation_id"] == "corr-1"
    assert context["tenant_id"] == hash_identifier("tenant-1")
    assert context["tenant_id"] != "tenant-1"


def test_json_log_formatter_always_includes_required_fields() -> None:
    payload = json.loads(
        JsonLogFormatter().format(
            _log_record({"correlation_id": "corr-1", "extra": 1})
        )
    )
    assert payload["event"] == "project.updated"
    assert payload["level"] == "INFO"
    assert payload["extra"] == 1
    for field in REQUIRED_LOG_FIELDS:
        assert field in payload
    assert payload["tenant_id"] is None


def test_structured_logger_emits_its_context() -> None:
    logger = logging.getLogger("cairn.test.observability")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    captured: list[dict[str, Any]] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(json.loads(JsonLogFormatter().format(record)))

    logger.addHandler(Capture())
    StructuredLogger(logger=logger).emit(
        "project.updated",
        context=log_context(
            correlation_id="corr-1",
            tenant_id="tenant-1",
            project_id="project-1",
            operation_id="op-1",
        ),
    )
    assert captured[0]["event"] == "project.updated"
    assert captured[0]["correlation_id"] == "corr-1"
    assert captured[0]["tenant_id"] == "tenant-1"


def test_ai_call_record_contains_every_required_field() -> None:
    data = ai_call().to_dict()
    for field in (
        "provider",
        "model",
        "input_hash",
        "schema_valid",
        "outcome",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "cost_micro_usd",
        "correlation_id",
        "tenant_id",
    ):
        assert field in data
    assert data["total_tokens"] == 15
    assert data["created_at"] == CREATED_AT.isoformat()


def test_ai_call_record_rejects_invalid_values() -> None:
    for overrides in (
        {"provider": ""},
        {"model": ""},
        {"input_hash": "abc"},
        {"latency_ms": -1},
        {"input_tokens": -1},
        {"output_tokens": -1},
        {"cost_micro_usd": -1},
        {"schema_valid": "yes"},
    ):
        with pytest.raises(ValidationError):
            ai_call(**overrides)


def test_json_ai_call_logger_emits_required_fields() -> None:
    logger = logging.getLogger("cairn.test.ai")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    captured: list[dict[str, Any]] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(json.loads(JsonLogFormatter().format(record)))

    logger.addHandler(Capture())
    JsonAiCallLogger(StructuredLogger(logger=logger), hash_tenant=True).record(
        ai_call()
    )

    payload = captured[0]
    assert payload["event"] == "model.call.completed"
    assert payload["provider"] == "fake"
    assert payload["model"] == "fake-1"
    assert payload["tenant_id"] == hash_identifier("tenant-1")
    assert payload["total_tokens"] == 15
    for field in REQUIRED_LOG_FIELDS:
        assert field in payload
