import os
import sys

import diavgeia_project.otel_init as otel_init_module
from celery import Celery
from celery.schedules import crontab
from celery.signals import beat_init, worker_process_init
from opentelemetry import trace
from opentelemetry.instrumentation.celery import CeleryInstrumentor

from .otel_init import initialize_otel

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "diavgeia_project.settings")

# OpenTelemetry Initialization Logic
# We avoid initializing in the Worker Parent process to prevent gRPC fork-safety issues.
# Instead, we initialize in the child process via signals.

is_celery_worker = len(sys.argv) > 1 and "worker" in sys.argv
is_celery_beat = len(sys.argv) > 1 and "beat" in sys.argv


# Initialize for Beat (Single process)
@beat_init.connect
def init_beat_tracing(*args, **kwargs):
    from django.conf import settings

    if not settings.TRANSMIT_TO_JAEGER:
        print("[MUTE] [Beat] Jaeger tracing disabled (TRANSMIT_TO_JAEGER=false)")
        return
    try:
        initialize_otel("diavgeia-celery-beat")
        CeleryInstrumentor().instrument()
        print("[OK] [Beat] OpenTelemetry initialized")
    except Exception as e:
        print(f"[ERROR] [Beat] Failed to initialize OpenTelemetry: {e}")


# If we are NOT a worker and NOT beat (e.g. Django web, management command, etc.)
# We invoke instrumentation. We assume the TracerProvider is configured elsewhere (e.g. settings/wsgi)
# or via initialize_otel called by other means.
if not is_celery_worker and not is_celery_beat:
    try:
        # We can try to instrument using existing provider if available
        CeleryInstrumentor().instrument()
    except Exception:
        pass

# Configure Loguru for JSON logging BEFORE any Loguru imports
from diavgeia_project.logging.loguru_config import configure_loguru

configure_loguru()

# Create Celery app
app = Celery("diavgeia_project")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Disable Celery's logging setup to use Django's configuration
from celery.signals import setup_logging


@setup_logging.connect
def config_loggers(*args, **kwargs):
    """Prevent Celery from overriding Django's logging configuration"""
    pass  # Do nothing, let Django handle logging


# Fix for "ValueError: Cannot invoke RPC on closed channel!"
# This ensures each forked worker process gets a FRESH OpenTelemetry exporter
@worker_process_init.connect(weak=False)
def init_celery_tracing(*args, **kwargs):
    """
    Re-initialize OpenTelemetry in the worker child process.
    This is critical because gRPC channels (used by the OTLP exporter)
    are not fork-safe and break when inherited from the parent process.
    """
    from django.conf import settings

    if not settings.TRANSMIT_TO_JAEGER:
        print(
            "[MUTE] [Worker Child] Jaeger tracing disabled (TRANSMIT_TO_JAEGER=false)"
        )
        return
    try:
        # 1. Force reset the global state in otel_init module
        otel_init_module._global_initialized = False
        otel_init_module._services_initialized.clear()

        # 2. FORCE reset the global TracerProvider
        # This is required because opentelemetry-api refuses to overwrite the provider
        # if one is already set. We must clear it to allow the new provider (with fresh exporter)
        # to be registered.
        trace._TRACER_PROVIDER = None

        # 3. Re-initialize with a fresh gRPC channel
        print("[RETRY] [Worker Child] Re-initializing OpenTelemetry for fork safety...")
        initialize_otel("diavgeia-celery")

        # 4. Ensure instrumentation is active for this process
        # We explicitly instrument here for the worker child logic
        CeleryInstrumentor().instrument()
        print("[OK] [Worker Child] OpenTelemetry re-initialized successfully")
    except Exception as e:
        print(f"[ERROR] [Worker Child] Failed to re-initialize OpenTelemetry: {e}")


# Instrumentation is now handled via signals (worker_process_init, beat_init)
# or conditionally at the top of the file for other processes.


app.autodiscover_tasks()


# Import logging utilities after Django setup

# Task execution tracking - DISABLED FOR TESTING HANG ISSUE
# task_start_times = {}

# DISABLED: These signal handlers might be causing the worker hang
# @task_prerun.connect
# def task_prerun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, **kwds):
#     """Log task start and store start time"""
#     task_start_times[task_id] = time.time()
#     task_logger.log_task_start(sender.name, task_id, args, kwargs)

# @task_postrun.connect
# def task_postrun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, retval=None, state=None, **kwds):
#     """Log task completion"""
#     start_time = task_start_times.pop(task_id, time.time())
#     duration_s = time.time() - start_time
#
#     if state == 'SUCCESS':
#         task_logger.log_task_success(sender.name, task_id, duration_s, retval)
#     # Note: failures are handled by task_failure signal

# @task_failure.connect
# def task_failure_handler(sender=None, task_id=None, exception=None, traceback=None, einfo=None, **kwds):
#     """Log task failure"""
#     start_time = task_start_times.pop(task_id, time.time())
#     duration_s = time.time() - start_time
#     task_logger.log_task_failure(sender.name, task_id, duration_s, exception)

# Configure result backend to store task results
app.conf.update(
    result_backend="django-db",  # Store results in Django's database
    task_track_started=False,  # Track when task starts (stored in result backend)
    result_expires=86400,  # Results expire after 1 day (in seconds)
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    worker_prefetch_multiplier=1,  # Fetch 1 task per worker process (concurrency * 1)
)


# Helper to get auto import schedule time from environment
def get_auto_import_time():
    """
    Get the scheduled time for auto daily import from environment variable.

    Note: Cannot use feature_flags here because Django apps aren't loaded yet
    at module import time (when beat schedule is defined).

    The feature flag AUTO_DAILY_IMPORT_TIME has requires_restart=True for this reason.
    Set via environment variable: AUTO_DAILY_IMPORT_TIME="03:00"

    Falls back to: Environment variable → Default "00:30"
    """
    import os

    time_str = os.environ.get("AUTO_DAILY_IMPORT_TIME", "00:30")
    try:
        hour, minute = time_str.split(":")
        return int(hour), int(minute)
    except (ValueError, AttributeError):
        return 0, 30  # Default to 00:30


auto_import_hour, auto_import_minute = get_auto_import_time()




app.conf.beat_schedule = {
    "persist-analytics-daily": {
        "task": "api.tasks.analytics.persist_analytics_task",
        "schedule": crontab(minute=5, hour="*/4"),  # Run at 5 minutes past every 4th hour
    },
    # NOTE: persist_endpoint_access_log is NOT a periodic task. It is a per-request
    # task fired from api/middleware/security_monitoring.py with the fields of a
    # single access log. Scheduling it via beat with no args only produces failing
    # tasks (missing required arguments). Do not re-add it here.
    # 'import-ministry-decisions-daily': {
    #     'task': 'core.tasks.import_ministry_decisions_task',
    #     'schedule': crontab(hour=3, minute=0),  # Run at 3am daily
    #     'args': ('ministries', None),
    # },
    # 'process-new-documents': {
    #     'task': 'core.tasks.process_documents_task',
    #     'schedule': crontab(hour=5, minute=0),  # Run at 5am daily
    #     'kwargs': {'from_date': 'yesterday', 'limit': 500, 'unprocessed_only': True},
    # },
    # # Add a weekly task to catch any missed documents
    # 'process-missed-documents-weekly': {
    #     'task': 'core.tasks.process_documents_task',
    #     'schedule': crontab(hour=2, minute=0, day_of_week=0),  # Sunday at 2am
    #     'kwargs': {'limit': 1000, 'unprocessed_only': True},  # No date filter = all unprocessed
    # },
    # 'reset-usage-counters-monthly': {
    #     'task': 'users.tasks.reset_monthly_usage',
    #     'schedule': crontab(0, 0, day_of_month='1'),  # First day of month
    # },
    # 'daily-decisions-sync': {
    #     'task': 'core.tasks.daily_decisions_sync_task',
    #     'schedule': crontab(hour=2, minute=30),  # Run at 2:30 AM daily
    #     'kwargs': {'incremental': True},
    # },
    # Optional: Half-hourly incremental sync during business hours
    # 'incremental-decisions-sync': {
    #     'task': 'core.tasks.daily_decisions_sync_task',
    #     'schedule': crontab(minute='*/30', hour='8-18'),  # Every 30 min, 8AM-6PM
    #     'kwargs': {'incremental': True},
    # },
    # 'fetch-company-data-hourly': {
    #     'task': 'core.tasks.process_entities_needing_company_data',
    #     'schedule': crontab(minute=0),  # Every hour
    #     'kwargs': {'limit': 20}  # Process 20 entities per hour
    # },
    # 'verify-entity-extraction-daily': {
    #     'task': 'core.tasks.verify_entity_extraction_status',
    #     'schedule': crontab(hour=2, minute=0),  # Daily at 2 AM
    # },
    # Health Check Tasks - Keep admin data fresh automatically
    # "health-check-recent-decisions": {
    #     "task": "core.tasks.health_check_tasks.check_recent_decisions_health",
    #     "schedule": crontab(minute="0"),  # Every hour
    # },
    # "refresh-problematic-decisions": {
    #     "task": "core.tasks.health_check_tasks.refresh_problematic_decisions",
    #     "schedule": crontab(minute="30"),  # Every hour at :30
    # },
    # "auto-fix-simple-issues": {
    #     "task": "core.tasks.health_check_tasks.auto_fix_simple_issues",
    #     "schedule": crontab(hour="*/6", minute=15),  # Every 6 hours
    # },
    # "cleanup-old-health-checks": {
    #     "task": "core.tasks.health_check_tasks.cleanup_old_health_checks",
    #     "schedule": crontab(
    #         hour=1, minute=0, day_of_week=0
    #     ),  # Weekly on Sunday at 1 AM
    # },
    # Auto Daily Import (Fresh Data) - Runs at configurable time (default 00:30)
    # Time configured via AUTO_DAILY_IMPORT_TIME feature flag
    "auto-daily-import": {
        "task": "core.tasks.tasks_auto_import.auto_daily_import_task",
        "schedule": crontab(hour=auto_import_hour, minute=auto_import_minute),
    },
    # Auto Company GEMI Import — virtuous-cycle recovery heartbeat (daily at 02:00)
    # The cycle is self-sustaining once started (chains itself via Celery link);
    # this beat entry only restarts the chain if it died unexpectedly.
    # Start/stop is controlled entirely by the AUTO_COMPANY_GEMI_IMPORT_ENABLED flag.
    "auto-company-gemi-import": {
        "task": "core.tasks.tasks_auto_import.trigger_next_company_gemi_batch",
        "schedule": crontab(hour=2, minute=0),
    },
}
