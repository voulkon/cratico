"""
Admin request profiler.

Paste page URLs, API paths, cURL commands or a HAR export and get the same
cold/warm profile the ``profile_request`` command produces. The work runs in a
Celery task and is persisted in ``RequestProfileRun`` so the page can poll,
revoke, and compare runs across improvements.
"""

import json
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from admin_custom.sites import admin_site
from core.models.request_profile_run import RequestProfileRun
from core.services.request_profiler import MAX_PROFILE_TARGETS, parse_profile_input
from diavgeia_project.celery import app as celery_app

_SUCCESS = RequestProfileRun.Status.SUCCESS
_FAILURE = RequestProfileRun.Status.FAILURE
_REVOKED = RequestProfileRun.Status.REVOKED
_PENDING = RequestProfileRun.Status.PENDING
_STARTED = RequestProfileRun.Status.STARTED


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


def _get_run(run_id):
    if not run_id:
        return None
    try:
        return RequestProfileRun.objects.filter(pk=run_id).first()
    except (ValidationError, ValueError):
        return None


def _previous_run(run):
    if run is None or run.status != _SUCCESS:
        return None
    try:
        return (
            RequestProfileRun.objects.filter(
                status=_SUCCESS,
                targets=run.targets,
                created_at__lt=run.created_at,
            )
            .order_by("-created_at")
            .first()
        )
    except Exception:  # noqa: BLE001 - history is optional
        return None


def _history(limit=20):
    runs = list(
        RequestProfileRun.objects.select_related("user").order_by("-created_at")[:limit]
    )
    seen = {}
    for run in runs:
        run.previous_id = None
        if run.status != _SUCCESS:
            continue
        key = json.dumps(run.targets or [], sort_keys=True)
        if key in seen:
            run.previous_id = seen[key].id
        seen[key] = run
    return runs


def _revoke_run(run):
    try:
        celery_app.control.revoke(run.task_id, terminate=True, signal="SIGKILL")
    except Exception:  # noqa: BLE001 - the DB status is the source of truth
        pass
    if not run.is_terminal:
        run.status = _REVOKED
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "finished_at"])


def _delta(current, baseline):
    if current is None or baseline is None:
        return None
    return float(current) - float(baseline)


def _delta_class(delta):
    if delta is None:
        return ""
    if delta < 0:
        return "better"
    if delta > 0:
        return "worse"
    return ""


def _display(value, digits=1):
    if value is None:
        return "—"
    return f"{float(value):.{digits}f}"


def _display_delta(value, digits=1):
    if value is None:
        return "—"
    return f"{float(value):+.{digits}f}"


def _compare_rows(a, b):
    def index(run):
        rows = {}
        for request in (run.result or {}).get("requests") or []:
            key = (request.get("path") or "", int(request.get("iteration") or 1))
            rows[key] = request
        return rows

    current_rows = index(a)
    baseline_rows = index(b)
    keys = sorted(set(current_rows) | set(baseline_rows), key=lambda item: item)
    rows = []
    for path, iteration in keys:
        current = current_rows.get((path, iteration), {})
        baseline = baseline_rows.get((path, iteration), {})
        wall_delta = _delta(current.get("wall_ms"), baseline.get("wall_ms"))
        db_delta = _delta(current.get("db_ms"), baseline.get("db_ms"))
        query_delta = _delta(current.get("query_count"), baseline.get("query_count"))
        rows.append(
            {
                "path": path,
                "iteration": iteration,
                "current_wall_display": _display(current.get("wall_ms")),
                "baseline_wall_display": _display(baseline.get("wall_ms")),
                "wall_delta_display": _display_delta(wall_delta),
                "wall_class": _delta_class(wall_delta),
                "current_db_display": _display(current.get("db_ms")),
                "baseline_db_display": _display(baseline.get("db_ms")),
                "db_delta_display": _display_delta(db_delta),
                "db_class": _delta_class(db_delta),
                "current_queries_display": _display(current.get("query_count"), 0),
                "baseline_queries_display": _display(baseline.get("query_count"), 0),
                "query_delta_display": (
                    "—" if query_delta is None else f"{int(query_delta):+d}"
                ),
                "query_class": _delta_class(query_delta),
                "current_status": current.get("status"),
                "baseline_status": baseline.get("status"),
            }
        )

    wall_delta = _delta(a.total_wall_ms, b.total_wall_ms)
    db_delta = _delta(a.total_db_ms, b.total_db_ms)
    totals = {
        "current_wall_display": _display(a.total_wall_ms),
        "baseline_wall_display": _display(b.total_wall_ms),
        "wall_delta_display": _display_delta(wall_delta),
        "current_db_display": _display(a.total_db_ms),
        "baseline_db_display": _display(b.total_db_ms),
        "db_delta_display": _display_delta(db_delta),
        "wall_class": _delta_class(wall_delta),
        "db_class": _delta_class(db_delta),
    }
    return rows, totals


def profiler_view(request):
    if not request.user.is_superuser:
        raise PermissionDenied("Only superusers can use the request profiler.")

    form = {
        "urls": "",
        "label": "",
        "repeat": 2,
        "explain": True,
        "explain_min_ms": 200,
        "statement_timeout_ms": 0,
        "db_info": True,
        "bust_cache": False,
        "authenticated": True,
    }
    errors = []
    expanded = []
    result = None
    run = None
    job_id = request.GET.get("job")
    job_state = None
    download_url = None
    compare_id = None

    if request.method == "POST" and request.POST.get("action") == "revoke":
        run = _get_run(request.POST.get("run_id"))
        if run is None:
            errors.append("Run not found.")
        else:
            _revoke_run(run)
            return redirect(f"{request.path}?job={run.id}")

    if request.method == "POST":
        form.update(
            {
                "urls": request.POST.get("urls", ""),
                "label": (request.POST.get("label") or "").strip()[:200],
                "repeat": _int_value(request.POST.get("repeat"), 2, 1, 5),
                "explain": request.POST.get("explain") == "on",
                "explain_min_ms": _float_value(
                    request.POST.get("explain_min_ms"), 200.0, 0.0, 60000.0
                ),
                "statement_timeout_ms": _int_value(
                    request.POST.get("statement_timeout_ms"), 0, 0, 600000
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
            run_id = str(uuid.uuid4())
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
                "statement_timeout_ms": form["statement_timeout_ms"] or None,
            }
            run = RequestProfileRun.objects.create(
                id=run_id,
                task_id=run_id,
                user=request.user if form["authenticated"] else None,
                label=form["label"],
                targets=expanded,
                options=options,
                status=_PENDING,
            )
            try:
                celery_app.send_task(
                    "admin.profile_request",
                    args=[run_id, expanded, options],
                    task_id=run_id,
                )
            except Exception as exc:  # noqa: BLE001 - broker may be unavailable
                run.status = _FAILURE
                run.error = f"Could not queue the profiler task: {exc}"
                run.finished_at = timezone.now()
                run.save(update_fields=["status", "error", "finished_at"])
                errors.append(run.error)
                job_id = run_id
                job_state = run.status
            else:
                return redirect(f"{request.path}?job={run.id}")

    elif job_id:
        run = _get_run(job_id)
        if run is None:
            errors.append("Run not found (it may have been deleted).")
        else:
            job_state = run.status
            if run.status == _SUCCESS:
                result = run.result or {}
                previous = _previous_run(run)
                compare_id = previous.id if previous else None
                download_url = f"{request.path}?job={run.id}&download=1"
                if request.GET.get("download"):
                    response = JsonResponse(result, json_dumps_params={"indent": 2})
                    response["Content-Disposition"] = (
                        'attachment; filename="request-profile.json"'
                    )
                    return response
            elif run.status == _FAILURE:
                errors.append(run.error or "The profiler task failed.")
                if run.result:
                    result = run.result
                    download_url = f"{request.path}?job={run.id}&download=1"
            elif run.status == _REVOKED:
                errors.append("This run was revoked.")
                if run.result:
                    result = run.result
                    download_url = f"{request.path}?job={run.id}&download=1"

    context = {
        **admin_site.each_context(request),
        "title": "Request Profiler",
        "form": form,
        "errors": errors,
        "expanded": expanded,
        "result": result,
        "run": run,
        "job_id": job_id,
        "job_state": job_state,
        "download_url": download_url,
        "compare_id": compare_id,
        "runs": _history(),
    }
    return render(request, "admin/request_profiler.html", context)


def profiler_status_view(request, job_id):
    if not request.user.is_superuser:
        raise PermissionDenied("Only superusers can use the request profiler.")

    run = _get_run(job_id)
    if run is None:
        return JsonResponse({"state": "NOT_FOUND"}, status=404)

    options = run.options or {}
    repeat = max(1, int(options.get("repeat") or 1))
    payload = {
        "state": run.status,
        "label": run.label,
        "targets": run.target_count,
        "planned": run.target_count * repeat,
        "requests_done": len((run.result or {}).get("requests") or []),
    }
    if run.status == _FAILURE:
        payload["error"] = run.error
    if run.status == _STARTED and run.started_at:
        age = (timezone.now() - run.started_at).total_seconds()
        payload["elapsed_ms"] = int(age * 1000)
        payload["stale"] = age > 900
    return JsonResponse(payload)


def profiler_compare_view(request):
    if not request.user.is_superuser:
        raise PermissionDenied("Only superusers can use the request profiler.")

    current = _get_run(request.GET.get("a"))
    baseline = _get_run(request.GET.get("b"))
    errors = []

    if current is None:
        errors.append("Select a run to compare.")
    elif baseline is None:
        baseline = _previous_run(current)
        if baseline is None:
            errors.append(
                "No previous completed run with the same targets. "
                "Select a baseline explicitly."
            )

    rows = []
    totals = {}
    if current is not None and baseline is not None:
        rows, totals = _compare_rows(current, baseline)

    context = {
        **admin_site.each_context(request),
        "title": "Compare Profiles",
        "current": current,
        "baseline": baseline,
        "rows": rows,
        "totals": totals,
        "errors": errors,
        "runs": _history(30),
    }
    return render(request, "admin/request_profiler_compare.html", context)
