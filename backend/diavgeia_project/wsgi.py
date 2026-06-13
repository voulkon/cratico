"""
WSGI config for diavgeia_project project.
"""

import os

from django.conf import settings
from django.core.wsgi import get_wsgi_application
from loguru import logger

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "diavgeia_project.settings")

# --- Monkey-patch wsgiref.util.request_uri to use UTF-8 encoding ---
# OpenTelemetry's wsgi instrumentation calls wsgiref.util.request_uri(environ)
# which hardcodes encoding='latin1'. This crashes with a UnicodeEncodeError
# when PATH_INFO contains non-latin-1 characters (e.g. Greek names in URLs).
# Replacing it with a UTF-8-aware version fixes the issue.
import wsgiref.util as _wsgiref_util
from urllib.parse import quote as _quote

_original_request_uri = _wsgiref_util.request_uri


def _patched_request_uri(environ, include_query=True):
    """Replacement for wsgiref.util.request_uri that uses UTF-8 instead of latin-1."""
    from wsgiref.util import application_uri

    url = application_uri(environ)
    path_info = _quote(
        environ.get("PATH_INFO", ""), safe="/;=,", encoding="utf-8"
    )
    if not path_info.startswith("/"):
        url += "/" + path_info
    else:
        url += path_info
    if include_query and environ.get("QUERY_STRING"):
        url += "?" + environ["QUERY_STRING"]
    return url


_wsgiref_util.request_uri = _patched_request_uri
# --- End monkey-patch ---

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
