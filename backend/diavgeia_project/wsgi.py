"""
WSGI config for diavgeia_project project.
"""

import os

from django.conf import settings
from django.core.wsgi import get_wsgi_application
from loguru import logger

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "diavgeia_project.settings")

try:
    # Check if tracing is enabled
    if settings.TRANSMIT_TO_JAEGER:
        # Simple approach - just force the Django service name
        os.environ["OTEL_SERVICE_NAME"] = "diavgeia-django"

        # Import and initialize after setting the service name
        from opentelemetry.instrumentation.django import DjangoInstrumentor
        from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
        from opentelemetry.instrumentation.requests import RequestsInstrumentor

        from .otel_init import initialize_otel

        # Initialize with Django service name
        tracer = initialize_otel("diavgeia-django")

        # Auto-instrument
        DjangoInstrumentor().instrument()
        RequestsInstrumentor().instrument()
        Psycopg2Instrumentor().instrument()
        logger.info("[OK] All Django instrumentations complete")
    else:
        logger.info("[MUTE] Jaeger tracing disabled (TRANSMIT_TO_JAEGER=false)")

except Exception as e:
    logger.error(f"[ERROR] OpenTelemetry initialization failed in wsgi.py: {e}")
    import traceback

    traceback.print_exc()

# Get the Django application
application = get_wsgi_application()
logger.info("[OK] WSGI application ready")
