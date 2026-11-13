from collections.abc import Mapping, MutableMapping

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter


def configure_tracing(
    service_name: str,
    *,
    exporter: SpanExporter | None = None,
    attributes: Mapping[str, str] | None = None,
    set_global: bool = True,
) -> TracerProvider:
    resource = Resource.create(
        {"service.name": service_name, **dict(attributes or {})}
    )
    provider = TracerProvider(resource=resource)
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    if set_global:
        trace.set_tracer_provider(provider)
    return provider


def tracer_for(provider: TracerProvider, name: str) -> trace.Tracer:
    return provider.get_tracer(name)


def inject_trace_context(
    carrier: MutableMapping[str, str] | None = None,
) -> dict[str, str]:
    target: MutableMapping[str, str] = {} if carrier is None else carrier
    inject(target)
    return dict(target)


def extract_trace_context(carrier: Mapping[str, str]) -> Context:
    return extract(dict(carrier))


def trace_attributes(
    *,
    tenant_id: str,
    project_id: str | None = None,
    correlation_id: str | None = None,
    operation_id: str | None = None,
) -> dict[str, str]:
    attributes = {"tenant_id": tenant_id}
    if project_id is not None:
        attributes["project_id"] = project_id
    if correlation_id is not None:
        attributes["correlation_id"] = correlation_id
    if operation_id is not None:
        attributes["operation_id"] = operation_id
    return attributes
