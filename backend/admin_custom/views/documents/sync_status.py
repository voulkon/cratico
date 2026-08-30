from core.models.decisions import Decision
from core.models.document_analysis import DocumentExtraction, ProcessingStatus
from core.services.opensearch_service import OpenSearchService
from core.tasks.tasks_documents import process_document_task_enhanced
from core.tasks.tasks_opensearch import index_recent_documents
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import redirect, render
from loguru import logger


@staff_member_required
def sync_status_dashboard(request):
    """Dashboard for monitoring and managing PostgreSQL <-> OpenSearch sync"""

    opensearch_service = OpenSearchService()

    # Handle actions
    if request.method == "POST":
        action = request.POST.get("action")

        if action == "reindex_all":
            # Trigger bulk reindexing for all missing documents
            try:
                missing_count = _get_missing_count()
                task = index_recent_documents.delay(limit=missing_count + 100)
                messages.success(
                    request,
                    f"Bulk reindexing initiated for ~{missing_count} documents. Task ID: {task.id}",
                )
                logger.info(f"Bulk reindexing triggered by user, task ID: {task.id}")
            except Exception as e:
                messages.error(request, f"Failed to trigger reindexing: {str(e)}")
                logger.error(f"Failed to trigger bulk reindexing: {e}")

        elif action == "reindex_selected":
            # Reindex specific decisions
            selected_adas = request.POST.getlist("selected_decisions")
            if selected_adas:
                try:
                    reindexed_count = 0
                    failed_count = 0

                    for ada in selected_adas:
                        try:
                            extraction = DocumentExtraction.objects.select_related(
                                "decision",
                                "decision__organization",
                                "decision__decision_type",
                            ).get(
                                decision__ada=ada,
                                extraction_status=ProcessingStatus.COMPLETED,
                            )

                            document_data = {
                                "decision_id": extraction.decision.id,
                                "ada": extraction.decision.ada,
                                "title": extraction.decision.subject or "",
                                "content": extraction.raw_text,
                                "organization": (
                                    str(extraction.decision.organization)
                                    if extraction.decision.organization
                                    else ""
                                ),
                                "decision_type": (
                                    str(extraction.decision.decision_type)
                                    if extraction.decision.decision_type
                                    else ""
                                ),
                                "issue_date": (
                                    extraction.decision.issue_date.isoformat()
                                    if extraction.decision.issue_date
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
                                reindexed_count += 1
                            else:
                                failed_count += 1
                        except Exception as e:
                            failed_count += 1
                            logger.error(f"Failed to reindex {ada}: {e}")

                    messages.success(
                        request,
                        f"Reindexed {reindexed_count} documents. {failed_count} failed.",
                    )
                except Exception as e:
                    messages.error(
                        request, f"Error during selective reindexing: {str(e)}"
                    )
            else:
                messages.warning(request, "No decisions selected for reindexing.")

        elif action == "extract_all":
            # Trigger bulk extraction for all missing decisions
            try:
                # Get decisions without extraction
                decisions_without = Decision.objects.filter(
                    text_extraction__isnull=True
                ).count()

                # Get failed extractions
                failed_count = DocumentExtraction.objects.filter(
                    extraction_status=ProcessingStatus.FAILED
                ).count()

                total_to_extract = decisions_without + failed_count

                # Get batch size from request, default to 500
                try:
                    batch_size = int(request.POST.get("batch_size", 500))
                    batch_size = max(
                        1, min(batch_size, 1000)
                    )  # Clamp between 1 and 1000
                except (ValueError, TypeError):
                    batch_size = 500

                queued = 0

                # Queue decisions without extraction
                for decision in Decision.objects.filter(text_extraction__isnull=True)[
                    :batch_size
                ]:
                    process_document_task_enhanced.delay(decision.ada)
                    queued += 1

                # Queue failed extractions for retry
                for extraction in DocumentExtraction.objects.filter(
                    extraction_status=ProcessingStatus.FAILED
                ).select_related("decision")[:batch_size]:
                    process_document_task_enhanced.delay(extraction.decision.ada)
                    queued += 1

                messages.success(
                    request,
                    f"Queued {queued} decisions for text extraction (of {total_to_extract} total). "
                    f"More will be processed automatically. Check back in a few minutes!",
                )
                logger.info(f"Bulk extraction triggered by user: {queued} tasks queued")
            except Exception as e:
                messages.error(request, f"Failed to trigger extraction: {str(e)}")
                logger.error(f"Failed to trigger bulk extraction: {e}")

        elif action == "extract_selected":
            # Process specific decisions through FULL pipeline (not just documents)
            selected_adas = request.POST.getlist("selected_decisions")
            if selected_adas:
                try:
                    from core.tasks.tasks_documents import run_decision_pipeline_task

                    queued_count = 0

                    for ada in selected_adas:
                        try:
                            # Queue FULL pipeline: entities, companies, documents, opensearch
                            run_decision_pipeline_task.delay(ada, force_reprocess=True)
                            queued_count += 1
                        except Exception as e:
                            logger.error(f"Failed to queue pipeline for {ada}: {e}")

                    messages.success(
                        request,
                        f"[LAUNCH] Queued {queued_count} decisions for FULL pipeline processing "
                        f"(entities, companies, documents, OpenSearch). "
                        f"Check DecisionHealthCheck admin for component-level status.",
                    )
                except Exception as e:
                    messages.error(request, f"Error queueing pipeline: {str(e)}")
            else:
                messages.warning(request, "No decisions selected for processing.")

        return redirect("admin:sync_status_dashboard")

    # Get counts and stats
    try:
        # PostgreSQL counts - Step 1: Decisions
        total_decisions = Decision.objects.count()

        # Step 2: DocumentExtraction status breakdown
        decisions_with_extraction = Decision.objects.filter(
            text_extraction__isnull=False
        ).count()
        decisions_without_extraction = total_decisions - decisions_with_extraction

        pending_extractions = DocumentExtraction.objects.filter(
            extraction_status__in=[
                ProcessingStatus.PENDING,
                ProcessingStatus.PROCESSING,
            ]
        ).count()

        failed_extractions = DocumentExtraction.objects.filter(
            extraction_status=ProcessingStatus.FAILED
        ).count()

        completed_extractions = (
            DocumentExtraction.objects.filter(
                extraction_status=ProcessingStatus.COMPLETED, raw_text__isnull=False
            )
            .exclude(raw_text="")
            .count()
        )

        # Step 3: OpenSearch count
        opensearch_unavailable = not opensearch_service.is_enabled
        os_results = opensearch_service._test_match_all()
        opensearch_count = os_results.get("hits", {}).get("total", {}).get("value", 0)

        # Calculate gaps
        extraction_gap = decisions_without_extraction + failed_extractions
        indexing_gap = completed_extractions - opensearch_count

        # Calculate percentages for each stage
        extraction_percentage = (
            (decisions_with_extraction / total_decisions * 100)
            if total_decisions > 0
            else 0
        )
        completion_percentage = (
            (completed_extractions / total_decisions * 100)
            if total_decisions > 0
            else 0
        )
        indexing_percentage = (
            (opensearch_count / total_decisions * 100) if total_decisions > 0 else 0
        )

        # Get sample of missing documents (paginated)
        page = int(request.GET.get("page", 1))
        view_type = request.GET.get("view", "indexing")  # 'indexing' or 'extraction'
        page_size = 50
        offset = (page - 1) * page_size

        if view_type == "extraction":
            # Show decisions without extraction or failed
            missing_decisions = _get_decisions_needing_extraction(offset, page_size)
            total_missing = extraction_gap
        else:
            # Show decisions with extraction but not indexed
            missing_decisions = _get_missing_decisions(
                opensearch_service, offset, page_size
            )
            total_missing = len(_get_all_missing_adas(opensearch_service))

        total_pages = (
            (total_missing + page_size - 1) // page_size if total_missing > 0 else 1
        )

        context = {
            # Pipeline stats
            "total_decisions": total_decisions,
            "decisions_without_extraction": decisions_without_extraction,
            "pending_extractions": pending_extractions,
            "failed_extractions": failed_extractions,
            "completed_extractions": completed_extractions,
            "opensearch_count": opensearch_count,
            "opensearch_unavailable": opensearch_unavailable,
            # Gaps
            "extraction_gap": extraction_gap,
            "indexing_gap": indexing_gap,
            # Percentages
            "extraction_percentage": round(extraction_percentage, 2),
            "completion_percentage": round(completion_percentage, 2),
            "indexing_percentage": round(indexing_percentage, 2),
            # Pagination
            "missing_decisions": missing_decisions,
            "page": page,
            "total_pages": total_pages,
            "total_missing": total_missing,
            "has_previous": page > 1,
            "has_next": page < total_pages,
            "previous_page": page - 1,
            "next_page": page + 1,
            "view_type": view_type,
        }

    except Exception as e:
        logger.error(f"Error loading sync dashboard: {e}")
        messages.error(request, f"Error loading dashboard: {str(e)}")
        context = {
            "total_decisions": 0,
            "decisions_without_extraction": 0,
            "pending_extractions": 0,
            "failed_extractions": 0,
            "completed_extractions": 0,
            "opensearch_count": 0,
            "extraction_gap": 0,
            "indexing_gap": 0,
            "extraction_percentage": 0,
            "completion_percentage": 0,
            "indexing_percentage": 0,
            "missing_decisions": [],
            "page": 1,
            "total_pages": 1,
            "total_missing": 0,
            "has_previous": False,
            "has_next": False,
            "previous_page": 0,
            "next_page": 2,
            "view_type": "indexing",
            "error": str(e),
        }

    return render(request, "admin/sync_status_dashboard.html", context)


def _get_missing_count():
    """Get count of documents in DB but not in OpenSearch"""
    opensearch_service = OpenSearchService()
    missing_adas = _get_all_missing_adas(opensearch_service)
    return len(missing_adas)


def _get_all_missing_adas(opensearch_service):
    """Get all ADAs that exist in PostgreSQL but not in OpenSearch"""
    # Get all completed extractions with their ADAs
    completed_adas = set(
        DocumentExtraction.objects.filter(
            extraction_status=ProcessingStatus.COMPLETED, raw_text__isnull=False
        )
        .exclude(raw_text="")
        .values_list("decision__ada", flat=True)
    )

    # Get all indexed ADAs from OpenSearch
    try:
        # Query all documents from OpenSearch (this might need pagination for large datasets)
        response = opensearch_service._test_match_all(
            size=10000
        )  # Adjust size as needed
        indexed_adas = set(
            hit["_source"]["ada"] for hit in response.get("hits", {}).get("hits", [])
        )
    except Exception as e:
        logger.error(f"Error fetching indexed ADAs from OpenSearch: {e}")
        indexed_adas = set()

    # Find the difference
    missing_adas = completed_adas - indexed_adas
    return list(missing_adas)


def _get_decisions_needing_extraction(offset=0, limit=50):
    """Get decisions that need text extraction (no extraction or failed)"""
    # Get decisions without extraction
    without_extraction = (
        Decision.objects.filter(text_extraction__isnull=True)
        .select_related("organization", "decision_type")
        .order_by("-issue_date")[offset : offset + limit]
    )

    # Get decisions with failed extraction
    failed_extraction_ids = DocumentExtraction.objects.filter(
        extraction_status=ProcessingStatus.FAILED
    ).values_list("decision_id", flat=True)

    with_failed = (
        Decision.objects.filter(id__in=failed_extraction_ids)
        .select_related("organization", "decision_type")
        .prefetch_related("text_extraction")
        .order_by("-issue_date")[:limit]
    )

    # Combine and format
    result = []

    for decision in without_extraction:
        result.append(
            {
                "id": decision.id,
                "ada": decision.ada,
                "subject": decision.subject,
                "organization": (
                    str(decision.organization) if decision.organization else "N/A"
                ),
                "decision_type": (
                    str(decision.decision_type) if decision.decision_type else "N/A"
                ),
                "issue_date": decision.issue_date,
                "extraction_status": "NO_EXTRACTION",
                "extraction_date": None,
                "error_message": None,
            }
        )

    for decision in with_failed:
        extraction = decision.text_extraction
        result.append(
            {
                "id": decision.id,
                "ada": decision.ada,
                "subject": decision.subject,
                "organization": (
                    str(decision.organization) if decision.organization else "N/A"
                ),
                "decision_type": (
                    str(decision.decision_type) if decision.decision_type else "N/A"
                ),
                "issue_date": decision.issue_date,
                "extraction_status": "FAILED",
                "extraction_date": extraction.extraction_date if extraction else None,
                "error_message": (
                    extraction.error_message[:100]
                    if extraction and extraction.error_message
                    else None
                ),
            }
        )

    return result[:limit]


def _get_missing_decisions(opensearch_service, offset=0, limit=50):
    """Get decisions that exist in PostgreSQL but not in OpenSearch (paginated)"""
    missing_adas = _get_all_missing_adas(opensearch_service)

    # Paginate
    paginated_adas = missing_adas[offset : offset + limit]

    # Fetch the actual decision objects
    decisions = (
        Decision.objects.filter(ada__in=paginated_adas)
        .select_related("organization", "decision_type")
        .prefetch_related("text_extraction")
        .order_by("-issue_date")[:limit]
    )

    # Enrich with extraction info
    result = []
    for decision in decisions:
        try:
            extraction = decision.text_extraction
            result.append(
                {
                    "id": decision.id,
                    "ada": decision.ada,
                    "subject": decision.subject,
                    "organization": (
                        str(decision.organization) if decision.organization else "N/A"
                    ),
                    "decision_type": (
                        str(decision.decision_type) if decision.decision_type else "N/A"
                    ),
                    "issue_date": decision.issue_date,
                    "extraction_status": "COMPLETED",
                    "character_count": (
                        extraction.character_count if extraction else None
                    ),
                    "page_count": extraction.page_count if extraction else None,
                    "extraction_date": (
                        extraction.extraction_date if extraction else None
                    ),
                }
            )
        except DocumentExtraction.DoesNotExist:
            result.append(
                {
                    "id": decision.id,
                    "ada": decision.ada,
                    "subject": decision.subject,
                    "organization": (
                        str(decision.organization) if decision.organization else "N/A"
                    ),
                    "decision_type": (
                        str(decision.decision_type) if decision.decision_type else "N/A"
                    ),
                    "issue_date": decision.issue_date,
                    "extraction_status": "NO_EXTRACTION",
                    "character_count": None,
                    "page_count": None,
                    "extraction_date": None,
                }
            )

    return result
