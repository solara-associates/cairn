"""CAIRN cairn_kernel.observability."""

from cairn_kernel.observability.ai import (
    INPUT_HASH_PATTERN,
    AiCallLogger,
    AiCallRecord,
    JsonAiCallLogger,
)
from cairn_kernel.observability.correlation import (
    CORRELATION_HEADER,
    correlation_from_header,
    correlation_scope,
    current_correlation_id,
    new_correlation_id,
)
from cairn_kernel.observability.logging import (
    REQUIRED_LOG_FIELDS,
    JsonLogFormatter,
    StructuredLogger,
    hash_identifier,
    log_context,
)
from cairn_kernel.observability.red import RedMetrics, RedMiddleware, RedTimer
from cairn_kernel.observability.tracing import (
    configure_tracing,
    extract_trace_context,
    inject_trace_context,
    trace_attributes,
    tracer_for,
)

__all__ = [
    "CORRELATION_HEADER",
    "INPUT_HASH_PATTERN",
    "REQUIRED_LOG_FIELDS",
    "AiCallLogger",
    "AiCallRecord",
    "JsonAiCallLogger",
    "JsonLogFormatter",
    "RedMetrics",
    "RedMiddleware",
    "RedTimer",
    "StructuredLogger",
    "configure_tracing",
    "correlation_from_header",
    "correlation_scope",
    "current_correlation_id",
    "extract_trace_context",
    "hash_identifier",
    "inject_trace_context",
    "log_context",
    "new_correlation_id",
    "trace_attributes",
    "tracer_for",
]
