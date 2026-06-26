"""
Celery tasks for the Browse API — alphabetical entity browsing.

These tasks handle:
- Warming the available_letters cache (pre-computes distinct first letters)
- Rebuilding browse indexes (sanity / recovery)
"""

import time

from celery import shared_task
from django.core.cache import cache
from django.db import connection
from loguru import logger

from api.redis_keys import BROWSE_AVAILABLE_LETTERS_PREFIX, BROWSE_CACHE_TIMEOUT
from core.constants.search_service import BROWSABLE_ENTITIES, ENTITY_COMPANY


@shared_task(bind=True, name="browse.warm_available_letters_cache")
def warm_available_letters_cache_task(self):
    """
    Pre-compute and cache the set of available first letters for every
    browsable entity type (including "all").

    This avoids a cold-cache hit on the first user request after a deploy
    or after the cache TTL expires (5 min).

    Returns:
        dict with status, duration, and per-type letter counts.
    """
    start_time = time.time()

    self.update_state(
        state="STARTED",
        meta={"status": "Warming available-letters cache for all browse types…"},
    )

    entity_types = ["all"] + list(BROWSABLE_ENTITIES.keys())
    counts: dict[str, int] = {}

    with connection.cursor() as cursor:
        for entity_type in entity_types:
            letters = _compute_available_letters(cursor, entity_type)

            cache_key = f"{BROWSE_AVAILABLE_LETTERS_PREFIX}{entity_type}"
            cache.set(cache_key, letters, BROWSE_CACHE_TIMEOUT)
            counts[entity_type] = len(letters)

    elapsed = time.time() - start_time

    result = {
        "status": "success",
        "duration_seconds": round(elapsed, 2),
        "letters_per_type": counts,
        "message": f"Warmed available-letters cache for {len(entity_types)} types in {elapsed:.1f}s",
    }

    logger.info("browse.warm_available_letters_cache done in {:.1f}s", elapsed)
    return result


@shared_task(bind=True, name="browse.verify_browse_indexes")
def verify_browse_indexes_task(self):
    """
    Verify that all first-letter functional indexes for the Browse API exist.

    Does NOT rebuild anything — just reports status so operators can
    confirm 0074_add_browse_first_letter_indexes was applied.

    Returns:
        dict listing every expected index with its status ("present" | "missing").
    """
    expected_indexes = [
        "idx_browse_org_first_letter",
        "idx_browse_unit_first_letter",
        "idx_browse_signer_first_letter",
        "idx_browse_company_first_letter",
        "idx_browse_companyperson_first_letter",
        "idx_browse_afmentity_first_letter",
    ]

    statuses: dict[str, str] = {}
    with connection.cursor() as cursor:
        for idx_name in expected_indexes:
            cursor.execute(
                "SELECT 1 FROM pg_indexes WHERE indexname = %s", [idx_name]
            )
            statuses[idx_name] = "present" if cursor.fetchone() else "missing"

    # Also verify the IMMUTABLE wrapper function exists
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM pg_proc WHERE proname = 'immutable_unaccent'"
        )
        func_exists = cursor.fetchone() is not None

    all_present = all(s == "present" for s in statuses.values())

    result = {
        "status": "success" if (all_present and func_exists) else "incomplete",
        "indexes": statuses,
        "immutable_unaccent_function": "present" if func_exists else "missing",
        "message": (
            "All browse indexes and helper function present."
            if all_present and func_exists
            else "Some browse indexes or the helper function are missing. "
            "Apply migration 0074_add_browse_first_letter_indexes."
        ),
    }

    logger.info("browse.verify_browse_indexes: %s", result["message"])
    return result


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _compute_available_letters(cursor, entity_type: str) -> list[str]:
    """Return a sorted list of distinct first letters for *entity_type*.

    Uses raw SQL so we can reuse the immutable_unaccent() function that
    the indexes also rely on (Ά→Α, Ί→Ι, etc.).
    """
    letters: set[str] = set()

    if entity_type == "all":
        keys = list(BROWSABLE_ENTITIES.keys())
    else:
        keys = [entity_type]

    for key in keys:
        config = BROWSABLE_ENTITIES[key]
        table = _get_table_name(key)
        letter_field = config.letter_field

        cursor.execute(
            f"SELECT DISTINCT UPPER(immutable_unaccent(LEFT({letter_field}, 1))) "
            f"FROM {table} WHERE {letter_field} IS NOT NULL AND {letter_field} != ''"
        )
        for (ch,) in cursor.fetchall():
            if ch:
                letters.add(ch)

        # Companies: also include first letters from English names
        if key == ENTITY_COMPANY:
            cursor.execute(
                """
                SELECT DISTINCT UPPER(LEFT(elem, 1))
                FROM companies,
                     jsonb_array_elements_text(co_names_en) AS elem
                WHERE co_names_en IS NOT NULL
                  AND jsonb_array_length(co_names_en) > 0
                  AND elem IS NOT NULL
                  AND LEFT(elem, 1) ~ '^[A-Za-z]'
                """
            )
            for (ch,) in cursor.fetchall():
                if ch:
                    letters.add(ch)

    return sorted(letters)


def _get_table_name(entity_key: str) -> str:
    """Map entity key → DB table name."""
    from core.constants.search_service import POSTGRES_FTS_MODELS

    if entity_key not in POSTGRES_FTS_MODELS:
        raise KeyError(f"Unknown entity key '{entity_key}'")
    return POSTGRES_FTS_MODELS[entity_key]["table"]
