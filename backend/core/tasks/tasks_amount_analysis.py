"""
Celery task: Compute the Amount ↔ Entity Linkage Analysis.

Runs 6 aggregating SQL queries against the full DecisionAmountField /
DecisionEntityRelationship tables and stores the results in Django cache
with a 24h TTL so the admin dashboard loads instantly.
"""

import json
from collections import defaultdict

from celery import shared_task
from django.core.cache import cache
from django.db import connection
from loguru import logger

CACHE_KEY = "admin:amount_entity_analysis:v1"
CACHE_TTL = 86400  # 24 hours


# ---------------------------------------------------------------------------
# Helpers (mirror the view for consistency)
# ---------------------------------------------------------------------------

def classify_path(path: str) -> str:
    if not path:
        return "unknown"
    if path.startswith("sponsor[") and ".expenseAmount" in path:
        return "sponsor[N].expenseAmount"
    elif path.startswith("sponsor["):
        return "sponsor[N]"
    elif path.startswith("amountWithKae["):
        return "amountWithKae[N]"
    elif path.startswith("amountWithVATAndKae[") and ".amountWithVAT" in path:
        return "amountWithVATAndKae[N].amountWithVAT"
    elif path.startswith("amountWithVATAndKae["):
        return "amountWithVATAndKae[N]"
    elif path == "amountWithVAT":
        return "amountWithVAT"
    elif path == "awardAmount":
        return "awardAmount"
    elif path == "contractAmount":
        return "contractAmount"
    elif path == "estimatedAmount":
        return "estimatedAmount"
    elif path == "positionSalary":
        return "positionSalary"
    return f"other: {path}"


def _truncate_json_for_display(extra_json, field_name: str, max_chars: int = 2500):
    """Return a display-friendly string from extra_field_values_json."""
    if extra_json is None:
        return "(null)"
    if isinstance(extra_json, str):
        try:
            extra = json.loads(extra_json)
        except (json.JSONDecodeError, TypeError):
            return extra_json[:max_chars]
    else:
        extra = extra_json

    full = json.dumps(extra, indent=2, ensure_ascii=False, default=str)
    if len(full) <= max_chars:
        return full

    search_key = field_name or ""
    key_pos = full.find(f'"{search_key}"')
    if key_pos >= 0:
        start = max(0, key_pos - 400)
        snippet = full[start : start + max_chars]
        return f"...(truncated {len(full):,} chars, showing around '{search_key}')...\n{snippet}"
    return full[:max_chars] + f"\n...({len(full) - max_chars:,} more chars)..."

def _decimal_default(obj):
    """JSON serializer for Decimal types."""
    from decimal import Decimal
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

@shared_task(bind=True, max_retries=1)
def compute_amount_entity_analysis(self):
    """
    Run all 6 analysis queries and cache the result.

    This is a heavyweight task that scans the full DecisionAmountField
    and DecisionEntityRelationship tables.  Results are cached for 24h.
    """
    task_id = self.request.id if hasattr(self, "request") else "sync"
    logger.info(f"Task {task_id}: Starting amount-entity linkage analysis...")
    result: dict = {}

    try:
        # --- SECTION 1: Linkage Rate by Decision Type ---
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    dt.label, dt.uid,
                    COUNT(daf.id) AS total,
                    COUNT(daf.associated_relationship_id) AS linked,
                    COUNT(DISTINCT d.id) AS total_decisions,
                    COUNT(DISTINCT CASE WHEN daf.associated_relationship_id IS NOT NULL
                                   THEN d.id END) AS linked_decisions,
                    COUNT(DISTINCT daf.associated_relationship_id) AS unique_rels
                FROM core_decisionamountfield daf
                JOIN core_decision d ON daf.decision_id = d.id
                JOIN core_acttype dt ON d.decision_type_id = dt.uid
                GROUP BY dt.label, dt.uid
                HAVING COUNT(daf.id) > 0
                ORDER BY total DESC
            """)
            linkage_rows = cursor.fetchall()

        linkage_table = []
        for label, uid, total, linked, total_d, linked_d, unique_rels in linkage_rows:
            link_pct = (linked / total * 100) if total else 0
            d_pct = (linked_d / total_d * 100) if total_d else 0
            linkage_table.append({
                "label": label, "uid": uid,
                "total": total, "linked": linked,
                "link_pct": round(link_pct, 1),
                "total_decisions": total_d, "linked_decisions": linked_d,
                "decisions_pct": round(d_pct, 1),
                "unique_rels": unique_rels,
            })
        result["linkage_table"] = linkage_table
        logger.info(f"Task {task_id}: Section 1 done ({len(linkage_table)} types)")

        # --- SECTION 2: Pattern Distribution (linked only, aggregated) ---
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT dt.label, dt.uid, daf.parent_key_path,
                       COUNT(*) AS cnt,
                       COUNT(DISTINCT daf.associated_relationship_id) AS unique_rels,
                       SUM(daf.amount) AS total_sum
                FROM core_decisionamountfield daf
                JOIN core_decision d ON daf.decision_id = d.id
                JOIN core_acttype dt ON d.decision_type_id = dt.uid
                WHERE daf.associated_relationship_id IS NOT NULL
                GROUP BY dt.label, dt.uid, daf.parent_key_path
                ORDER BY dt.label, cnt DESC
            """)
            pattern_rows = cursor.fetchall()

        type_patterns = defaultdict(lambda: defaultdict(lambda: {
            "count": 0, "unique_rels": 0, "total_sum": 0.0, "variant_count": 0,
        }))
        for label, uid, path, cnt, rels, amt in pattern_rows:
            classified = classify_path(path)
            agg = type_patterns[(label, uid)][classified]
            agg["count"] += cnt
            agg["unique_rels"] += rels
            agg["total_sum"] += float(amt or 0)
            agg["variant_count"] += 1

        pattern_sections = []
        for (label, uid), classified_map in sorted(type_patterns.items()):
            patterns = sorted(classified_map.items(), key=lambda x: -x[1]["count"])
            total = sum(p[1]["count"] for p in patterns)
            total_euros = sum(p[1]["total_sum"] for p in patterns)
            items = []
            for name, agg in patterns[:15]:
                pct = (agg["count"] / total * 100) if total else 0
                items.append({
                    "name": name, "count": agg["count"], "pct": round(pct, 1),
                    "euros": agg["total_sum"], "rels": agg["unique_rels"],
                    "variants": agg["variant_count"],
                })
            pattern_sections.append({
                "label": label, "uid": uid,
                "total": total, "total_euros": total_euros,
                "patterns": items, "more": max(0, len(patterns) - 15),
            })
        result["pattern_sections"] = pattern_sections
        logger.info(f"Task {task_id}: Section 2 done ({len(pattern_sections)} types)")

        # --- SECTION 3: Top Entities by Linked Amount ---
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT dt.label, dt.uid, e.afm, e.name, der.role,
                       COUNT(DISTINCT daf.id) AS fields,
                       SUM(daf.amount) AS total_euros,
                       COUNT(DISTINCT d.id) AS decisions
                FROM core_decisionamountfield daf
                JOIN core_decisionentityrelationship der
                    ON daf.associated_relationship_id = der.id
                JOIN core_afmentity e ON der.entity_id = e.id
                JOIN core_decision d ON daf.decision_id = d.id
                JOIN core_acttype dt ON d.decision_type_id = dt.uid
                GROUP BY dt.label, dt.uid, e.afm, e.name, der.role
                ORDER BY total_euros DESC
            """)
            entity_rows = cursor.fetchall()

        type_entities = defaultdict(list)
        for label, uid, afm, name, role, fields, euros, decs in entity_rows:
            type_entities[(label, uid)].append({
                "afm": afm, "name": name, "role": role,
                "fields": fields, "euros": float(euros), "decisions": decs,
            })

        entity_sections = []
        for (label, uid), entities in sorted(type_entities.items()):
            top = sorted(entities, key=lambda x: -x["euros"])[:5]
            entity_sections.append({"label": label, "uid": uid, "top": top})
        result["entity_sections"] = entity_sections
        logger.info(f"Task {task_id}: Section 3 done ({len(entity_sections)} types)")

        # --- SECTION 4: Role × Pattern Cross-tab ---
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT der.role, daf.parent_key_path,
                       COUNT(*) AS cnt, SUM(daf.amount) AS total_euros,
                       COUNT(DISTINCT e.afm) AS unique_entities
                FROM core_decisionamountfield daf
                JOIN core_decisionentityrelationship der
                    ON daf.associated_relationship_id = der.id
                JOIN core_afmentity e ON der.entity_id = e.id
                GROUP BY der.role, daf.parent_key_path
                ORDER BY der.role, cnt DESC
            """)
            role_rows = cursor.fetchall()

        role_patterns = defaultdict(list)
        for role, path, cnt, euros, ent in role_rows:
            role_patterns[role].append({
                "pattern": classify_path(path),
                "count": cnt,
                "euros": float(euros or 0),
                "entities": ent,
            })

        role_sections = []
        for role in sorted(role_patterns.keys()):
            patterns = role_patterns[role]
            total = sum(p["count"] for p in patterns)
            total_e = sum(p["euros"] for p in patterns)
            items = []
            for p in sorted(patterns, key=lambda x: -x["count"])[:8]:
                items.append({
                    "pattern": p["pattern"], "count": p["count"],
                    "pct": round((p["count"] / total * 100) if total else 0, 1),
                    "euros": p["euros"],
                })
            role_sections.append({
                "role": role, "total": total, "total_euros": total_e,
                "patterns": items,
            })
        result["role_sections"] = role_sections
        logger.info(f"Task {task_id}: Section 4 done ({len(role_sections)} roles)")

        # --- SECTION 5: Unlinked Amounts Summary ---
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT dt.label, dt.uid, daf.parent_key_path,
                       COUNT(*) AS cnt, SUM(daf.amount) AS total_euros,
                       COUNT(DISTINCT d.id) AS unique_decisions
                FROM core_decisionamountfield daf
                JOIN core_decision d ON daf.decision_id = d.id
                JOIN core_acttype dt ON d.decision_type_id = dt.uid
                WHERE daf.associated_relationship_id IS NULL
                GROUP BY dt.label, dt.uid, daf.parent_key_path
                ORDER BY cnt DESC
            """)
            unlinked_rows = cursor.fetchall()

        unlinked_table = []
        for label, uid, path, cnt, euros, decs in unlinked_rows[:40]:
            unlinked_table.append({
                "pattern": classify_path(path), "raw_path": path,
                "count": cnt, "decisions": decs,
                "euros": float(euros or 0),
                "type_label": label, "type_uid": uid,
            })
        result["unlinked_table"] = unlinked_table
        result["unlinked_has_more"] = max(0, len(unlinked_rows) - 40)
        logger.info(f"Task {task_id}: Section 5 done ({len(unlinked_rows)} combos)")

        # --- SECTION 6: Sample Unlinked with raw JSON ---
        with connection.cursor() as cursor:
            cursor.execute("""
                WITH unlinked_summary AS (
                    SELECT dt.label, dt.uid, daf.parent_key_path, COUNT(*) AS cnt
                    FROM core_decisionamountfield daf
                    JOIN core_decision d ON daf.decision_id = d.id
                    JOIN core_acttype dt ON d.decision_type_id = dt.uid
                    WHERE daf.associated_relationship_id IS NULL
                    GROUP BY dt.label, dt.uid, daf.parent_key_path
                ),
                top_combos AS (
                    SELECT label, uid, parent_key_path,
                           ROW_NUMBER() OVER (ORDER BY cnt DESC) AS rn
                    FROM unlinked_summary
                ),
                samples AS (
                    SELECT tc.label, tc.uid, tc.parent_key_path,
                           daf.id AS daf_id, daf.source_field_name,
                           daf.amount, daf.structure_type,
                           d.id AS decision_id, d.ada, d.subject,
                           d.extra_field_values_json,
                           ROW_NUMBER() OVER (
                               PARTITION BY tc.label, tc.uid, tc.parent_key_path
                               ORDER BY daf.amount DESC
                           ) AS sample_rn
                    FROM top_combos tc
                    JOIN core_decisionamountfield daf
                        ON daf.parent_key_path = tc.parent_key_path
                        AND daf.associated_relationship_id IS NULL
                    JOIN core_decision d ON daf.decision_id = d.id
                    JOIN core_acttype dt ON d.decision_type_id = dt.uid
                        AND dt.uid = tc.uid
                    WHERE tc.rn <= 12
                )
                SELECT label, uid, parent_key_path, daf_id, source_field_name,
                       amount, structure_type, decision_id, ada, subject,
                       extra_field_values_json
                FROM samples
                WHERE sample_rn <= 2
                ORDER BY label, parent_key_path, amount DESC
            """)
            sample_rows = cursor.fetchall()

        samples = []
        for row in sample_rows:
            label, uid, path, daf_id, fname, amt, struct, dec_id, ada, subject, extra = row
            samples.append({
                "type_label": label, "type_uid": uid,
                "path": path, "classified": classify_path(path),
                "daf_id": daf_id, "source_field_name": fname,
                "amount": float(amt) if amt else None,
                "structure_type": struct,
                "decision_id": dec_id, "ada": ada,
                "subject": (subject or "(no subject)")[:120],
                "extra_json_display": _truncate_json_for_display(extra, fname),
            })
        result["samples"] = samples
        logger.info(f"Task {task_id}: Section 6 done ({len(samples)} samples)")

        # --- Serialize and cache ---
        # Use custom encoder for Decimal; then store as JSON string in cache
        result_json = json.dumps(result, default=_decimal_default, ensure_ascii=False)
        cache.set(CACHE_KEY, result_json, timeout=CACHE_TTL)
        logger.info(
            f"Task {task_id}: Analysis complete.  "
            f"Result size: {len(result_json):,} chars.  "
            f"Cached under '{CACHE_KEY}' for {CACHE_TTL}s."
        )
        return {
            "success": True,
            "cache_key": CACHE_KEY,
            "ttl_seconds": CACHE_TTL,
            "result_size_chars": len(result_json),
        }

    except Exception as e:
        logger.error(f"Task {task_id}: Analysis failed — {e}")
        raise
