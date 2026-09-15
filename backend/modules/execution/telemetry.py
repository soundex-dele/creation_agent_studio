"""Optional OpenTelemetry wiring for HTTP requests and durable execution."""

import threading

from django.conf import settings


_configure_lock = threading.Lock()
_configured = False


def configure_telemetry():
    """Configure the SDK once; remain a no-op when observability is disabled."""

    global _configured
    if _configured or not getattr(settings, "OTEL_ENABLED", False):
        return
    with _configure_lock:
        if _configured:
            return
        from opentelemetry import trace
        from opentelemetry.instrumentation.django import DjangoInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": getattr(
                        settings, "OTEL_SERVICE_NAME", "agent-studio"
                    ),
                    "deployment.environment.name": getattr(
                        settings, "OTEL_DEPLOYMENT_ENVIRONMENT", "development"
                    ),
                }
            )
        )
        endpoint = getattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", "")
        if endpoint:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(
                        endpoint=endpoint,
                        insecure=getattr(settings, "OTEL_EXPORTER_OTLP_INSECURE", False),
                    )
                )
            )
        trace.set_tracer_provider(provider)
        DjangoInstrumentor().instrument()
        _configured = True


def start_execution_span(name, *, run, attempt=None):
    if not getattr(settings, "OTEL_ENABLED", False):
        return None
    from opentelemetry import trace

    attributes = {
        "execution.run.id": str(run.id),
        "execution.organization.id": str(run.organization_id),
        "execution.executor.kind": run.executor_kind,
        "execution.executor.key": run.executor_key,
        "execution.source.type": run.source_type,
        "execution.source.id": str(run.source_id),
    }
    if attempt is not None:
        attributes.update(
            {
                "execution.attempt.id": str(attempt.id),
                "execution.attempt.number": attempt.number,
            }
        )
    return trace.get_tracer("agent_studio.execution").start_span(
        name, attributes=attributes
    )


def finish_execution_span(span, *, outcome, error=None):
    if span is None:
        return
    span.set_attribute("execution.outcome", outcome)
    if error is not None:
        from opentelemetry.trace import Status, StatusCode

        span.record_exception(error)
        span.set_status(Status(StatusCode.ERROR, str(error)))
    span.end()


def annotate_execution_span(span, key, value):
    if span is not None:
        span.set_attribute(key, value)
