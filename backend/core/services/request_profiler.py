"""
In-process request profiler for production diagnostics.

Runs real Django requests through ``django.test.Client`` and captures SQL with
``CaptureQueriesContext``.  The debug cursor is forced for this process only,
so it works with ``DEBUG=False`` and does not require a restart or a log-level
change.

Used by the ``profile_request`` management command and by the admin profiler.
"""

from __future__ import annotations

import calendar
import json
import logging
import re
import time
import traceback
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Tuple
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from django.conf import settings
from django.core.cache import cache
from django.db import connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext

_STRING_RE = re.compile(r"'(?:[^']|'')*'")
_PLACEHOLDER_RE = re.compile(r"%\([^)]+\)s|%s|%d|\$\d+")
_NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])")
_WHITESPACE_RE = re.compile(r"\s+")
_IN_LIST_RE = re.compile(r"\bIN\s*\(\s*\?(?:\s*,\s*\?)+\)", re.IGNORECASE)
_TABLE_RE = re.compile(
    r"\b(?:FROM|JOIN|INTO|UPDATE)\s+([A-Za-z_][A-Za-z0-9_.]*)", re.IGNORECASE
)
_SELECT_RE = re.compile(r"(?is)^\s*(?:SELECT|WITH)\b")
_WRITE_RE = re.compile(
    r"(?is)\b(?:INSERT|UPDATE|DELETE|MERGE|ALTER|DROP|CREATE|TRUNCATE)\b"
)

_ORG_PAGE_RE = re.compile(r"^/entity/organization/([^/]+)/?$")
_TEMPORAL_RANGE_RE = re.compile(r"^/explore/temporal/([^/]+)/([^/]+)/?$")
_TEMPORAL_DAY_RE = re.compile(r"^/explore/temporal/([^/]+)/?$")
_MONTH_PAGE_RE = re.compile(r"^/explore/month/(\d{4})/(\d{1,2})/?$")
_WEEK_PAGE_RE = re.compile(r"^/explore/week/(\d{4})/(\d{1,2})/?$")

_UNIFIED_VIEW_PATH = "/api/decisions/unified/"
_TOP_COUNTERPARTS_SUFFIX = "/top-counterparts/"
_TOP_PAIRS_PATH = "/api/direct-assignments/top-pairs/"

_CACHE_LOGGER = "api.middleware.cache_stats"
MAX_PROFILE_TARGETS = 50

_CURL_URL_RE = re.compile(
    r"curl\s+(?:-X\s+\S+\s+)?['\"]([^'\"]+)['\"]", re.IGNORECASE | re.DOTALL
)
_CURL_METHOD_RE = re.compile(r"(?:-X|--request)\s+['\"]?([A-Za-z]+)", re.IGNORECASE)
_CURL_CHUNK_RE = re.compile(r"curl\s.*?(?=\n\s*curl\s|\Z)", re.IGNORECASE | re.DOTALL)


@dataclass
class QueryGroup:
    sql: str
    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    tables: Tuple[str, ...] = field(default_factory=tuple)


def normalize_sql(sql: str) -> str:
    text = str(sql).strip().rstrip(";").replace('"', "")
    text = _STRING_RE.sub("?", text)
    text = _PLACEHOLDER_RE.sub("?", text)
    text = _NUMBER_RE.sub("?", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return _IN_LIST_RE.sub("IN (?)", text)


def extract_tables(sql: str) -> Tuple[str, ...]:
    return tuple(dict.fromkeys(_TABLE_RE.findall(sql)))


def shorten(text: str, limit: int = 240) -> str:
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def parse_header(raw: str) -> Tuple[str, str]:
    name, separator, value = raw.partition(":")
    if not separator or not name.strip():
        raise ValueError(f"Invalid header {raw!r}; expected 'Name: value'.")
    key = name.strip().upper().replace("-", "_")
    if key not in {"CONTENT_TYPE", "CONTENT_LENGTH"}:
        key = f"HTTP_{key}"
    return key, value.strip()


def default_host() -> str:
    hosts = [host for host in getattr(settings, "ALLOWED_HOSTS", []) if host]
    for host in hosts:
        if host != "*" and not host.startswith("."):
            return host
    if hosts:
        return hosts[0].lstrip(".")
    return "localhost"


# ---------------------------------------------------------------------------
# Target expansion
# ---------------------------------------------------------------------------


def _flatten_query(query: str) -> Dict[str, str]:
    parsed = parse_qs(query, keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


def _with_query(path: str, params: Dict[str, str]) -> str:
    clean = {key: value for key, value in params.items() if value not in (None, "")}
    query = urlencode(clean)
    return f"{path}?{query}" if query else path


def _default_window() -> Tuple[str, str]:
    end = date.today()
    start = end - timedelta(days=365)
    return start.isoformat(), end.isoformat()


def _parse_iso_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {label} date: {value!r}") from exc


def _temporal_window(path: str) -> Tuple[str, str] | None:
    """Resolve a temporal route to an ISO ``(start, end)`` window."""
    match = _TEMPORAL_RANGE_RE.match(path)
    if match:
        start = _parse_iso_date(match.group(1), "start")
        end = _parse_iso_date(match.group(2), "end")
        if start > end:
            start, end = end, start
        return start.isoformat(), end.isoformat()

    match = _TEMPORAL_DAY_RE.match(path)
    if match:
        day = _parse_iso_date(match.group(1), "day")
        return day.isoformat(), day.isoformat()

    match = _MONTH_PAGE_RE.match(path)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        if not 1 <= month <= 12:
            raise ValueError(f"Invalid month: {month!r}")
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, 1).isoformat(), date(year, month, last_day).isoformat()

    match = _WEEK_PAGE_RE.match(path)
    if match:
        year, week = int(match.group(1)), int(match.group(2))
        if not 1 <= week <= 53:
            raise ValueError(f"Invalid week: {week!r}")
        jan1 = date(year, 1, 1)
        # The frontend uses JavaScript's getDay(): Sunday=0, Monday=1, ...
        js_day = (jan1.weekday() + 1) % 7
        start = jan1 + timedelta(days=(week - 1) * 7 - js_day)
        return start.isoformat(), (start + timedelta(days=6)).isoformat()

    return None


def _filter_params(query: Dict[str, str]) -> Dict[str, str]:
    params = {}
    for page_key, api_key in (
        ("search", "q"),
        ("types", "decision_types"),
        ("orgs", "organization_ids"),
        ("minAmount", "min_amount"),
        ("maxAmount", "max_amount"),
    ):
        if query.get(page_key):
            params[api_key] = query[page_key]
    if str(query.get("direct_assignments_only", "")).lower() == "true":
        params["direct_assignments_only"] = "true"
    return params


def _temporal_targets(start: str, end: str, query: Dict[str, str]) -> List[str]:
    common = {"source": "temporal"}
    list_params = {
        **common,
        "view": "decisions",
        "sort_by": query.get("sort") or "amount_desc",
        "start_date": start,
        "end_date": end,
        "page": "1",
        "page_size": "20",
        **_filter_params(query),
    }
    return [
        _with_query(
            _UNIFIED_VIEW_PATH,
            {
                **common,
                "view": "decision_types",
                "start_date": start,
                "end_date": end,
            },
        ),
        _with_query(_UNIFIED_VIEW_PATH, list_params),
        _with_query(
            _TOP_PAIRS_PATH,
            {
                "start_date": start,
                "end_date": end,
                "limit": "10",
                "offset": "0",
            },
        ),
    ]


def expand_profile_targets(raw: str) -> List[str]:
    """
    Turn one pasted value into the API paths to profile.

    Accepts an API path (``/api/...``), a full URL, or an organization page URL
    (``/entity/organization/<uid>?...``).  The page URL expands to the same four
    requests the frontend makes: date range, decision types, the decision list
    and top counterparts.
    """
    raw = (raw or "").strip()
    if not raw:
        return []

    parsed = urlparse(raw)
    path = unquote(parsed.path or raw.split("?", 1)[0])
    if path and not path.startswith("/"):
        path = "/" + path
    query = parsed.query
    if not query and "?" in raw and not path.startswith("http"):
        query = raw.split("?", 1)[1]

    if path.startswith("/api/"):
        return [_with_query(path, _flatten_query(query))]

    temporal = _temporal_window(path)
    if temporal is not None:
        return _temporal_targets(temporal[0], temporal[1], _flatten_query(query))

    match = _ORG_PAGE_RE.match(path)
    if not match:
        raise ValueError(
            "Paste an API path (/api/...), an organization page URL "
            "(/entity/organization/<uid>), or a temporal page URL "
            "(/explore/temporal/..., /explore/month/..., /explore/week/...). "
            "For other page routes, export a HAR or copy the browser requests "
            "as cURL."
        )

    uid = match.group(1)
    params = _flatten_query(query)
    start = params.get("start_date")
    end = params.get("end_date")
    if not start or not end:
        start, end = _default_window()
    if start > end:
        start, end = end, start

    common = {
        "source": "entity",
        "entity_type": "organization",
        "entity_id": uid,
    }
    targets = [
        _with_query(_UNIFIED_VIEW_PATH, {**common, "view": "date_range"}),
        _with_query(
            _UNIFIED_VIEW_PATH,
            {
                **common,
                "view": "decision_types",
                "start_date": start,
                "end_date": end,
            },
        ),
    ]

    list_params = {
        **common,
        "view": "decisions",
        "sort_by": params.get("sort") or "amount_desc",
        "start_date": start,
        "end_date": end,
        "page": "1",
        "page_size": "20",
    }
    if params.get("search"):
        list_params["q"] = params["search"]
    if params.get("types"):
        list_params["decision_types"] = params["types"]
    if params.get("orgs"):
        list_params["organization_ids"] = params["orgs"]
    if params.get("minAmount"):
        list_params["min_amount"] = params["minAmount"]
    if params.get("maxAmount"):
        list_params["max_amount"] = params["maxAmount"]
    if str(params.get("direct_assignments_only", "")).lower() == "true":
        list_params["direct_assignments_only"] = "true"
    targets.append(_with_query(_UNIFIED_VIEW_PATH, list_params))

    targets.append(
        _with_query(
            f"/api/organizations/{uid}{_TOP_COUNTERPARTS_SUFFIX}",
            {
                "start_date": start,
                "end_date": end,
                "limit": "5",
                "offset": "0",
            },
        )
    )
    return targets


def _api_path_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    if not parsed.path.startswith("/api/"):
        return None
    return _with_query(parsed.path, _flatten_query(parsed.query))


def _dedupe(paths: List[str]) -> List[str]:
    return list(dict.fromkeys(paths))


def extract_api_paths_from_har(raw: str) -> List[str]:
    """Extract GET /api/ paths from a HAR (browser network export)."""
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ValueError("Invalid HAR JSON.") from exc

    if (
        isinstance(data, dict)
        and "log" not in data
        and ("message" in data or "sql" in data or "logger" in data)
    ):
        raise ValueError(
            "That looks like a Django SQL log line, not a HAR. Export the "
            "browser network requests as HAR, or copy them as cURL."
        )

    entries = (data.get("log") or {}).get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ValueError("HAR is missing log.entries.")

    paths = []
    for entry in entries:
        request = entry.get("request") or {}
        if str(request.get("method", "GET")).upper() != "GET":
            continue
        path = _api_path_from_url(str(request.get("url") or ""))
        if path:
            paths.append(path)
    return _dedupe(paths)


def extract_api_paths_from_curl(raw: str) -> List[str]:
    """Extract GET /api/ paths from one or more 'Copy all as cURL' commands."""
    paths = []
    for chunk in _CURL_CHUNK_RE.finditer(raw):
        command = chunk.group(0)
        method = _CURL_METHOD_RE.search(command)
        if method and method.group(1).upper() != "GET":
            continue
        url = _CURL_URL_RE.search(command)
        if not url:
            continue
        path = _api_path_from_url(url.group(1))
        if path:
            paths.append(path)
    return _dedupe(paths)


def parse_profile_input(raw: str) -> List[str]:
    """
    Parse the admin/command input into API paths.

    Accepts newline-separated page or API URLs, one or more cURL commands, or
    a HAR JSON document. Page URLs are expanded with ``expand_profile_targets``;
    HAR/cURL inputs are reduced to the GET ``/api/`` calls the browser made.
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    if raw.startswith("{") or raw.startswith("["):
        return extract_api_paths_from_har(raw)
    if "curl " in raw.lower():
        return extract_api_paths_from_curl(raw)

    paths = []
    for line in raw.splitlines():
        line = line.strip()
        if line:
            paths.extend(expand_profile_targets(line))
    return _dedupe(paths)


# ---------------------------------------------------------------------------
# Cache busting
# ---------------------------------------------------------------------------


def bust_cache_for_paths(paths: List[str]) -> List[str]:
    """
    Delete the known API cache keys for the profiled paths.

    Only the unified aggregate, top-counterparts and direct-assignment
    top-pairs views are known here. Other paths are measured as-is. Returns
    the keys that were deleted.
    """
    from api.redis_keys import UNIFIED_AGGREGATE_CACHE_PARAMS
    from core.services.response_cache_service import response_cache

    deleted = []
    for path in paths:
        parsed = urlparse(path)
        params = _flatten_query(parsed.query)
        keys = []

        if parsed.path == _UNIFIED_VIEW_PATH:
            key_params = {
                name: params.get(name, "") for name in UNIFIED_AGGREGATE_CACHE_PARAMS
            }
            keys.append(response_cache.build_key("unified", **key_params))
        elif parsed.path == _TOP_PAIRS_PATH:
            key_params = {
                name: params.get(name, "")
                for name in ("start_date", "end_date", "limit", "offset")
            }
            keys.append(response_cache.build_key("da_top_pairs", **key_params))
        elif parsed.path.startswith("/api/organizations/") and parsed.path.endswith(
            _TOP_COUNTERPARTS_SUFFIX
        ):
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 4:
                uid = parts[2]
                key_params = {
                    name: params.get(name, "")
                    for name in ("start_date", "end_date", "limit", "offset", "q")
                }
                key_params["organization_uid"] = uid
                keys.append(
                    response_cache.build_key("top_org_counterparts", **key_params)
                )

        for key in keys:
            try:
                if cache.delete(key):
                    deleted.append(key)
            except Exception:  # noqa: BLE001 - cache is best effort
                continue
    return deleted


# ---------------------------------------------------------------------------
# Client / measurement
# ---------------------------------------------------------------------------


def _resolve_user(user):
    if user is None or not isinstance(user, str):
        return user

    from users.models import CustomUser

    found = (
        CustomUser.objects.filter(username=user).first()
        or CustomUser.objects.filter(email__iexact=user).first()
    )
    if found is None:
        raise ValueError(f"No user matches {user!r}.")
    return found


def _build_client(user=None) -> Client:
    client = Client()
    resolved = _resolve_user(user)
    if resolved is not None:
        client.force_login(resolved)
    return client


def _request_kwargs(
    *,
    host: str | None,
    client_ip: str,
    token: str | None,
    bearer: str | None,
    headers: List[str] | None,
) -> Dict[str, str]:
    kwargs: Dict[str, str] = {
        "HTTP_HOST": host or default_host(),
        "REMOTE_ADDR": client_ip,
    }
    if token:
        kwargs["HTTP_AUTHORIZATION"] = f"Token {token}"
    elif bearer:
        kwargs["HTTP_AUTHORIZATION"] = f"Bearer {bearer}"
    for raw in headers or []:
        key, value = parse_header(raw)
        kwargs[key] = value
    return kwargs


def _measure(
    client: Client,
    method: str,
    path: str,
    kwargs: Dict[str, str],
    insecure: bool,
) -> Dict[str, Any]:
    from loguru import logger as loguru_logger

    records: List[Dict] = []
    sink_id = loguru_logger.add(
        lambda message: records.append(message.record),
        level="INFO",
        format="{message}",
    )
    response = None
    content = b""
    captured = None
    error = None
    started = time.perf_counter()
    try:
        with CaptureQueriesContext(connection) as captured:
            response = client.generic(method, path, secure=not insecure, **kwargs)
            content = response.content
    except Exception:  # noqa: BLE001 - report the failure, keep profiling
        error = traceback.format_exc()
    finally:
        wall_ms = (time.perf_counter() - started) * 1000.0
        loguru_logger.remove(sink_id)

    defer = None
    if response is not None and response.status_code == 202:
        body = {}
        try:
            body = json.loads(content)
        except (TypeError, ValueError):
            body = {}
        retry_after = response.headers.get("Retry-After") or body.get("retry_after")
        try:
            retry_after = int(retry_after)
        except (TypeError, ValueError):
            retry_after = None
        defer = {
            "status": body.get("status") or "warming",
            "retry_after": retry_after,
        }

    raw_queries = list(captured.captured_queries) if captured else []
    queries_ms = sum(float(query.get("time") or 0) for query in raw_queries) * 1000.0

    groups: Dict[str, QueryGroup] = {}
    slowest = []
    for query in raw_queries:
        sql = str(query.get("sql") or "")
        duration_ms = float(query.get("time") or 0) * 1000.0
        normalized = normalize_sql(sql)
        tables = extract_tables(normalized)
        group = groups.setdefault(
            normalized,
            QueryGroup(sql=normalized, tables=tables),
        )
        group.count += 1
        group.total_ms += duration_ms
        group.max_ms = max(group.max_ms, duration_ms)
        slowest.append(
            {
                "sql": sql,
                "normalized_sql": normalized,
                "duration_ms": duration_ms,
                "tables": list(tables),
            }
        )

    grouped = sorted(groups.values(), key=lambda item: item.total_ms, reverse=True)
    slowest.sort(key=lambda item: item["duration_ms"], reverse=True)

    return {
        "method": method,
        "path": path,
        "status": response.status_code if response is not None else "exception",
        "is_error": response is not None and response.status_code >= 400,
        "error": error,
        "defer": defer,
        "wall_ms": wall_ms,
        "db_ms": queries_ms,
        "db_pct": (queries_ms / wall_ms * 100.0) if wall_ms else 0.0,
        "query_count": len(raw_queries),
        "response_bytes": len(content),
        "cache": {
            "summary": [
                record["message"]
                for record in records
                if record.get("name") == _CACHE_LOGGER
                or "[Cache Summary]" in record.get("message", "")
            ],
            "defer": [
                record["message"]
                for record in records
                if "Cache Decorator DEFER" in record.get("message", "")
            ],
        },
        "queries": {
            "groups": [
                {
                    "sql": group.sql,
                    "tables": list(group.tables),
                    "count": group.count,
                    "total_ms": group.total_ms,
                    "max_ms": group.max_ms,
                }
                for group in grouped
            ],
            "slowest": slowest,
        },
        "body_preview": (
            content[:800].decode("utf-8", errors="replace")
            if response is not None and response.status_code >= 400
            else None
        ),
    }


# ---------------------------------------------------------------------------
# EXPLAIN
# ---------------------------------------------------------------------------


def _run_explain(sql: str, timeout_ms: int) -> List[str]:
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
                cursor.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) " + sql)
                rows = [str(row[0]) for row in cursor.fetchall()]
            transaction.set_rollback(True)
        return rows
    except Exception as exc:  # noqa: BLE001 - diagnostic tool
        return [f"EXPLAIN failed: {exc}"]


def _explain_slow_queries(
    slowest: List[Dict],
    *,
    explain: bool,
    explain_min_ms: float,
    explain_top: int,
    explain_timeout_ms: int,
) -> List[Dict[str, Any]]:
    if not explain:
        return []

    plans = []
    seen = set()
    for query in slowest:
        if query["duration_ms"] < explain_min_ms:
            continue
        sql = query["sql"]
        if not _SELECT_RE.match(sql) or _WRITE_RE.search(sql):
            continue
        if " FOR UPDATE" in sql.upper():
            continue
        shape = query["normalized_sql"]
        if shape in seen:
            continue
        seen.add(shape)
        if len(plans) >= max(0, explain_top):
            break

        plan = _run_explain(sql, explain_timeout_ms)
        plans.append(
            {
                "sql": sql,
                "normalized_sql": shape,
                "duration_ms": query["duration_ms"],
                "tables": query["tables"],
                "plan": plan,
            }
        )
    return plans


# ---------------------------------------------------------------------------
# DB context
# ---------------------------------------------------------------------------


def db_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    current_setting('shared_buffers'),
                    current_setting('effective_cache_size'),
                    current_setting('work_mem'),
                    current_setting('maintenance_work_mem'),
                    current_setting('random_page_cost'),
                    current_setting('effective_io_concurrency'),
                    current_setting('max_parallel_workers_per_gather'),
                    current_setting('statement_timeout'),
                    current_setting('server_version')
                """
            )
            row = cursor.fetchone()
            keys = (
                "shared_buffers",
                "effective_cache_size",
                "work_mem",
                "maintenance_work_mem",
                "random_page_cost",
                "effective_io_concurrency",
                "max_parallel_workers_per_gather",
                "statement_timeout",
                "server_version",
            )
            info.update(dict(zip(keys, row)))

            cursor.execute(
                """
                SELECT
                    COALESCE(inet_server_addr()::text, 'local'),
                    current_database(),
                    pg_postmaster_start_time()
                """
            )
            addr, database_name, started = cursor.fetchone()
            info["server_addr"] = addr
            info["database_name"] = database_name
            info["postmaster_start_time"] = str(started)

            cursor.execute(
                "SELECT pg_size_pretty(pg_database_size(current_database()))"
            )
            info["database_size"] = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT relname, pg_size_pretty(pg_total_relation_size(oid))
                FROM pg_class
                WHERE relkind = 'r'
                  AND relnamespace = 'public'::regnamespace
                ORDER BY pg_total_relation_size(oid) DESC
                LIMIT 10
                """
            )
            info["largest_tables"] = [
                {"table": name, "size": size} for name, size in cursor.fetchall()
            ]
    except Exception as exc:  # noqa: BLE001 - diagnostic tool
        info["error"] = str(exc)
    return info


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def profile_requests(
    paths: List[str],
    *,
    method: str = "GET",
    host: str | None = None,
    token: str | None = None,
    bearer: str | None = None,
    headers: List[str] | None = None,
    user=None,
    insecure: bool = False,
    warmup: int = 0,
    repeat: int = 1,
    explain: bool = False,
    explain_min_ms: float = 200.0,
    explain_top: int = 3,
    explain_timeout_ms: int = 30000,
    include_db_info: bool = False,
    client_ip: str = "127.0.0.1",
    bust_cache: bool = False,
    statement_timeout_ms: int | None = None,
    progress=None,
) -> Dict[str, Any]:
    """
    Run each path and return the profiling payload.

    ``user`` may be a User instance (the admin view) or a username/email string
    (the management command).  The caller is responsible for printing the
    payload; this function has no output.
    """
    paths = [path.strip() for path in paths if path and path.strip()]
    if not paths:
        raise ValueError("At least one request path is required.")
    for path in paths:
        if not path.startswith("/"):
            raise ValueError(f"Request path must start with '/': {path!r}")

    db_logger = logging.getLogger("django.db.backends")
    previous_level = db_logger.level
    db_logger.setLevel(logging.WARNING)
    timeout_override = None
    if statement_timeout_ms:
        timeout_override = max(1, int(statement_timeout_ms))
        with connection.cursor() as cursor:
            cursor.execute(f"SET statement_timeout = {timeout_override}")
    try:
        return _profile_requests(
            paths,
            method=method,
            host=host,
            token=token,
            bearer=bearer,
            headers=headers,
            user=user,
            insecure=insecure,
            warmup=warmup,
            repeat=repeat,
            explain=explain,
            explain_min_ms=explain_min_ms,
            explain_top=explain_top,
            explain_timeout_ms=explain_timeout_ms,
            include_db_info=include_db_info,
            client_ip=client_ip,
            bust_cache=bust_cache,
            progress=progress,
        )
    finally:
        if timeout_override is not None:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("RESET statement_timeout")
            except Exception:  # noqa: BLE001 - restore is best effort
                pass
        db_logger.setLevel(previous_level)


def _profile_requests(
    paths: List[str],
    *,
    method: str,
    host: str | None,
    token: str | None,
    bearer: str | None,
    headers: List[str] | None,
    user,
    insecure: bool,
    warmup: int,
    repeat: int,
    explain: bool,
    explain_min_ms: float,
    explain_top: int,
    explain_timeout_ms: int,
    include_db_info: bool,
    client_ip: str,
    bust_cache: bool,
    progress=None,
) -> Dict[str, Any]:
    client = _build_client(user)
    request_kwargs = _request_kwargs(
        host=host,
        client_ip=client_ip,
        token=token,
        bearer=bearer,
        headers=headers,
    )

    payload: Dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "targets": paths,
        "db": db_info() if include_db_info else None,
        "cache_busted": bust_cache_for_paths(paths) if bust_cache else [],
        "requests": [],
    }

    for path in paths:
        for _ in range(max(0, warmup)):
            try:
                client.generic(method, path, secure=not insecure, **request_kwargs)
            except Exception:  # noqa: BLE001 - warmup is best effort
                pass

        for iteration in range(1, max(1, repeat) + 1):
            result = _measure(client, method, path, request_kwargs, insecure)
            result["iteration"] = iteration
            result["explain"] = _explain_slow_queries(
                result["queries"]["slowest"],
                explain=explain,
                explain_min_ms=explain_min_ms,
                explain_top=explain_top,
                explain_timeout_ms=explain_timeout_ms,
            )
            payload["requests"].append(result)
            if progress is not None:
                try:
                    progress(payload)
                except Exception:  # noqa: BLE001 - progress must not stop profiling
                    logging.getLogger(__name__).exception(
                        "Request profiler progress callback failed"
                    )

    return payload
