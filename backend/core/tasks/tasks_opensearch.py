from celery import shared_task
from core.models.document_analysis import DocumentExtraction, ProcessingStatus
from core.services.opensearch_service import OpenSearchService
from loguru import logger


@shared_task
def create_opensearch_backup(repository_name="s3-backup-repo", snapshot_name=None):
    """
    Celery task to create OpenSearch backup
    """
    try:
        opensearch_service = OpenSearchService()

        # Ensure repository is registered
        opensearch_service.register_s3_repository(repository_name)

        # Create snapshot
        result = opensearch_service.create_snapshot(repository_name, snapshot_name)

        if result["success"]:
            logger.info(f"[PKG] Backup completed: {result['snapshot']}")
            return {"status": "success", "snapshot": result["snapshot"]}
        else:
            logger.error(f"[ERROR] Backup failed: {result['error']}")
            return {"status": "failed", "error": result["error"]}

    except Exception as e:
        logger.error(f"[ERROR] Backup task failed: {e}")
        raise


@shared_task
def daily_opensearch_backup():
    """
    Daily automated backup task
    """
    from datetime import datetime

    snapshot_name = f"daily-backup-{datetime.now().strftime('%Y%m%d')}"
    return create_opensearch_backup.delay(snapshot_name=snapshot_name)


@shared_task
def check_opensearch_sync():
    """
    Monitoring task to check OpenSearch sync status
    """
    try:
        # Count completed extractions in PostgreSQL
        pg_count = (
            DocumentExtraction.objects.filter(
                extraction_status=ProcessingStatus.COMPLETED, raw_text__isnull=False
            )
            .exclude(raw_text="")
            .count()
        )

        # Count documents in OpenSearch
        opensearch_service = OpenSearchService()
        os_results = opensearch_service._test_match_all()
        os_count = os_results.get("hits", {}).get("total", {}).get("value", 0)

        diff = pg_count - os_count

        logger.info(
            f"[CHART] Sync status: PostgreSQL={pg_count}, OpenSearch={os_count}, Diff={diff}"
        )

        # If significant difference, trigger sync
        if diff > 10:
            logger.warning(
                f"[WARN]️ Large sync difference detected ({diff}), triggering batch indexing"
            )
            index_recent_documents.delay(limit=diff + 50)

        return {
            "postgresql_count": pg_count,
            "opensearch_count": os_count,
            "difference": diff,
            "sync_triggered": diff > 10,
        }

    except Exception as e:
        logger.error(f"[ERROR] Sync check failed: {e}")
        raise


@shared_task
def index_recent_documents(limit=100):
    """
    Task to index recently processed documents to OpenSearch
    """
    logger.info(f"[SCAN] Starting batch indexing of {limit} recent documents")

    try:
        opensearch_service = OpenSearchService()
        initial_count = (
            opensearch_service._test_match_all()
            .get("hits", {})
            .get("total", {})
            .get("value", 0)
        )

        # Get recently completed extractions
        recent_extractions = (
            DocumentExtraction.objects.filter(
                extraction_status=ProcessingStatus.COMPLETED, raw_text__isnull=False
            )
            .exclude(raw_text="")
            .select_related(
                "decision", "decision__organization", "decision__decision_type"
            )
            .order_by("-extraction_date")[:limit]
        )

        indexed_count = 0

        for extraction in recent_extractions:
            try:
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
                    indexed_count += 1

            except Exception as e:
                logger.error(f"[ERROR] Error indexing {extraction.decision.ada}: {e}")

        final_count = (
            opensearch_service._test_match_all()
            .get("hits", {})
            .get("total", {})
            .get("value", 0)
        )

        logger.info(
            f"[OK] Batch indexing completed: {indexed_count} processed, OpenSearch: {initial_count} → {final_count}"
        )

        return {
            "processed": indexed_count,
            "initial_opensearch_count": initial_count,
            "final_opensearch_count": final_count,
        }

    except Exception as e:
        logger.error(f"[ERROR] Batch indexing failed: {e}")
        raise


@shared_task
def bulk_reindex_missing_documents():
    """
    Task to find and reindex all documents that are in PostgreSQL but missing from OpenSearch
    """
    logger.info("[SCAN] Starting bulk reindex of missing documents")

    try:
        opensearch_service = OpenSearchService()

        # Get initial counts
        initial_os_count = (
            opensearch_service._test_match_all()
            .get("hits", {})
            .get("total", {})
            .get("value", 0)
        )

        # Get all completed extractions with ADAs
        completed_adas = set(
            DocumentExtraction.objects.filter(
                extraction_status=ProcessingStatus.COMPLETED, raw_text__isnull=False
            )
            .exclude(raw_text="")
            .values_list("decision__ada", flat=True)
        )

        # Get all indexed ADAs from OpenSearch
        try:
            # Query all documents from OpenSearch
            response = opensearch_service._test_match_all(size=10000)
            indexed_adas = set(
                hit["_source"]["ada"]
                for hit in response.get("hits", {}).get("hits", [])
            )
        except Exception as e:
            logger.error(f"Error fetching indexed ADAs: {e}")
            indexed_adas = set()

        # Find missing ADAs
        missing_adas = completed_adas - indexed_adas

        logger.info(
            f"[CHART] Found {len(missing_adas)} documents missing from OpenSearch"
        )

        if not missing_adas:
            logger.info("[OK] No missing documents found, all synced!")
            return {
                "processed": 0,
                "missing_count": 0,
                "initial_opensearch_count": initial_os_count,
                "final_opensearch_count": initial_os_count,
            }

        # Reindex missing documents
        indexed_count = 0
        failed_count = 0

        for ada in missing_adas:
            try:
                extraction = DocumentExtraction.objects.select_related(
                    "decision", "decision__organization", "decision__decision_type"
                ).get(decision__ada=ada, extraction_status=ProcessingStatus.COMPLETED)

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
                    indexed_count += 1
                else:
                    failed_count += 1

            except DocumentExtraction.DoesNotExist:
                logger.warning(f"Extraction not found for ADA {ada}")
                failed_count += 1
            except Exception as e:
                logger.error(f"[ERROR] Error indexing {ada}: {e}")
                failed_count += 1

        final_os_count = (
            opensearch_service._test_match_all()
            .get("hits", {})
            .get("total", {})
            .get("value", 0)
        )

        logger.info(
            f"[OK] Bulk reindex completed: {indexed_count} indexed, {failed_count} failed, "
            f"OpenSearch: {initial_os_count} → {final_os_count}"
        )

        return {
            "processed": indexed_count,
            "failed": failed_count,
            "missing_count": len(missing_adas),
            "initial_opensearch_count": initial_os_count,
            "final_opensearch_count": final_os_count,
        }

    except Exception as e:
        logger.error(f"[ERROR] Bulk reindex failed: {e}")
        raise


@shared_task
def reindex_specific_adas(adas_list):
    """
    Task to reindex specific documents by their ADAs

    Args:
        adas_list: List of ADA strings to reindex
    """
    logger.info(f"[SCAN] Starting reindex of {len(adas_list)} specific documents")

    try:
        opensearch_service = OpenSearchService()
        indexed_count = 0
        failed_count = 0

        for ada in adas_list:
            try:
                extraction = DocumentExtraction.objects.select_related(
                    "decision", "decision__organization", "decision__decision_type"
                ).get(decision__ada=ada, extraction_status=ProcessingStatus.COMPLETED)

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
                    indexed_count += 1
                    logger.debug(f"[OK] Indexed {ada}")
                else:
                    failed_count += 1
                    logger.warning(f"[ERROR] Failed to index {ada}")

            except DocumentExtraction.DoesNotExist:
                logger.warning(f"Extraction not found for ADA {ada}")
                failed_count += 1
            except Exception as e:
                logger.error(f"[ERROR] Error indexing {ada}: {e}")
                failed_count += 1

        logger.info(
            f"[OK] Specific reindex completed: {indexed_count} indexed, {failed_count} failed"
        )

        return {
            "processed": indexed_count,
            "failed": failed_count,
            "total": len(adas_list),
        }

    except Exception as e:
        logger.error(f"[ERROR] Specific reindex failed: {e}")
        raise
