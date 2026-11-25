"""
Admin request profiler.

Paste an organization page URL or an API path and get the same cold/warm
profile the ``profile_request`` command produces, including per-query timings,
cache hit/miss lines and optional EXPLAIN plans.
"""

from admin_custom.sites import admin_site
from core.services.request_profiler import (
    MAX_PROFILE_TARGETS,
    parse_profile_input,
    profile_requests,
)
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render


def _int_value(raw, default: int, low: int, high: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def _float_value(raw, default: float, low: float, high: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def profiler_view(request):
    if not request.user.is_superuser:
        raise PermissionDenied("Only superusers can use the request profiler.")

    form = {
        "urls": "",
        "repeat": 2,
        "explain": True,
        "explain_min_ms": 200,
        "db_info": True,
        "bust_cache": False,
        "authenticated": True,
    }
    errors = []
    expanded = []
    result = None

    if request.method == "POST":
        form.update(
            {
                "urls": request.POST.get("urls", ""),
                "repeat": _int_value(request.POST.get("repeat"), 2, 1, 5),
                "explain": request.POST.get("explain") == "on",
                "explain_min_ms": _float_value(
                    request.POST.get("explain_min_ms"), 200.0, 0.0, 60000.0
                ),
                "db_info": request.POST.get("db_info") == "on",
                "bust_cache": request.POST.get("bust_cache") == "on",
                "authenticated": request.POST.get("authenticated") == "on",
            }
        )

        raw_inputs = [("URLs", form["urls"])]
        har_file = request.FILES.get("har_file")
        if har_file:
            try:
                raw_inputs.append(
                    ("HAR file", har_file.read().decode("utf-8", errors="replace"))
                )
            except Exception as exc:  # noqa: BLE001 - show the failure in the UI
                errors.append(f"HAR file: {exc}")

        for label, text in raw_inputs:
            if not text.strip():
                continue
            try:
                expanded.extend(parse_profile_input(text))
            except ValueError as exc:
                errors.append(f"{label}: {exc}")

        expanded = list(dict.fromkeys(expanded))
        if len(expanded) > MAX_PROFILE_TARGETS:
            errors.append(
                f"Only the first {MAX_PROFILE_TARGETS} API calls will be profiled."
            )
            expanded = expanded[:MAX_PROFILE_TARGETS]

        if not expanded and not errors:
            errors.append("Paste at least one URL, cURL command, or HAR file.")

        if expanded:
            try:
                result = profile_requests(
                    expanded,
                    method="GET",
                    host=request.get_host(),
                    user=request.user if form["authenticated"] else None,
                    repeat=form["repeat"],
                    explain=form["explain"],
                    explain_min_ms=form["explain_min_ms"],
                    explain_top=4,
                    include_db_info=form["db_info"],
                    client_ip=request.META.get("REMOTE_ADDR", "127.0.0.1"),
                    bust_cache=form["bust_cache"],
                )
            except Exception as exc:  # noqa: BLE001 - show the failure in the UI
                errors.append(f"Profiler failed: {exc}")

        if request.POST.get("format") == "json" and result is not None:
            response = JsonResponse(result, json_dumps_params={"indent": 2})
            response["Content-Disposition"] = (
                'attachment; filename="request-profile.json"'
            )
            return response

    context = {
        **admin_site.each_context(request),
        "title": "Request Profiler",
        "form": form,
        "errors": errors,
        "expanded": expanded,
        "result": result,
    }
    return render(request, "admin/request_profiler.html", context)
