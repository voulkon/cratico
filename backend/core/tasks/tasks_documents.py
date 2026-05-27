from celery import shared_task
from core.models.document_analysis import DocumentExtraction, ProcessingStatus
from core.services.opensearch_service import OpenSearchService
from diavgeia_project.logging.logging_helpers import log_document_processing
from loguru import logger

from .tasks_opensearch import index_recent_documents

# ============================================================================
# SINGLE SOURCE OF TRUTH: Use this for processing individual decisions
# ============================================================================


@shared_task(bind=True, max_retries=3)
def run_decision_pipeline_task(
    self, ada: str, force_reprocess: bool = False, skip_opensearch: bool = False
):
    """
    [TARGET] SINGLE SOURCE OF TRUTH for processing one decision through the full pipeline.

    This task ensures ALL stages complete for a decision:
    1. [OK] Ingestion (already done)
    2. [SCAN] Entity Extraction (AFM detection)
    3. [CORP] Company Enrichment (GEMI lookup)
    4. [FILE] Document Processing (PDF download + text extraction)
    5. [FIND] OpenSearch Indexing (make searchable)
    6. [CHART] Coverage Metrics (DateCoverage updates)

    Use this instead of:
    - process_document_task (only does documents)
    - process_document_task_enhanced (only does documents + opensearch)
    - Scattered signals that may or may not fire

    Args:
        ada: Decision ADA to process
        force_reprocess: If True, reprocess even if already completed
        skip_opensearch: If True, skip OpenSearch indexing to reduce infra costs

    Returns:
        DecisionHealthCheck status with component-level results
    """

    from core.services.pipeline_orchestrator import DecisionPipelineOrchestrator

    # Generate task-level ID for Celery task tracking
    task_id = self.request.id if hasattr(self, "request") else "sync"

    # Use contextualize to propagate context to ALL Loguru loggers in this execution
    # This allows filtering in Grafana: {component="celery"} | json | record.extra.task_id="abc-123-def"
    with logger.contextualize(
        task_id=task_id,
        ada=ada,
        task_name="run_decision_pipeline_task",
        force_reprocess=force_reprocess,
    ):
        try:
            logger.debug("Starting FULL pipeline for decision")

            orchestrator = DecisionPipelineOrchestrator()
            health_check = orchestrator.run_pipeline(
                decision_ada=ada,
                force_reprocess=force_reprocess,
                skip_opensearch=skip_opensearch,
            )

            logger.debug(
                "[OK] PIPELINE COMPLETED",
                overall_status=health_check.overall_status,
                ingestion_status=health_check.ingestion_status,
                entities_status=health_check.entities_status,
                relations_status=health_check.relations_status,
                document_extraction_status=health_check.document_extraction_status,
                opensearch_status=health_check.opensearch_status,
                coverage_status=health_check.coverage_status,
            )

            return {
                "success": True,
                "ada": ada,
                "overall_status": health_check.overall_status,
                "health_check_id": health_check.id,
                "components": {
                    "ingestion": health_check.ingestion_status,
                    "entities": health_check.entities_status,
                    "companies": health_check.relations_status,
                    "documents": health_check.document_extraction_status,
                    "opensearch": health_check.opensearch_status,
                    "coverage": health_check.coverage_status,
                },
                "errors": (
                    [
                        msg
                        for component, msg in health_check.findings.items()
                        if msg and isinstance(msg, str)
                    ]
                    if health_check.findings
                    else []
                ),
            }

        except Exception as e:
            logger.error(
                "[ERROR] Failed to run pipeline",
                error=str(e),
                error_type=type(e).__name__,
            )
            raise self.retry(exc=e, countdown=60, max_retries=3)


# ============================================================================
# LEGACY TASKS: These are kept for backward compatibility but should be
# replaced with run_decision_pipeline_task in new code
# ============================================================================


@shared_task(bind=True, max_retries=3)
def process_document_task(self, ada, provider=None):
    """
    Celery task to process a document with structured logging.
    All logs are tagged with document_ada and task_id for easy filtering in Grafana.
    """
    from core.models.decisions import Decision
    from core.services.document_processor import DocumentAnalysisService

    # Use structured logging context for this document processing job
    with log_document_processing(ada, task_id=self.request.id, provider=provider):
        try:
            logger.info("Document processing task started")

            # Get the decision
            decision = Decision.objects.get(ada=ada)
            logger.info(
                "Decision retrieved",
                subject=decision.subject[:50] if decision.subject else "N/A",
            )

            # Process the document with the specified provider
            service = DocumentAnalysisService()
            result = service.process_decision(decision, provider=provider)

            logger.info(
                "Document processing completed",
                success=result.get("success"),
                extraction_status=result.get("extraction_status"),
            )

            return {"success": True, "ada": ada, "result": result}

        except Decision.DoesNotExist:
            logger.warning(
                "Decision not found, will retry", retry_count=self.request.retries
            )
            raise self.retry(
                exc=Exception(f"Decision {ada} not found"), countdown=60, max_retries=3
            )

        except Exception as e:
            logger.error(
                "Document processing failed",
                error=str(e),
                error_type=type(e).__name__,
                retry_count=self.request.retries,
            )
            # Retry a few times
            raise self.retry(exc=e, countdown=60, max_retries=3)


@shared_task
def process_scanned_document_task(decision_ada, provider="GOOGLE_VISION"):
    """Process a scanned document with OCR"""
    # Implementation here


@shared_task
def collect_batch_results(results):
    """Collect and process the results of the batch processing"""
    success_count = sum(1 for r in results if r.get("success", False))
    return {
        "processed": len(results),
        "successful": success_count,
        "failed": len(results) - success_count,
    }


@shared_task
def process_document_batch(ada_list):
    """Process a batch of documents with controlled concurrency"""
    from celery import chord

    # Create a chord that will execute the callback when all tasks complete
    header = [process_document_task.s(ada) for ada in ada_list]
    callback = collect_batch_results.s()
    result = chord(header)(callback)

    return {"task_id": result.id, "processed": len(ada_list)}


@shared_task(bind=True, max_retries=3)
def process_document_task_enhanced(self, ada, provider=None):
    """
    Enhanced Celery task to process a document with OpenSearch indexing and full observability.
    Includes structured logging with metadata for Grafana/Loki filtering.
    """
    from core.models.decisions import Decision
    from core.services.document_processor import DocumentAnalysisService
    from opentelemetry import trace

    # Get tracer for distributed tracing
    tracer = trace.get_tracer(__name__)

    # Use structured logging context for this document processing job
    with log_document_processing(ada, task_id=self.request.id, provider=provider):
        try:
            # Get the decision first
            decision = Decision.objects.get(ada=ada)

            # Start OpenTelemetry span for the entire task
            with tracer.start_as_current_span(
                "process_document_task",
                attributes={
                    "document.ada": ada,
                    "task.id": self.request.id,
                    "provider": provider or "default",
                },
            ) as span:
                # Get trace context for correlation
                span_context = span.get_span_context()
                trace_id = (
                    format(span_context.trace_id, "032x")
                    if span_context.is_valid
                    else None
                )
                span_id = (
                    format(span_context.span_id, "016x")
                    if span_context.is_valid
                    else None
                )

                # Add trace context to logs
                logger.bind(trace_id=trace_id, span_id=span_id).info(
                    "Document processing started",
                    subject=decision.subject[:50] if decision.subject else "N/A",
                )

                # Process the document with the specified provider
                service = DocumentAnalysisService()
                result = service.process_decision(decision, provider=provider)

                if (
                    result.get("success")
                    and result.get("extraction_status") == "COMPLETED"
                ):
                    # Set span attributes for successful processing
                    span.set_attribute("task.status", "success")
                    span.set_status(trace.Status(trace.StatusCode.OK))

                    logger.info("Document processing completed successfully")

                    # Force OpenSearch indexing if the signal didn't work
                    try:
                        extraction = DocumentExtraction.objects.get(
                            decision=decision,
                            extraction_status=ProcessingStatus.COMPLETED,
                        )

                        if extraction.raw_text:
                            opensearch_service = OpenSearchService()

                            # Prepare document for indexing
                            document_data = {
                                "decision_id": decision.id,
                                "ada": decision.ada,
                                "title": decision.subject or "",
                                "content": extraction.raw_text,
                                "organization": (
                                    str(decision.organization)
                                    if decision.organization
                                    else ""
                                ),
                                "decision_type": (
                                    str(decision.decision_type)
                                    if decision.decision_type
                                    else ""
                                ),
                                "issue_date": (
                                    decision.issue_date.isoformat()
                                    if decision.issue_date
                                    else None
                                ),
                                "extraction_date": (
                                    extraction.extraction_date.isoformat()
                                    if extraction.extraction_date
                                    else None
                                ),
                                "character_count": extraction.character_count,
                                "page_count": extraction.page_count,
                            }

                            success = opensearch_service.index_document(document_data)
                            if success:
                                logger.info("Document indexed to OpenSearch")
                            else:
                                logger.warning("Failed to index document to OpenSearch")

                    except DocumentExtraction.DoesNotExist:
                        logger.warning("No completed extraction found")
                    except Exception as e:
                        logger.error("Error indexing to OpenSearch", error=str(e))

                return {"success": True, "ada": ada, "result": result}

        except Decision.DoesNotExist:
            logger.warning(
                "Decision not found, will retry", retry_count=self.request.retries
            )
            raise self.retry(
                exc=Exception(f"Decision {ada} not found"), countdown=60, max_retries=3
            )

        except Exception as e:
            # Set error status on span
            from opentelemetry import trace

            current_span = trace.get_current_span()
            if current_span:
                current_span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                current_span.record_exception(e)

            # Log the error with context
            logger.error(
                "Document processing failed",
                error=str(e),
                error_type=type(e).__name__,
                retry_count=self.request.retries,
            )

            # Retry a few times
            raise self.retry(exc=e, countdown=60, max_retries=3)


@shared_task
def process_documents_task(ada_list=None, from_date=None, limit=50, user_id=None):
    from django.core.management import call_command

    logger.info(f"Processing documents: user_id={user_id}, limit={limit}")

    args = ["--unprocessed-only"]  # Add this flag for the scheduled task

    if ada_list:
        for ada in ada_list:
            args.extend(["--ada", ada])
    if from_date:
        # Handle special 'yesterday' value from the scheduled task
        if from_date == "yesterday":
            from datetime import date, timedelta

            yesterday = date.today() - timedelta(days=1)
            args.extend(["--from-date", yesterday.isoformat()])
        else:
            args.extend(["--from-date", from_date])
    if limit:
        args.extend(["--limit", str(limit)])

    try:
        call_command("process_documents", *args)
        return {"status": "completed", "documents_processed": limit}
    except Exception as e:
        logger.error(f"Error processing documents: {str(e)}")
        return {"status": "error", "message": str(e)}


@shared_task
def process_documents_task_enhanced(
    ada_list=None, from_date=None, limit=50, user_id=None, index_to_opensearch=True
):
    """
    Enhanced task with OpenSearch indexing option
    """
    from django.core.management import call_command

    logger.info(
        f"Processing documents: user_id={user_id}, limit={limit}, opensearch={index_to_opensearch}"
    )

    args = ["--unprocessed-only"]  # Add this flag for the scheduled task

    if ada_list:
        for ada in ada_list:
            args.extend(["--ada", ada])
    if from_date:
        # Handle special 'yesterday' value from the scheduled task
        if from_date == "yesterday":
            from datetime import date, timedelta

            yesterday = date.today() - timedelta(days=1)
            args.extend(["--from-date", yesterday.isoformat()])
        else:
            args.extend(["--from-date", from_date])
    if limit:
        args.extend(["--limit", str(limit)])

    try:
        call_command("process_documents", *args)

        # If indexing is requested, trigger batch indexing
        if index_to_opensearch:
            index_recent_documents.delay(limit=limit)

        return {"status": "completed", "documents_processed": limit}
    except Exception as e:
        logger.error(f"Error processing documents: {str(e)}")
        return {"status": "error", "message": str(e)}


@shared_task
def generate_summary_task(decision_ada, provider="OPENAI"):
    """Generate summary for a document"""
    # Implementation here
