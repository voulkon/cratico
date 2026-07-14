"""
ASGI config for diavgeia_project project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "diavgeia_project.settings")
# Configure Loguru to match the Django logging format (JSON when
# USE_JSON_LOGGING=true).  See wsgi.py for the full rationale.
from diavgeia_project.logging.loguru_config import configure_loguru

configure_loguru()
application = get_asgi_application()
