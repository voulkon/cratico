"""
Admin request profiler.

Paste page URLs, API paths, cURL commands or a HAR export and get the same
cold/warm profile the ``profile_request`` command produces. The work runs in a
Celery task so the admin request does not hit the nginx/gunicorn 504 timeout;
the page polls the task state and renders the result when it is ready.
"""

from celery.result import AsyncResult
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import redirect, render

from admin_custom.sites import admin_site
from core.services.request_profiler import MAX_PROFILE_TARGETS, parse_profile_input
from diavgeia_project.celery import app as celery_app


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
    job_id = request.GET.get("job")
    job_state = None
    download_url = None

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
            options = {
                "method": "GET",
                "host": request.get_host(),
                "user": request.user.username if form["authenticated"] else None,
                "repeat": form["repeat"],
                "explain": form["explain"],
                "explain_min_ms": form["explain_min_ms"],
                "explain_top": 4,
                "include_db_info": form["db_info"],
                "client_ip": request.META.get("REMOTE_ADDR", "127.0.0.1"),
                "bust_cache": form["bust_cache"],
            }
            try:
                task = celery_app.send_task(
                    "admin.profile_request", args=[expanded, options]
                )
            except Exception as exc:  # noqa: BLE001 - broker may be unavailable
                errors.append(f"Could not queue the profiler task: {exc}")
            else:
                return redirect(f"{request.path}?job={task.id}")

    elif job_id:
        try:
            task = AsyncResult(job_id, app=celery_app)
            job_state = task.state
            if task.state == "SUCCESS":
                result = task.result
                download_url = f"{request.path}?job={job_id}&download=1"
                if request.GET.get("download"):
                    response = JsonResponse(result, json_dumps_params={"indent": 2})
                    response["Content-Disposition"] = (
                        'attachment; filename="request-profile.json"'
                    )
                    return response
            elif task.state == "FAILURE":
                errors.append(f"Profiler task failed: {task.info}")
        except Exception as exc:  # noqa: BLE001 - show the failure in the UI
            errors.append(f"Could not read task state: {exc}")

    context = {
        **admin_site.each_context(request),
        "title": "Request Profiler",
        "form": form,
        "errors": errors,
        "expanded": expanded,
        "result": result,
        "job_id": job_id,
        "job_state": job_state,
        "download_url": download_url,
    }
    return render(request, "admin/request_profiler.html", context)


def profiler_status_view(request, job_id):
    if not request.user.is_superuser:
        raise PermissionDenied("Only superusers can use the request profiler.")

    try:
        task = AsyncResult(job_id, app=celery_app)
        state = task.state
        payload = {"state": state}
        if state == "STARTED" and isinstance(task.info, dict):
            payload["status"] = task.info.get("status")
        if state == "FAILURE":
            payload["error"] = str(task.info)
        return JsonResponse(payload)
    except Exception as exc:  # noqa: BLE001 - keep the poll loop alive
        return JsonResponse({"state": "ERROR", "error": str(exc)}, status=500)
