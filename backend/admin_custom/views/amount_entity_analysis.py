"""
Admin view: Amount ↔ Entity Linkage Analysis.

Reads pre-computed results from Django cache (populated by the
compute_amount_entity_analysis Celery task).  Includes a "Refresh
Analysis" button that dispatches a fresh computation.
"""

import json

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.cache import cache
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

from core.tasks.tasks_amount_analysis import CACHE_KEY, CACHE_TTL


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
