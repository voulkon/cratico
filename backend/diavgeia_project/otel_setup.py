import json

# from opentelemetry.instrumentation.django import DjangoInstrumentor
# from opentelemetry.instrumentation.requests import RequestsInstrumentor
# from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
# from opentelemetry.instrumentation.celery import CeleryInstrumentor
import os

from django.conf import settings
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import StatusCode


def setup_tracing(service_name="diavgeia-app"):
    """Initialize and configure OpenTelemetry tracing."""
    # Check if Jaeger transmission is disabled
    if not settings.TRANSMIT_TO_JAEGER:
        # Return a no-op tracer when tracing is disabled
        return trace.get_tracer(__name__)

    # Check if a tracer provider is already set
    current_provider = trace.get_tracer_provider()
    if not isinstance(current_provider, trace.NoOpTracerProvider):
        # If a real tracer provider exists, just return a tracer
        return trace.get_tracer(__name__)

    # Configure the resource with service information
    resource = Resource(
        attributes={
            "service.name": service_name,
            "environment": os.getenv("DJANGO_SETTINGS_MODULE", "development"),
        }
    )

    # Set up the tracer provider with the resource
    trace.set_tracer_provider(TracerProvider(resource=resource))
    tracer_provider = trace.get_tracer_provider()

    # Set up the OTLP exporter to send traces to Jaeger
    # Note: Using modern OTLP protocol which Jaeger supports
    jaeger_host = os.getenv("JAEGER_HOST", "jaeger")
    jaeger_port = os.getenv("JAEGER_PORT", "4317")  # OTLP gRPC port

    otlp_exporter = OTLPSpanExporter(endpoint=f"http://{jaeger_host}:{jaeger_port}")

    # Process spans in batches for better performance
    span_processor = BatchSpanProcessor(otlp_exporter)
    tracer_provider.add_span_processor(span_processor)

    # Get a tracer for manual instrumentation
    tracer = trace.get_tracer(__name__)

    return tracer


class SecurityTracer:
    """Centralized utility for security event tracing"""

    def __init__(self):
        # Reuse your existing tracing setup
        self.tracer = setup_tracing(service_name="diavgeia-security")

    def log_security_event(
        self, event_type, details=None, user=None, ip=None, severity="INFO"
    ):
        """
        Log a security event as an OpenTelemetry span

        Parameters:
            event_type: String describing event type (e.g. "authentication.failed")
            details: Additional event details (string or dict)
            user: User object or ID
            ip: Client IP address
            severity: "INFO", "WARNING", "ERROR", or "CRITICAL"
        """
        # Create attributes for the security event
        attributes = {"security.event_type": event_type, "security.severity": severity}

        # Add user information if provided
        if user:
            if hasattr(user, "id"):
                attributes["security.user.id"] = str(user.id)
            if hasattr(user, "username"):
                attributes["security.user.username"] = user.username
            elif hasattr(user, "email"):
                attributes["security.user.email"] = user.email

        # Add IP address if provided
        if ip:
            attributes["security.client.ip"] = ip

        # Add details if provided
        if details:
            if isinstance(details, dict):
                # For structured data, add as individual attributes
                for key, value in details.items():
                    safe_key = key.replace(".", "_")
                    if isinstance(value, (str, int, float, bool)):
                        attributes[f"security.details.{safe_key}"] = value
                    else:
                        # Complex types need to be serialized
                        try:
                            attributes[f"security.details.{safe_key}"] = json.dumps(
                                value
                            )
                        except:
                            attributes[f"security.details.{safe_key}"] = str(value)
            else:
                # For simple details, just add as string
                attributes["security.details"] = str(details)

        # Create a span for this security event
        with self.tracer.start_as_current_span(
            f"security.{event_type}", attributes=attributes
        ) as span:
            # Set span status based on severity
            if severity in ["ERROR", "CRITICAL"]:
                span.set_status(StatusCode.ERROR)

            # Log additional diagnostic info if needed
            if severity == "CRITICAL":
                span.add_event(
                    "security.critical",
                    {"alert": "Potential security incident detected"},
                )


# Create a singleton instance for import
security_tracer = SecurityTracer()
