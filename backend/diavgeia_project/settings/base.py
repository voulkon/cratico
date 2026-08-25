"""
Base Django settings.

Contains core settings like SECRET_KEY, DEBUG, ALLOWED_HOSTS, and other fundamental configurations.
"""

import os
from pathlib import Path
from urllib.parse import urlparse

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
default_unsafe_secret_key = "django-insecure-_qy*f$4zd#u_)lt_v%2t*29g9f$rr0=u!-g=t#+6g+z0)u6zsi"  # nosec: B105 - Default key for development only, overridden in production
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", default_unsafe_secret_key)


# SECURITY WARNING: don't run with debug turned on in production!
DEBUG_ENV = os.getenv("DEBUG", "False")  # Get it as a string
DEBUG = DEBUG_ENV.lower() in ("true", "1", "t")  # Convert to boolean

# Stealth mode - requires authentication for all API endpoints
STEALTH_MODE = os.getenv("STEALTH_MODE", "False").lower() in ("true", "1", "t")

# Stealth allowlist - when enabled with STEALTH_MODE, only users in AllowedUser table can access
STEALTH_ALLOWLIST = os.getenv("STEALTH_ALLOWLIST", "False").lower() in (
    "true",
    "1",
    "t",
)


FRONTEND_DOMAINS: list[str] = os.getenv(
    "FRONTEND_DOMAINS", "http://localhost:3000"
).split(",")
# Importable from this module, but NOT exposed as settings.FRONTEND_DOMAINS_clean:
# Django only copies all-uppercase module attributes into the settings object.
FRONTEND_DOMAINS_clean: list[str] = [d.strip() for d in FRONTEND_DOMAINS]

if not FRONTEND_DOMAINS_clean and not DEBUG:
    raise ValueError("FRONTEND_DOMAINS must be set in production")
FRONTEND_HOSTNAMES = [
    urlparse(d).netloc for d in FRONTEND_DOMAINS_clean if urlparse(d).netloc
]

# Last-resort fallback origins used by core.services.frontend_url when no
# FRONTEND_DOMAINS are configured. Overridable via env for local workflows
# (e.g. FRONTEND_DEV_BASE=http://localhost when the frontend runs on port 80).
FRONTEND_DEV_BASE = os.getenv("FRONTEND_DEV_BASE", "http://localhost:3000")
FRONTEND_PROD_BASE = os.getenv("FRONTEND_PROD_BASE", "https://crati.co")

# Start with frontend hostnames
ALLOWED_HOSTS = FRONTEND_HOSTNAMES.copy()

# Add any additional hosts from environment
ALLOWED_HOSTS_ENV = os.getenv("ALLOWED_HOSTS")
if ALLOWED_HOSTS_ENV:
    ALLOWED_HOSTS.extend([host.strip() for host in ALLOWED_HOSTS_ENV.split(",")])

# If DEBUG is True, you might want to add common local hosts for convenience
if DEBUG:
    ALLOWED_HOSTS.extend(["localhost", "127.0.0.1"])

# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# WSGI application
WSGI_APPLICATION = "diavgeia_project.wsgi.application"

# Root URL configuration
ROOT_URLCONF = "diavgeia_project.urls"

# Let's document here which parts change:
INDEX_THE_OPENSEARCH = os.getenv("INDEX_THE_OPENSEARCH", "True").lower() == "true"
# If False:
#   the DecisionPipelineOrchestrator will skip indexing steps
#   the search api view will be omitting to ask opensearch
#   we need some task to be ensuring that all extracted documents will get indexed if we change this to True
HAVE_AFM_FETCH_JOB = os.getenv("HAVE_AFM_FETCH_JOB", "True").lower() == "true"
# If False:
#   the DecisionPipelineOrchestrator will skip registering afm tasks
#   the decisions api view(s) will be omitting to return afm data
#   we need some task to be ensuring that all companies extracted as Entities that DON'T have afm data will get it if we change this to True
#   on this critical is the mechanism that keeps the afm data ASKED updated (either found or not found)
EXTRACT_THE_DOCS_FROM_PDFS = (
    os.getenv("EXTRACT_THE_DOCS_FROM_PDFS", "True").lower() == "true"
)
# If False:
#   the DecisionPipelineOrchestrator will skip pdf text extraction steps
#   the decisions api view(s) will be omitting to return afm data
#   we need some task to be ensuring that all documents that DON'T have text extracted will start getting extracted (aka create the respective tasks)

TRANSMIT_TO_JAEGER = os.getenv("TRANSMIT_TO_JAEGER", "False").lower() == "true"
# If False:
#   OpenTelemetry/Jaeger tracing is disabled
#   No spans will be sent to Jaeger

ENABLE_SILK = os.getenv("ENABLE_SILK", "False").lower() in ("true", "1", "t")
# If True:
#   Silk profiling middleware and UI are enabled at /api/silk/
#   Defaults to DEBUG value (on in dev, off in prod)

LIGHT_WORKER = os.getenv("LIGHT_WORKER", "False").lower() == "true"
# If True:
#   Celery worker uses lightweight mode without PDF processing dependencies (Docling)
#   Only PyMuPDF extractor is available
#   Reduces Docker image size and memory footprint

RETRY_AFM_FETCHES_AFTER_NUMBER_OF_DAYS = int(
    os.getenv("RETRY_AFM_FETCHES_AFTER_NUMBER_OF_DAYS", "60")
)

# Import Job Queue Concurrency Control
# Maximum number of ImportJobs that can run simultaneously
# Set to 1 for sequential processing (prevents Redis/OpenSearch memory exhaustion)
# Set to higher values for parallel processing (requires more memory)
IMPORT_MAX_CONCURRENT_JOBS = int(os.getenv("IMPORT_MAX_CONCURRENT_JOBS", "1"))
