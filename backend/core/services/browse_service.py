"""
Browse Service

Provides alphabetical browsing of entities (organizations, signers, units,
companies, company persons, and AFM entities).

Uses BROWSABLE_ENTITIES from core.constants.search_service as the single
source of truth for which entities are browsable.

Single-type queries use the Django ORM with functional indexes.
The "all" type uses a SQL UNION ALL query so that pagination and sorting
happen at the database level (avoids loading every row into Python).
"""

from typing import Any, Dict, List, Optional

from api.redis_keys import BROWSE_AVAILABLE_LETTERS_PREFIX, BROWSE_CACHE_TIMEOUT
from core.constants.search_service import (
    BROWSABLE_ENTITIES,
    BrowsableEntityConfig,
    ENTITY_AFM_ENTITY,
    ENTITY_COMPANY,
    ENTITY_COMPANY_PERSON,
    ENTITY_ORGANIZATION,
    ENTITY_SIGNER,
    ENTITY_UNIT,
)
from core.models.companies import Company, CompanyPerson
from core.models.entities import AFMEntity
from core.models.organizations import Organization, Signer, Unit
from django.core.cache import cache
from django.db import connection
from django.db.models import Q, QuerySet


# Mapping from BROWSABLE_ENTITIES key → Django model class.
# All models from POSTGRES_FTS_MODELS that also appear in BROWSABLE_ENTITIES
# must have an entry here.
_ENTITY_MODEL_MAP = {
    ENTITY_ORGANIZATION: Organization,
    ENTITY_UNIT: Unit,
    ENTITY_SIGNER: Signer,
    ENTITY_COMPANY: Company,
    ENTITY_COMPANY_PERSON: CompanyPerson,
    ENTITY_AFM_ENTITY: AFMEntity,
}


class BrowseService:
    """Service for alphabetical browsing of entities."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def browse_entities(
        self,
        entity_type: str = "all",
        letter: Optional[str] = None,
        query: Optional[str] = None,
        sort: str = "asc",
        offset: int = 0,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        Return paginated alphabetical entity listings.

        Args:
            entity_type: One of BROWSABLE_ENTITY_TYPES ('all', 'organization', ...).
            letter: First-letter filter (Greek Α-Ω or Latin A-Z). None = all letters.
            query: Free-text prefix filter (e.g. "Tes" matches "Tesla", "Τέσσερα").
                   Applied on top of letter filtering. Case-insensitive.
            sort: 'asc' or 'desc'.
            offset: Pagination offset.
            limit: Page size (capped at 200).

        Returns:
            {
                "results": [...],
                "has_more": bool,
                "total_count": int,
                "available_letters": [...],
            }
        """
        limit = min(limit, 200)

        # Validate entity_type
        if entity_type not in BROWSABLE_ENTITIES and entity_type != "all":
            raise ValueError(
                f"Invalid entity_type '{entity_type}'. "
                f"Valid types: {list(BROWSABLE_ENTITIES.keys()) + ['all']}"
            )

        # ----------------------------------------------------------
        # Single entity type: straightforward ORM query
        # ----------------------------------------------------------
        if entity_type != "all":
            qs = self._build_browse_queryset(entity_type, letter, query, sort)
            total_count = qs.count()
            page = qs[offset : offset + limit + 1]  # fetch one extra
            has_more = len(page) > limit
            results = [
                self._serialize_result(entity_type, obj)
                for obj in page[:limit]
            ]
            available_letters = self._get_available_letters(entity_type)

            return {
                "results": results,
                "has_more": has_more,
                "total_count": total_count,
                "available_letters": available_letters,
            }

        # ----------------------------------------------------------
        # "all" — UNION ALL across every browsable entity type.
        # Pagination and sorting happen in SQL to avoid loading
        # every row into Python.
        # ----------------------------------------------------------
        union_sql, params = self._build_union_query(letter, query, sort)
        direction = "DESC" if sort == "desc" else "ASC"

        with connection.cursor() as cursor:
            # Total count across all types
            cursor.execute(
                f"SELECT COUNT(*) FROM ({union_sql}) AS merged", params
            )
            total_count = cursor.fetchone()[0]

            # Fetch one extra row to determine has_more
            cursor.execute(
                f"SELECT id, text, type, sort_key FROM ({union_sql}) AS merged "
                f"ORDER BY sort_key {direction} LIMIT %s OFFSET %s",
                [*params, limit + 1, offset],
            )
            rows = cursor.fetchall()

        has_more = len(rows) > limit
        results = [
            {
                "id": row[0],
                "text": row[1] or "",
                "type": row[2],
                "sort_key": row[3] or "",
            }
            for row in rows[:limit]
        ]

        available_letters = self._get_available_letters("all")

        return {
            "results": results,
            "has_more": has_more,
            "total_count": total_count,
            "available_letters": available_letters,
        }

    # ------------------------------------------------------------------
    # Queryset building (single-type path)
    # ------------------------------------------------------------------

    def _build_browse_queryset(
        self, entity_key: str, letter: Optional[str],
        query: Optional[str], sort: str
    ) -> QuerySet:
        """Build a filtered, ordered queryset for a single entity type."""
        config = BROWSABLE_ENTITIES[entity_key]
        model = self._get_model(entity_key)

        qs = model.objects.all()

        # Companies: exclude rows without an AFM (id_field is "afm" and the
        # frontend navigates to /entity/afm/<afm>, so empty AFM is useless).
        if entity_key == ENTITY_COMPANY:
            qs = qs.exclude(afm__isnull=True).exclude(afm="")

        # --- Free-text prefix filter ---
        # e.g. query="Tes" matches entities whose display fields start with "Tes"
        if query and query.strip():
            q_term = query.strip()
            if entity_key == ENTITY_COMPANY:
                # Greek name prefix OR English name prefix (JSONB array).
                # Use EXISTS on jsonb_array_elements_text for reliable JSONB
                # matching (icontains on a JSONField is a text-level substring
                # match on the serialized JSON and is unreliable).
                qs = qs.extra(
                    where=[
                        "co_name_el ILIKE %s OR EXISTS ("
                        "  SELECT 1 FROM jsonb_array_elements_text(co_names_en) elem"
                        "  WHERE elem ILIKE %s)"
                    ],
                    params=[f"{q_term}%", f"{q_term}%"],
                )
            else:
                prefix_q = Q()
                for field in config.display_fields:
                    prefix_q |= Q(**{f"{field}__istartswith": q_term})
                qs = qs.filter(prefix_q)

        # --- Letter filter ---
        # Uses functional index on UPPER(immutable_unaccent(LEFT(field, 1))).
        # immutable_unaccent() collapses accented Greek (Ά→Α, Ί→Ι) so letter=Α
        # matches both "Αθήνα" and "Άργος". The IMMUTABLE wrapper is required
        # because raw unaccent() is only STABLE and cannot be indexed.
        if letter and len(letter) == 1:
            letter_field = config.letter_field
            upper_letter = letter.upper()

            if entity_key == ENTITY_COMPANY:
                # Greek name first letter OR English name first letter.
                # Both conditions are OR-ed so a company discoverable only via
                # its English name is still returned.
                qs = qs.extra(
                    where=[
                        f"UPPER(immutable_unaccent(LEFT({letter_field}, 1))) = UPPER(immutable_unaccent(%s))"
                        f" OR EXISTS ("
                        f"  SELECT 1 FROM jsonb_array_elements_text(co_names_en) elem"
                        f"  WHERE UPPER(LEFT(elem, 1)) = UPPER(%s))"
                    ],
                    params=[upper_letter, upper_letter],
                )
            else:
                qs = qs.extra(
                    where=[
                        f"UPPER(immutable_unaccent(LEFT({letter_field}, 1))) = UPPER(immutable_unaccent(%s))"
                    ],
                    params=[upper_letter],
                )

        # Sorting
        sort_fields = list(config.sort_fields)
        if sort == "desc":
            sort_fields = [f"-{f}" for f in sort_fields]
        qs = qs.order_by(*sort_fields)

        return qs

    # ------------------------------------------------------------------
    # UNION query building ("all" path)
    # ------------------------------------------------------------------

    def _build_union_query(
        self, letter: Optional[str], query: Optional[str], sort: str
    ) -> tuple[str, list]:
        """
        Build a UNION ALL SQL query across all browsable entity types.

        Returns (sql, params) for the inner union (without ORDER BY / LIMIT).
        Each subquery selects: id, text, type, sort_key.

        The display text and sort key are built with array_to_string so that
        NULL / empty fields are skipped — matching the Python serialization
        in _serialize_result.
        """
        subqueries: List[str] = []
        params: list = []

        for key in BROWSABLE_ENTITIES:
            config = BROWSABLE_ENTITIES[key]
            model = self._get_model(key)
            table = model._meta.db_table
            id_field = config.id_field
            display_fields = config.display_fields
            sort_fields = config.sort_fields
            type_label = config.type_label
            letter_field = config.letter_field

            # Display text: array_to_string skips NULL elements
            display_expr = "array_to_string(ARRAY[" + ", ".join(
                f"NULLIF({f}, '')" for f in display_fields
            ) + "], ', ')"

            # Sort key: lowercase, space-separated
            sort_expr = "array_to_string(ARRAY[" + ", ".join(
                f"LOWER(NULLIF({f}, ''))" for f in sort_fields
            ) + "], ' ')"

            where_clauses: List[str] = []

            # Free-text prefix filter
            if query and query.strip():
                q_term = query.strip()
                prefix_clauses = [f"{f} ILIKE %s" for f in display_fields]
                param_count = len(display_fields)
                if key == ENTITY_COMPANY:
                    prefix_clauses.append(
                        "EXISTS (SELECT 1 FROM jsonb_array_elements_text(co_names_en) elem"
                        " WHERE elem ILIKE %s)"
                    )
                    param_count += 1
                where_clauses.append("(" + " OR ".join(prefix_clauses) + ")")
                params.extend([f"{q_term}%"] * param_count)

            # Letter filter
            if letter and len(letter) == 1:
                upper_letter = letter.upper()
                if key == ENTITY_COMPANY:
                    where_clauses.append(
                        f"(UPPER(immutable_unaccent(LEFT({letter_field}, 1))) = UPPER(immutable_unaccent(%s))"
                        f" OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(co_names_en) elem"
                        f" WHERE UPPER(LEFT(elem, 1)) = UPPER(%s)))"
                    )
                    params.extend([upper_letter, upper_letter])
                else:
                    where_clauses.append(
                        f"UPPER(immutable_unaccent(LEFT({letter_field}, 1))) = UPPER(immutable_unaccent(%s))"
                    )
                    params.append(upper_letter)

            # Companies: exclude null/empty AFM
            if key == ENTITY_COMPANY:
                where_clauses.append("afm IS NOT NULL AND afm != ''")

            where_sql = (
                " AND ".join(f"({c})" for c in where_clauses)
                if where_clauses
                else "TRUE"
            )

            subqueries.append(
                f"SELECT {id_field}::text AS id, {display_expr} AS text, "
                f"'{type_label}' AS type, {sort_expr} AS sort_key "
                f"FROM {table} WHERE {where_sql}"
            )

        union_sql = " UNION ALL ".join(subqueries)
        return union_sql, params

    # ------------------------------------------------------------------
    # Available letters
    # ------------------------------------------------------------------

    def _get_available_letters(self, entity_type: str) -> List[str]:
        """
        Return distinct first letters that actually have results.

        For entity_type="all", this is the union across all browsable types.
        Results are cached for 5 minutes.
        """
        cache_key = f"{BROWSE_AVAILABLE_LETTERS_PREFIX}{entity_type}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        keys = (
            list(BROWSABLE_ENTITIES.keys())
            if entity_type == "all"
            else [entity_type]
        )

        letters: set[str] = set()
        for key in keys:
            config = BROWSABLE_ENTITIES[key]
            model = self._get_model(key)
            letter_field = config.letter_field

            # Collect first letters from the primary letter field.
            # Uses immutable_unaccent() so Ά→Α, Ί→Ι etc. (matches the index).
            qs = (
                model.objects.extra(
                    select={"_fl": f"UPPER(immutable_unaccent(LEFT({letter_field}, 1)))"}
                )
                .values_list("_fl", flat=True)
                .distinct()
            )
            letters.update(l for l in qs if l)

            # Companies: also include first letters from English names
            if key == ENTITY_COMPANY:
                # Use raw SQL to extract first letters from co_names_en JSON array
                # This is much faster than iterating all company rows in Python
                with connection.cursor() as cursor:
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

        result = sorted(letters)
        cache.set(cache_key, result, BROWSE_CACHE_TIMEOUT)
        return result

    # ------------------------------------------------------------------
    # Serialization (single-type path)
    # ------------------------------------------------------------------

    def _serialize_result(
        self, entity_key: str, instance: Any
    ) -> Dict[str, Any]:
        """Convert a model instance into the API response dict."""
        config = BROWSABLE_ENTITIES[entity_key]
        id_field = config.id_field
        display_fields = config.display_fields
        sort_fields = config.sort_fields
        type_label = config.type_label

        # Build display text from display_fields
        display_parts = []
        for f in display_fields:
            val = getattr(instance, f, None)
            if val:
                display_parts.append(str(val))
        display_text = ", ".join(display_parts) if display_parts else ""

        # Build sort key from sort_fields (without direction prefix)
        sort_parts = []
        for f in sort_fields:
            val = getattr(instance, f, None)
            if val:
                sort_parts.append(str(val).lower())
        sort_key = " ".join(sort_parts) if sort_parts else ""

        return {
            "id": str(getattr(instance, id_field, "")),
            "text": display_text,
            "type": type_label,
            "sort_key": sort_key,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_model(entity_key: str):
        """Resolve a BROWSABLE_ENTITIES key to a Django model class."""
        if entity_key not in _ENTITY_MODEL_MAP:
            raise KeyError(
                f"Unknown entity key '{entity_key}'. "
                f"Known keys: {list(_ENTITY_MODEL_MAP.keys())}"
            )
        return _ENTITY_MODEL_MAP[entity_key]
