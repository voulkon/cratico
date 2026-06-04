"""
Async Celery tasks for bulk data migrations on the Decision table.

These tasks are designed for the 20M+ row Decision table.  Each task
processes a single batch and then re‑enqueues itself for the next batch,
so no single task invocation holds a DB transaction open for too long
and the work survives worker restarts.

Usage
-----
From a management command or Django shell:

    from core.tasks import recompute_issue_date_fields_task
    recompute_issue_date_fields_task.delay()

Or with a dry‑run first:

    recompute_issue_date_fields_task.delay(dry_run=True)

Progress is reported via ``self.update_state()`` so you can monitor it
through Flower / Celery inspect.
"""

from __future__ import annotations

from django.conf import settings
from django.db import connection
from celery import shared_task
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _affected_rows(
    table: str,
    where_clause: str,
    params: dict | None = None,
) -> int:
    """Return how many rows match *where_clause*."""
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {where_clause}",
            params or {},
        )
        return cursor.fetchone()[0]


# ---------------------------------------------------------------------------
# 1.  recompute_issue_date_fields  (day / month / year)
# ---------------------------------------------------------------------------


@shared_task(
    bind=True,
    name="migration.recompute_issue_date_fields",
    max_retries=0,  # self‑chaining; retries are handled by re‑enqueue
    acks_late=False,
)
def recompute_issue_date_fields_task(
    self,
    dry_run: bool = False,
    batch_size: int = 50_000,
    last_id: int = 0,
    total_affected: int | None = None,
    total_updated: int = 0,
) -> dict:
    """
    Recompute ``issue_date_day``, ``issue_date_month`` and
    ``issue_date_year`` for Decision rows where the stored value
    disagrees with the Europe/Athens‑localised date.

    Uses key‑based pagination (``id > last_id``) instead of OFFSET
    so that the scan remains stable even as rows are fixed and drop
    out of the matching set.

    Parameters
    ----------
    dry_run : bool
        If True, count affected rows and return without writing.
    batch_size : int
        Rows per batch (default 50 000).
    last_id : int
        Internal – highest ``id`` processed so far (key‑based pagination).
    total_affected : int or None
        Internal – cached count of rows to fix (for progress only).
    total_updated : int
        Internal – running total of fixed rows.
    """
    tz = settings.TIME_ZONE
    where = (
        "issue_date IS NOT NULL"
        " AND issue_date_day IS DISTINCT FROM"
        " (issue_date AT TIME ZONE %(tz)s)::date"
    )
    params = {"tz": tz}

    # --- first invocation: count affected rows ---
    if total_affected is None:
        total_affected = _affected_rows("core_decision", where, params)
        logger.info(
            "recompute_issue_date_fields | %s rows to fix (dry_run=%s)",
            total_affected,
            dry_run,
        )

    if dry_run:
        return {
            "status": "dry_run",
            "total_affected": total_affected,
            "message": (
                f"Would update {total_affected:,} rows "
                f"(TIME_ZONE={tz}).  Re-run with dry_run=False."
            ),
        }

    if total_affected == 0:
        return {"status": "done", "total_updated": 0}

    # --- update one batch (key‑based pagination: id > last_id) ---
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE core_decision
            SET
                issue_date_day   = (issue_date AT TIME ZONE %(tz)s)::date,
                issue_date_month = DATE_TRUNC('month',
                                        issue_date AT TIME ZONE %(tz)s
                                    )::date,
                issue_date_year  = EXTRACT(
                                        YEAR FROM
                                        (issue_date AT TIME ZONE %(tz)s)
                                    )::integer
            WHERE id IN (
                SELECT id
                FROM core_decision
                WHERE id > %(last_id)s AND {}
                ORDER BY id
                LIMIT %(batch_size)s
            )
            RETURNING id
            """.format(
                where
            ),
            {**params, "batch_size": batch_size, "last_id": last_id},
        )
        updated_ids = [row[0] for row in cursor.fetchall()]

    rows_in_batch = len(updated_ids)
    new_last_id = updated_ids[-1] if updated_ids else last_id
    total_updated += rows_in_batch

    # --- progress report ---
    pct = round(total_updated / total_affected * 100, 2) if total_affected else 100
    self.update_state(
        state="PROGRESS",
        meta={
            "total_updated": total_updated,
            "total_affected": total_affected,
            "pct": pct,
            "last_id": new_last_id,
        },
    )
    logger.info(
        "recompute_issue_date_fields | last_id=%s → +%s rows  "
        "(%s/%s, %s%%)",
        new_last_id,
        rows_in_batch,
        total_updated,
        total_affected,
        pct,
    )

    # --- chain next batch or finish ---
    if rows_in_batch == 0:
        return {
            "status": "done",
            "total_updated": total_updated,
            "total_affected": total_affected,
            "message": (
                f"Updated {total_updated:,} Decision rows. "
                "Next: backfill_date_coverage --reset"
            ),
        }

    recompute_issue_date_fields_task.apply_async(
        kwargs={
            "dry_run": False,
            "batch_size": batch_size,
            "last_id": new_last_id,
            "total_affected": total_affected,
            "total_updated": total_updated,
        },
    )
    return {
        "status": "chained",
        "total_updated": total_updated,
        "last_id": new_last_id,
    }


# ---------------------------------------------------------------------------
# 2.  recompute_publish_date_fields  (day only)
# ---------------------------------------------------------------------------


@shared_task(
    bind=True,
    name="migration.recompute_publish_date_fields",
    max_retries=0,
    acks_late=False,
)
def recompute_publish_date_fields_task(
    self,
    dry_run: bool = False,
    batch_size: int = 50_000,
    last_id: int = 0,
    total_affected: int | None = None,
    total_updated: int = 0,
) -> dict:
    """
    Recompute ``publish_date_day`` for Decision rows where the stored
    value is missing or disagrees with the Athens‑localised date of
    ``publish_timestamp``.

    Uses key‑based pagination (``id > last_id``) instead of OFFSET
    so that the scan remains stable even as rows are fixed and drop
    out of the matching set.

    Parameters
    ----------
    dry_run : bool
        If True, count affected rows and return without writing.
    batch_size : int
        Rows per batch (default 50 000).
    last_id : int
        Internal – highest ``id`` processed so far (key‑based pagination).
    total_affected : int or None
        Internal – cached count of rows to fix (for progress only).
    total_updated : int
        Internal – running total of fixed rows.
    """
    tz = settings.TIME_ZONE
    where = (
        "publish_timestamp IS NOT NULL"
        " AND ("
        "   publish_date_day IS NULL"
        "   OR publish_date_day IS DISTINCT FROM"
        "      (publish_timestamp AT TIME ZONE %(tz)s)::date"
        ")"
    )
    params = {"tz": tz}

    if total_affected is None:
        total_affected = _affected_rows("core_decision", where, params)
        logger.info(
            "recompute_publish_date_fields | %s rows to fix (dry_run=%s)",
            total_affected,
            dry_run,
        )

    if dry_run:
        return {
            "status": "dry_run",
            "total_affected": total_affected,
            "message": (
                f"Would update {total_affected:,} rows "
                f"(TIME_ZONE={tz}).  Re-run with dry_run=False."
            ),
        }

    if total_affected == 0:
        return {"status": "done", "total_updated": 0}

    # --- update one batch (key‑based pagination: id > last_id) ---
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE core_decision
            SET publish_date_day =
                (publish_timestamp AT TIME ZONE %(tz)s)::date
            WHERE id IN (
                SELECT id
                FROM core_decision
                WHERE id > %(last_id)s AND {}
                ORDER BY id
                LIMIT %(batch_size)s
            )
            RETURNING id
            """.format(
                where
            ),
            {**params, "batch_size": batch_size, "last_id": last_id},
        )
        updated_ids = [row[0] for row in cursor.fetchall()]

    rows_in_batch = len(updated_ids)
    new_last_id = updated_ids[-1] if updated_ids else last_id
    total_updated += rows_in_batch

    pct = round(total_updated / total_affected * 100, 2) if total_affected else 100
    self.update_state(
        state="PROGRESS",
        meta={
            "total_updated": total_updated,
            "total_affected": total_affected,
            "pct": pct,
            "last_id": new_last_id,
        },
    )
    logger.info(
        "recompute_publish_date_fields | last_id=%s → +%s rows  "
        "(%s/%s, %s%%)",
        new_last_id,
        rows_in_batch,
        total_updated,
        total_affected,
        pct,
    )

    if rows_in_batch == 0:
        return {
            "status": "done",
            "total_updated": total_updated,
            "total_affected": total_affected,
            "message": (
                f"Updated {total_updated:,} Decision rows. "
                "Restart the backfill scheduler so BackfillCoverageService "
                "picks up the corrected data."
            ),
        }

    recompute_publish_date_fields_task.apply_async(
        kwargs={
            "dry_run": False,
            "batch_size": batch_size,
            "last_id": new_last_id,
            "total_affected": total_affected,
            "total_updated": total_updated,
        },
    )
    return {
        "status": "chained",
        "total_updated": total_updated,
        "last_id": new_last_id,
    }
