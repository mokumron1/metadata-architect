"""
OpenTelemetry tracing setup.

Configures a TracerProvider with an OTLP exporter (gRPC) when
OTEL_EXPORTER_OTLP_ENDPOINT is set; falls back to a no-op provider
in development so the app starts without a collector.

Usage:
    from metadata_architect.observability.tracing import setup_tracing, get_tracer
    setup_tracing()           # call once at startup
    tracer = get_tracer()     # use anywhere for manual spans
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

log = logging.getLogger(__name__)

_tracer = None


def setup_tracing(service_name: str = "metadata-architect") -> None:
    """
    Initialise the global TracerProvider.

    When OTEL_EXPORTER_OTLP_ENDPOINT is set, exports spans via OTLP/gRPC.
    Otherwise uses a no-op provider so the app works without a collector.
    """
    global _tracer

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)

        if endpoint:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            log.info("otel_tracing_enabled endpoint=%s", endpoint)
        else:
            log.info("otel_tracing_noop no OTEL_EXPORTER_OTLP_ENDPOINT set")

        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(service_name)

    except ImportError:
        log.warning("opentelemetry SDK not installed — tracing disabled")
        _tracer = _NoopTracer()


def get_tracer():
    """Return the global tracer (no-op if OTel is unavailable)."""
    global _tracer
    if _tracer is None:
        setup_tracing()
    return _tracer


# ---------------------------------------------------------------------------
# Lightweight no-op tracer for environments without the OTel SDK
# ---------------------------------------------------------------------------

class _NoopSpan:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def set_attribute(self, *_):
        pass

    def record_exception(self, *_):
        pass

    def set_status(self, *_):
        pass


class _NoopTracer:
    def start_as_current_span(self, name: str, **_):
        return _NoopSpan()

    def start_span(self, name: str, **_):
        return _NoopSpan()
