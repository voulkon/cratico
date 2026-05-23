import os
import sys

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# Global flag to prevent excessive initialization
_global_initialized = False
_services_initialized = set()


def initialize_otel(service_name):
    global _global_initialized, _services_initialized

    # Check if Jaeger transmission is disabled via Django settings
    try:
        from django.conf import settings

        if not settings.TRANSMIT_TO_JAEGER:
            # Return a no-op tracer when tracing is disabled
            return trace.get_tracer(__name__)
    except Exception:
        # If Django settings aren't available yet, default to disabled
        # This should rarely happen as settings should be loaded before otel_init
        return trace.get_tracer(__name__)

    # Handle management commands - create a separate service for them
    if "manage.py" in sys.argv[0] and len(sys.argv) > 1:
        command = sys.argv[1]
        # For server commands, use the original service name
        if command in ["runserver", "test", "shell"]:
            ...
            # logger.debug(f"[SERVER]️ Server command detected: {command}, using service: {service_name}")
            # IMPORTANT: Don't change the service name for server commands!
        else:
            # For utility commands, create a separate "commands" service
            command_service_name = f"diavgeia-commands"
            # logger.debug(f"[CONFIG] Management command detected: {command}, using service: {command_service_name}")
            service_name = command_service_name

    # logger.debug(f"[SCAN] initialize_otel called with service_name: {service_name}")
    # logger.debug(f"[SCAN] Global initialized: {_global_initialized}, Services: {_services_initialized}")

    # For runserver command, FORCE reset if we're trying to set Django
    if "runserver" in sys.argv and service_name == "diavgeia-django":
        # logger.debug("[RETRY] RUNSERVER: Forcing Django service name override")
        _global_initialized = False
        _services_initialized.clear()

    # If we already have a global provider set up, just return a tracer
    if _global_initialized and service_name in _services_initialized:
        # logger.debug(f"[WARN]️ Service {service_name} already initialized, returning existing tracer")
        return trace.get_tracer(__name__)

    # logger.debug(f"[LAUNCH] Setting up OpenTelemetry for {service_name}...")

    # Configure resource for this specific service
    resource = Resource.create(
        {
            "service.name": service_name,
            "environment": os.getenv("DJANGO_SETTINGS_MODULE", "development"),
            "service.version": "1.0.0",
        }
    )
    # logger.debug(f"[COPY] Resource created: {resource.attributes}")

    # Create provider
    provider = TracerProvider(resource=resource)

    # Set as global provider (last one wins, which is fine)
    trace.set_tracer_provider(provider)
    # logger.debug(f"[PROD] Set TracerProvider: {provider}")

    # Configure exporter
    jaeger_host = os.getenv("JAEGER_HOST", "jaeger")
    jaeger_port = os.getenv("JAEGER_PORT", "4317")
    endpoint = f"http://{jaeger_host}:{jaeger_port}"
    # logger.debug(f"[TARGET] OTLP endpoint: {endpoint}")

    try:
        otlp_exporter = OTLPSpanExporter(
            endpoint=endpoint, timeout=10  # Add timeout for debugging
        )
        # logger.debug("[OK] OTLP exporter created")
    except Exception:
        # logger.debug(f"[ERROR] OTLP exporter creation failed: {e}")
        raise

    # Use BatchSpanProcessor with shorter intervals for testing
    processor = BatchSpanProcessor(
        otlp_exporter,
        max_export_batch_size=10,
        schedule_delay_millis=1000,  # Export every 1 second instead of default 5
        export_timeout_millis=10000,  # 10 second timeout
    )
    provider.add_span_processor(processor)
    # logger.debug("[OK] Span processor added with fast export settings")

    # Mark as initialized
    _global_initialized = True
    _services_initialized.add(service_name)

    # Return a tracer
    tracer = trace.get_tracer(__name__)
    # logger.debug(f"[OK] OpenTelemetry initialization complete for {service_name}. Tracer: {tracer}")
    return tracer
