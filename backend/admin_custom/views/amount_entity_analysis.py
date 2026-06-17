"""
Admin view: Amount ↔ Entity Linkage Analysis.

Reads pre-computed results from Django cache (populated by the
compute_amount_entity_analysis Celery task).  Includes a "Refresh
Analysis" button that dispatches a fresh computation, and a per-section
"Refresh Samples" button that re-runs just the sample SQL on demand.
"""

import json

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.cache import cache
from django.db import connection
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import reverse

from core.tasks.tasks_amount_analysis import (
    CACHE_KEY,
    CACHE_TTL,
    _truncate_json_for_display,
    classify_path,
)


@staff_member_required
def amount_entity_analysis(request):
    """Render the Amount ↔ Entity Linkage Analysis dashboard."""

    # Handle "Refresh" POST
    if request.method == "POST" and request.POST.get("action") == "refresh":
        from core.tasks.tasks_amount_analysis import compute_amount_entity_analysis

        task = compute_amount_entity_analysis.delay()
        messages.success(
            request,
            f"Analysis refresh dispatched (task {task.id}). "
            "Results will appear here when the task completes (typically < 30s). "
            "Reload this page to see them.",
        )
        return HttpResponseRedirect(reverse("admin:amount_entity_analysis"))

    # Try cache
    cached_json = cache.get(CACHE_KEY)
    if cached_json:
        try:
            context = json.loads(cached_json)
        except (json.JSONDecodeError, TypeError):
            context = {}
        context["cached"] = True
        context["cache_key"] = CACHE_KEY
        context["cache_ttl_hours"] = CACHE_TTL // 3600
    else:
        context = {"cached": False}

    return render(request, "admin/amount_entity_analysis.html", context)


@staff_member_required
def refresh_samples_api(request):
    """
    AJAX endpoint: re-run only the Section 6 sample query and return fresh results.

    GET params:
        type_uid  – if provided, return unlinked samples for that specific
                    decision type (useful for drilling down from Section 1).
                    Otherwise return the top-12-combos view.

    Also patches the cached analysis JSON so a full page reload picks up the
    new samples without re-running the entire heavyweight task.
    """
    type_uid = request.GET.get("type_uid", "").strip()

    try:
        if type_uid:
            # --- Per-type drill-down: unlinked amounts for ONE decision type ---
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT
                        dt.label,
                        dt.uid,
                        daf.parent_key_path,
                        daf.id AS daf_id,
                        daf.source_field_name,
                        daf.amount,
                        daf.structure_type,
                        d.id AS decision_id,
                        d.ada,
                        d.subject,
                        d.extra_field_values_json
                    FROM core_decisionamountfield daf
                    JOIN core_decision d ON daf.decision_id = d.id
                    JOIN core_acttype dt ON d.decision_type_id = dt.uid
                    WHERE daf.associated_relationship_id IS NULL
                      AND dt.uid = %s
                    ORDER BY daf.amount DESC NULLS LAST
                    LIMIT 15
                """, [type_uid])
                sample_rows = cursor.fetchall()

                # Also get a summary: how many unlinked total, how many per pattern
                cursor.execute("""
                    SELECT daf.parent_key_path, COUNT(*) AS cnt,
                           SUM(daf.amount) AS total_euros,
                           COUNT(DISTINCT d.id) AS decisions
                    FROM core_decisionamountfield daf
                    JOIN core_decision d ON daf.decision_id = d.id
                    JOIN core_acttype dt ON d.decision_type_id = dt.uid
                    WHERE daf.associated_relationship_id IS NULL
                      AND dt.uid = %s
                    GROUP BY daf.parent_key_path
                    ORDER BY cnt DESC
                """, [type_uid])
                summary_rows = cursor.fetchall()

            summary = []
            for path, cnt, euros, decs in summary_rows:
                summary.append({
                    "classified": classify_path(path),
                    "raw_path": path,
                    "count": cnt,
                    "euros": float(euros or 0),
                    "decisions": decs,
                })

        else:
            # --- Original top-combos query (all types) ---
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
            summary = None

        samples = []
        for row in sample_rows:
            label, uid, path, daf_id, fname, amt, struct, dec_id, ada, subject, extra = row
            # Full, untruncated JSON for verification
            extra_full = json.dumps(
                extra if not isinstance(extra, str) else
                (json.loads(extra) if extra else None),
                indent=2, ensure_ascii=False, default=str,
            ) if extra else None
            samples.append({
                "type_label": label,
                "type_uid": uid,
                "path": path,
                "classified": classify_path(path),
                "daf_id": daf_id,
                "source_field_name": fname,
                "amount": float(amt) if amt else None,
                "structure_type": struct,
                "decision_id": dec_id,
                "ada": ada,
                "subject": (subject or "(no subject)")[:120],
                "extra_json_display": _truncate_json_for_display(extra, fname),
                "extra_json_full": extra_full,
                "api_url": f"https://diavgeia.gov.gr/luminapi/api/decisions/{ada}" if ada else None,
            })

        # --- Patch the existing cache so a full reload also gets fresh samples ---
        cached_json = cache.get(CACHE_KEY)
        if cached_json:
            try:
                result = json.loads(cached_json)
                result["samples"] = samples
                cache.set(CACHE_KEY, json.dumps(result, ensure_ascii=False), timeout=CACHE_TTL)
            except (json.JSONDecodeError, TypeError):
                pass  # cache is corrupt; leave it alone

        response_data = {"success": True, "samples": samples, "count": len(samples)}
        if summary is not None:
            response_data["summary"] = summary
        return JsonResponse(response_data)

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)
