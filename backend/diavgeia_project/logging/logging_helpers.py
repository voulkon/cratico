"""
Helper utilities and examples for structured logging with Loki metadata.

This module provides context managers and utilities for adding structured
metadata to logs for better filtering and querying in Grafana/Loki.
"""

import uuid
from contextlib import contextmanager
from typing import Optional

from loguru import logger


@contextmanager
def log_document_processing(
    document_ada: str, task_id: Optional[str] = None, provider: Optional[str] = None
):
    """
    Context manager for document processing that adds structured metadata to all logs.

    Usage:
        with log_document_processing(ada, task_id=self.request.id, provider="PYMUPDF"):
            logger.info("Starting extraction")
            # ... processing code ...
            logger.info("Extraction complete")

    All logs within this context will have document_ada and task_id in Loki metadata.
    Query in Grafana: {application="diavgeia-backend"} | document_ada="ΨΨ4746ΛΕΑΩ-ΩΞΨ"
    """
    # Bind metadata to logger for all logs in this context
    bound_logger = logger.bind(
        document_ada=document_ada,
        task_id=task_id or "unknown",
        job_type="document_processing",
        provider=provider,
    )

    # Use patch to temporarily make this the default logger behavior
    with bound_logger.contextualize():
        yield bound_logger


@contextmanager
def log_decision_import(
    job_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    organization_id: Optional[str] = None,
):
    """
    Context manager for decision import operations.

    Usage:
        with log_decision_import(job_id=123, batch_id=batch_uuid):
            logger.info("Starting import")
            # ... import code ...
            logger.info("Import complete", decisions_imported=count)

    Query in Grafana: {application="diavgeia-backend"} | job_type="decision_import" | batch_id="..."
    """
    bound_logger = logger.bind(
        job_id=job_id,
        batch_id=batch_id or str(uuid.uuid4()),
        job_type="decision_import",
        organization_id=organization_id,
    )

    with bound_logger.contextualize():
        yield bound_logger


@contextmanager
def log_with_trace(trace_id: str, span_id: Optional[str] = None):
    """
    Context manager for adding OpenTelemetry trace context to logs.

    Usage:
        from opentelemetry import trace

        current_span = trace.get_current_span()
        span_context = current_span.get_span_context()

        with log_with_trace(
            trace_id=format(span_context.trace_id, '032x'),
            span_id=format(span_context.span_id, '016x')
        ):
            logger.info("Processing with trace context")

    Query in Grafana: {application="diavgeia-backend"} | trace_id="abc123..."
    """
    bound_logger = logger.bind(trace_id=trace_id, span_id=span_id or "unknown")

    with bound_logger.contextualize():
        yield bound_logger


def log_with_user_context(
    user_id: Optional[int] = None, username: Optional[str] = None
):
    """
    Create a logger bound with user context.

    Usage:
        user_logger = log_with_user_context(user_id=request.user.id, username=request.user.username)
        user_logger.info("User action performed", action="document_processed")

    Query in Grafana: {application="diavgeia-backend"} | user_id="123"
    """
    return logger.bind(user_id=user_id, username=username)


# Example usage patterns for common scenarios
"""
EXAMPLE 1: Document Processing Task with full context
------------------------------------------------------
from diavgeia_project.logging.logging_helpers import log_document_processing

@shared_task(bind=True, max_retries=3)
def process_document_task(self, ada, provider=None):
    with log_document_processing(ada, task_id=self.request.id, provider=provider) as task_logger:
        task_logger.info("Document processing started")

        try:
            decision = Decision.objects.get(ada=ada)
            task_logger.info("Decision found", subject=decision.subject)

            service = DocumentAnalysisService()
            result = service.process_decision(decision, provider=provider)

            task_logger.info("Processing complete",
                           success=result['success'],
                           extraction_status=result.get('extraction_status'))

            return result
        except Exception as e:
            task_logger.error("Processing failed", error=str(e), exc_info=True)
            raise


EXAMPLE 2: Batch Import with batch tracking
--------------------------------------------
from diavgeia_project.logging.logging_helpers import log_decision_import
import uuid

@shared_task
def import_decisions_task(start_date, end_date, organization_id=None, job_id=None):
    batch_id = str(uuid.uuid4())

    with log_decision_import(job_id=job_id, batch_id=batch_id, organization_id=organization_id) as import_logger:
        import_logger.info("Import job started",
                          start_date=start_date,
                          end_date=end_date)

        # ... import logic ...

        import_logger.info("Import job complete",
                          decisions_imported=count,
                          duration_seconds=elapsed)


EXAMPLE 3: Manual binding for specific log lines
-------------------------------------------------
# When you only want specific logs to have metadata, not all logs in a context
logger.bind(document_ada=ada, step="download").info("Downloading PDF")
logger.bind(document_ada=ada, step="extract").info("Extracting text", page_count=10)
logger.bind(document_ada=ada, step="complete").info("Processing finished")


EXAMPLE 4: Combining with OpenTelemetry traces
-----------------------------------------------
from opentelemetry import trace
from diavgeia_project.logging.logging_helpers import log_document_processing, log_with_trace

@shared_task(bind=True)
def process_document_task(self, ada, provider=None):
    current_span = trace.get_current_span()
    span_context = current_span.get_span_context()

    trace_id = format(span_context.trace_id, '032x')
    span_id = format(span_context.span_id, '016x')

    with log_document_processing(ada, task_id=self.request.id, provider=provider):
        with log_with_trace(trace_id=trace_id, span_id=span_id):
            logger.info("Processing with full observability context")
            # All logs now have document_ada, task_id, trace_id, and span_id


GRAFANA LOKI QUERIES
--------------------

1. All logs for a specific document:
   {application="diavgeia-backend"} | document_ada="ΨΨ4746ΛΕΑΩ-ΩΞΨ"

2. All logs for a specific Celery task:
   {application="diavgeia-backend"} | task_id="abc-123-def"

3. All document processing jobs:
   {application="diavgeia-backend"} | job_type="document_processing"

4. All errors during document processing:
   {application="diavgeia-backend", level="ERROR"} | job_type="document_processing"

5. Specific document with errors only:
   {application="diavgeia-backend", level="ERROR"} | document_ada="ΨΨ4746ΛΕΑΩ-ΩΞΨ"

6. All logs for a batch import:
   {application="diavgeia-backend"} | batch_id="550e8400-e29b-41d4-a716-446655440000"

7. User-triggered actions:
   {application="diavgeia-backend"} | user_id="123"

8. Trace across services (if using OpenTelemetry):
   {application="diavgeia-backend"} | trace_id="abc123def456..."

9. Timeline of a document processing (with visualization):
   {application="diavgeia-backend"} | document_ada="XYZ" | json

10. Count errors per document:
    sum(count_over_time({application="diavgeia-backend", level="ERROR"} | document_ada!="" [1h])) by (document_ada)


LOKI VS PROMTAIL COMPARISON
----------------------------

Now that you have loki_logger_handler, here's what changed:

BEFORE (with Promtail):
- Logs → Docker stdout → Promtail scrapes → Loki
- Promtail adds labels based on container name
- Limited ability to add dynamic metadata per log line
- Extra hop in the pipeline

AFTER (with loki_logger_handler):
- Logs → LokiLoggerHandler → Loki directly
- Can add structured metadata per log line (document_ada, task_id, etc.)
- More efficient - no intermediate collection
- Better for application-level metadata

RECOMMENDATION:
- Keep loki_logger_handler for application logs (what you're doing now)
- Promtail is still useful for:
  * Non-Python services (nginx, postgres, etc.)
  * System logs
  * Services you don't control
- You can run both! They complement each other.

ARCHITECTURE DECISION:
For your Django backend and Celery workers:
[OK] Use loki_logger_handler (direct push with structured metadata)

For other services:
[OK] Use Promtail (for infrastructure logs, nginx, databases, etc.)
"""
