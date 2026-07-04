"""Optional OpenTelemetry bridge for proxy receipts.

This module is deliberately dependency-optional. Importing it must never print to
stdout or fail the MCP stdio process when OpenTelemetry packages are absent.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager, nullcontext
from typing import Any, Iterator

from .config import AppConfig

_tracer: Any = None
_otel_ready = False
_warned_unavailable = False


def init_telemetry(config: AppConfig) -> None:
    """Initialise OpenTelemetry if enabled and installed; otherwise stay no-op."""
    global _tracer, _otel_ready, _warned_unavailable
    _tracer = None
    _otel_ready = False

    if not config.otel_enabled:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    except Exception as exc:  # pragma: no cover - depends on optional packages
        if not _warned_unavailable:
            sys.stderr.write(f"[telemetry] OpenTelemetry unavailable, receipts still active: {exc}\n")
            _warned_unavailable = True
        return

    resource = Resource.create({"service.name": config.otel_service_name})
    provider = TracerProvider(resource=resource)
    exporter_kwargs = {}
    if config.otel_exporter_otlp_endpoint:
        exporter_kwargs["endpoint"] = config.otel_exporter_otlp_endpoint
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(**exporter_kwargs)))
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(config.otel_service_name)
    _otel_ready = True


@contextmanager
def span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    """Start an OTel span when available; otherwise behave as a no-op context."""
    if not _otel_ready or _tracer is None:
        with nullcontext() as ctx:
            yield ctx
        return

    clean_attrs = {
        key: value
        for key, value in (attributes or {}).items()
        if value is not None and isinstance(value, (str, bool, int, float))
    }
    with _tracer.start_as_current_span(name, attributes=clean_attrs) as active_span:
        yield active_span
