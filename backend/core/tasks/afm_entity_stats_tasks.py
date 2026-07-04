"""
Celery task for recomputing AFMEntityStats.

This runs the bulk aggregation in the background so the admin
interface doesn't block while the computation runs.
"""

from typing import Any, Dict

from celery import shared_task
from core.services.afm_entity_stats_service import AFMEntityStatsService
from loguru import logger


@shared_task(name="afm_entity_stats.recompute_all", bind=True)
def recompute_all_entity_stats(self) -> Dict[str, Any]:
    """
    Recompute AFMEntityStats for all AFM entities.

    This uses the AFMEntityStatsService which performs bulk
    aggregation queries — no per-entity loops.

    Returns:
        Dict with created, updated, total counts.
    """
    logger.info(
        "AFMEntityStats recompute task started (celery task id=%s)",
        self.request.id,
    )
    try:
        service = AFMEntityStatsService()
        result = service.compute_all()
        logger.info(
            "AFMEntityStats recompute task completed: created=%d updated=%d total=%d",
            result["created"],
            result["updated"],
            result["total"],
        )
        return {"success": True, **result}
    except Exception as e:
        logger.exception("AFMEntityStats recompute task failed: %s", e)
        return {"success": False, "error": str(e)}
