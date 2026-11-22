#!/usr/bin/env python3
"""Turn Django/loguru request logs into a readable SQL report.

The logs are JSON lines shaped like:

    2026-11-22 21:34:49.207 | {"message": "...", "sql": "SELECT ...", "duration": 0.0005, ...}

This script parses those lines and prints the queries as cleaned-up SQL with
their count and database time, so repeated or expensive queries stand out.

Usage:
    python3 scripts/analyze_sql_log.py org_loading
    python3 scripts/analyze_sql_log.py org_loading --by-request
    python3 scripts/analyze_sql_log.py org_loading --slowest 10
    python3 scripts/analyze_sql_log.py after.log --compare before.log
    python3 scripts/analyze_sql_log.py org_loading -o report.txt
    python3 scripts/analyze_sql_log.py org_loading --json -o report.json

The script uses only the standard library.
"""

from __future__ import annotations

import argparse
import bisect
import json
import re
import shutil
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional

SEPARATOR = " | "

STRING_RE = re.compile(r"'(?:[^']|'')*'")
PLACEHOLDER_RE = re.compile(r"%\([^)]+\)s|%s|%d|\$\d+")
NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])")
IN_LIST_RE = re.compile(r"\bIN\s*\(\s*\?(?:\s*,\s*\?)+\s*\)", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")
TABLE_RE = re.compile(
    r"\b(?:FROM|JOIN|INTO|UPDATE)\s+([A-Za-z_][A-Za-z0-9_.]*)", re.IGNORECASE
)
SELECT_RE = re.compile(r"(?is)^(SELECT\s+(?:DISTINCT\s+)?)(.*?)(\s+FROM\s+.*)$")
REQUEST_RE = re.compile(
    r'"?([A-Z]+)\s+(\S+)\s+HTTP/[\d.]+"?\s+(\d{3})(?:\s+(\d+))?'
)
DB_MESSAGE_PREFIX_RE = re.compile(r"^\(\s*([\d.]+)\s*\)\s*")
TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]{32,}")
CLAUSE_KEYWORDS = (
    "LEFT OUTER JOIN",
    "RIGHT OUTER JOIN",
    "FULL OUTER JOIN",
    "INNER JOIN",
    "LEFT JOIN",
    "RIGHT JOIN",
    "CROSS JOIN",
    "JOIN",
    "FROM",
    "WHERE",
    "GROUP BY",
    "ORDER BY",
    "HAVING",
    "LIMIT",
    "OFFSET",
    "VALUES",
)


@dataclass(frozen=True)
class Query:
    ts: Optional[datetime]
    sql: str
    duration_ms: float
    params: tuple[str, ...] = ()
    alias: str = "default"


@dataclass(frozen=True)
class Request:
    ts: datetime
    method: str
    path: str
    status: int
    size: Optional[int] = None


@dataclass
class QueryGroup:
    fingerprint: str
    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    params: list[str] = field(default_factory=list)
    tables: tuple[str, ...] = ()

    @property
    def avg_ms(self) -> float:
        return self.total_ms / self.count if self.count else 0.0


@dataclass
class Analysis:
    queries: list[Query]
    requests: list[Request]
    lines: int
    skipped: int
    start: Optional[datetime]
    end: Optional[datetime]

    @property
    def total_db_ms(self) -> float:
        return sum(q.duration_ms for q in self.queries)

    @property
    def wall_seconds(self) -> Optional[float]:
        if not self.start or not self.end:
            return None
        return (self.end - self.start).total_seconds()


def parse_timestamp(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def parse_line(raw: str) -> Optional[dict]:
    line = raw.strip()
    if not line:
        return None
    payload = line
    if SEPARATOR in line:
        left, right = line.split(SEPARATOR, 1)
        if parse_timestamp(left.strip()) is not None:
            payload = right
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _query_from_record(ts: Optional[datetime], obj: dict) -> Optional[Query]:
    sql = obj.get("sql")
    message = obj.get("message") or ""
    duration = obj.get("duration")

    if sql is None:
        logger = str(obj.get("logger") or "")
        if "django.db.backends" not in logger:
            return None
        sql = DB_MESSAGE_PREFIX_RE.sub("", message).split("; args=")[0].strip()
        match = DB_MESSAGE_PREFIX_RE.match(message)
        if duration is None and match:
            duration = float(match.group(1))
    if not sql:
        return None

    params = obj.get("params") or ()
    if not isinstance(params, (list, tuple)):
        params = (params,)
    try:
        duration_ms = float(duration or 0.0) * 1000.0
    except (TypeError, ValueError):
        duration_ms = 0.0

    return Query(
        ts=ts,
        sql=str(sql),
        duration_ms=duration_ms,
        params=tuple(str(p) for p in params),
        alias=str(obj.get("alias") or "default"),
    )


def _request_from_record(ts: Optional[datetime], obj: dict) -> Optional[Request]:
    if ts is None or "status_code" not in obj:
        return None
    message = obj.get("message") or ""
    match = REQUEST_RE.search(message)
    if not match:
        return None
    method, path, status, size = match.groups()
    return Request(
        ts=ts,
        method=method,
        path=path,
        status=int(status),
        size=int(size) if size is not None else None,
    )


def analyze_lines(lines: Iterable[str]) -> Analysis:
    queries: list[Query] = []
    requests: list[Request] = []
    lines_count = 0
    skipped = 0
    timestamps: list[datetime] = []

    for raw in lines:
        lines_count += 1
        obj = parse_line(raw)
        if obj is None:
            skipped += 1
            continue
        ts = parse_timestamp(
            raw.split(SEPARATOR, 1)[0].strip() if SEPARATOR in raw else ""
        )
        if ts is not None:
            timestamps.append(ts)

        query = _query_from_record(ts, obj)
        if query is not None:
            queries.append(query)
            continue
        request = _request_from_record(ts, obj)
        if request is not None:
            requests.append(request)
        else:
            skipped += 1

    queries.sort(key=lambda q: q.ts or datetime.min)
    requests.sort(key=lambda r: r.ts)
    return Analysis(
        queries=queries,
        requests=requests,
        lines=lines_count,
        skipped=skipped,
        start=min(timestamps) if timestamps else None,
        end=max(timestamps) if timestamps else None,
    )


def read_lines(path: str) -> Iterator[str]:
    if path == "-":
        yield from sys.stdin
        return
    with open(path, encoding="utf-8", errors="replace") as handle:
        yield from handle


def normalize_sql(sql: str) -> str:
    text = sql.strip().rstrip(";")
    text = text.replace('"', "")
    text = STRING_RE.sub("?", text)
    text = PLACEHOLDER_RE.sub("?", text)
    text = NUMBER_RE.sub("?", text)
    text = WHITESPACE_RE.sub(" ", text).strip()
    return IN_LIST_RE.sub("IN (?)", text)


def split_top_level(text: str) -> list[str]:
    parts: list[str] = []
    buffer: list[str] = []
    depth = 0
    in_string = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            buffer.append(char)
            if char == "'":
                if index + 1 < len(text) and text[index + 1] == "'":
                    buffer.append(text[index + 1])
                    index += 1
                else:
                    in_string = False
        elif char == "'":
            in_string = True
            buffer.append(char)
        elif char in "([":
            depth += 1
            buffer.append(char)
        elif char in ")]":
            depth = max(0, depth - 1)
            buffer.append(char)
        elif char == "," and depth == 0:
            parts.append("".join(buffer).strip())
            buffer = []
        else:
            buffer.append(char)
        index += 1
    if buffer:
        parts.append("".join(buffer).strip())
    return [part for part in parts if part]


def shorten_select(sql: str, max_columns: int) -> str:
    if max_columns <= 0:
        return sql
    match = SELECT_RE.match(sql)
    if not match:
        return sql
    prefix, columns_text, suffix = match.groups()
    columns = split_top_level(columns_text)
    if len(columns) <= max_columns:
        return sql
    shown = ", ".join(columns[:max_columns])
    hidden = len(columns) - max_columns
    return f"{prefix}{shown}, … (+{hidden} more){suffix}"


def extract_tables(sql: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(TABLE_RE.findall(sql)))


def _is_identifier_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def break_clauses(sql: str) -> str:
    """Insert newlines before top-level SQL clauses, ignoring subqueries."""
    upper = sql.upper()
    output: list[str] = []
    depth = 0
    in_string = False
    index = 0
    length = len(sql)
    while index < length:
        char = sql[index]
        if in_string:
            output.append(char)
            if char == "'":
                if index + 1 < length and sql[index + 1] == "'":
                    output.append(sql[index + 1])
                    index += 2
                    continue
                in_string = False
            index += 1
            continue
        if char == "'":
            in_string = True
            output.append(char)
            index += 1
            continue
        if char in "([":
            depth += 1
            output.append(char)
            index += 1
            continue
        if char in ")]":
            depth = max(0, depth - 1)
            output.append(char)
            index += 1
            continue
        if depth == 0 and char == " ":
            for keyword in CLAUSE_KEYWORDS:
                end = index + 1 + len(keyword)
                matches = upper.startswith(keyword, index + 1)
                boundary = end >= length or not _is_identifier_char(upper[end])
                if matches and boundary:
                    if output and output[-1] != "\n":
                        output.append("\n")
                    output.append(sql[index + 1 : end])
                    index = end
                    break
            else:
                output.append(char)
                index += 1
            continue
        output.append(char)
        index += 1
    return "".join(output)


def pretty_sql(sql: str, *, width: int, max_columns: int, indent: str = "    ") -> str:
    text = shorten_select(sql, max_columns)
    text = break_clauses(text)
    wrap_width = max(30, width - len(indent))
    lines: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        wrapped = textwrap.wrap(
            line,
            width=wrap_width,
            break_long_words=False,
            break_on_hyphens=False,
        )
        lines.extend(wrapped or [line])
    return "\n".join(indent + line for line in lines)


def safe_param(params: tuple[str, ...]) -> str:
    if not params:
        return ""
    text = str(params[0])
    if len(text) >= 32 and TOKEN_RE.fullmatch(text):
        return "<redacted>"
    if len(text) > 40:
        return text[:37] + "..."
    return text


def group_queries(queries: Iterable[Query]) -> list[QueryGroup]:
    groups: dict[str, QueryGroup] = {}
    for query in queries:
        fingerprint = normalize_sql(query.sql)
        group = groups.get(fingerprint)
        if group is None:
            group = QueryGroup(fingerprint=fingerprint)
            groups[fingerprint] = group
        group.count += 1
        group.total_ms += query.duration_ms
        group.max_ms = max(group.max_ms, query.duration_ms)
        if len(group.params) < 5:
            param = safe_param(query.params)
            if param and param not in group.params:
                group.params.append(param)
    for group in groups.values():
        group.tables = extract_tables(group.fingerprint)
    return list(groups.values())


def sort_groups(groups: list[QueryGroup], key: str) -> list[QueryGroup]:
    return sorted(
        groups,
        key=lambda g: {
            "total": g.total_ms,
            "count": g.count,
            "avg": g.avg_ms,
            "max": g.max_ms,
        }[key],
        reverse=True,
    )


def filter_groups(
    groups: list[QueryGroup],
    *,
    min_ms: float = 0.0,
    tables: Optional[list[str]] = None,
    grep: Optional[str] = None,
    duplicates_only: bool = False,
) -> list[QueryGroup]:
    pattern = re.compile(grep, re.IGNORECASE) if grep else None
    wanted = {table.lower() for table in tables} if tables else None
    filtered = []
    for group in groups:
        if group.total_ms < min_ms:
            continue
        if duplicates_only and group.count < 2:
            continue
        if wanted and not (wanted & {t.lower() for t in group.tables}):
            continue
        if pattern and not pattern.search(group.fingerprint):
            continue
        filtered.append(group)
    return filtered


def attribute_queries(
    analysis: Analysis,
) -> tuple[list[tuple[Request, int, float]], int, float]:
    if not analysis.requests:
        return [], len(analysis.queries), analysis.total_db_ms
    requests = analysis.requests
    times = [request.ts for request in requests]
    counts = [0] * len(requests)
    totals = [0.0] * len(requests)
    unattributed_count = 0
    unattributed_ms = 0.0
    for query in analysis.queries:
        if query.ts is None:
            unattributed_count += 1
            unattributed_ms += query.duration_ms
            continue
        index = bisect.bisect_left(times, query.ts)
        if index >= len(requests):
            unattributed_count += 1
            unattributed_ms += query.duration_ms
            continue
        counts[index] += 1
        totals[index] += query.duration_ms
    rows = [(request, counts[i], totals[i]) for i, request in enumerate(requests)]
    return rows, unattributed_count, unattributed_ms


def format_ms(value: float) -> str:
    if value >= 1000:
        return f"{value / 1000:,.2f}s"
    return f"{value:,.1f}ms"


def format_table(headers: list[str], rows: list[list[str]], right: set[int]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    lines = []
    for line_index, row in enumerate([headers] + rows):
        cells = []
        for index, cell in enumerate(row):
            if line_index > 0 and index in right:
                cells.append(cell.rjust(widths[index]))
            else:
                cells.append(cell.ljust(widths[index]))
        lines.append("  ".join(cells).rstrip())
        if line_index == 0:
            lines.append("  ".join("-" * width for width in widths))
    return "\n".join(lines)


def describe_analysis(analysis: Analysis) -> str:
    wall = analysis.wall_seconds
    window = ""
    if analysis.start and analysis.end:
        window = (
            f"\nWindow   {analysis.start.strftime('%H:%M:%S.%f')[:-3]}"
            f" → {analysis.end.strftime('%H:%M:%S.%f')[:-3]}"
        )
        if wall is not None:
            window += f" (wall {wall:,.2f}s)"
    return (
        f"Parsed {analysis.lines:,} lines: {len(analysis.queries):,} queries, "
        f"{len(analysis.requests):,} requests, {analysis.skipped:,} skipped"
        f"\nDB time  {format_ms(analysis.total_db_ms)} across "
        f"{len(analysis.queries):,} queries"
        f"{window}"
    )


def render_group_blocks(
    groups: list[QueryGroup],
    *,
    total_ms: float,
    width: int,
    max_columns: int,
    show_params: bool,
) -> str:
    total = total_ms or 1.0
    blocks: list[str] = []
    for index, group in enumerate(groups, 1):
        share = group.total_ms / total * 100
        blocks.append(
            f"{index}.  {group.count}×  {format_ms(group.total_ms)} total"
            f"  ({format_ms(group.avg_ms)} avg, {format_ms(group.max_ms)} max,"
            f" {share:.1f}%)"
        )
        blocks.append(
            pretty_sql(group.fingerprint, width=width, max_columns=max_columns)
        )
        if show_params and group.params:
            params = "params: " + ", ".join(group.params)
            blocks.extend(
                "    " + line
                for line in textwrap.wrap(
                    params,
                    width=max(30, width - 4),
                    break_long_words=False,
                    break_on_hyphens=False,
                )
            )
        blocks.append("")
    return "\n".join(blocks).rstrip()


def render_report(
    analysis: Analysis,
    *,
    top: int = 15,
    sort: str = "total",
    min_ms: float = 0.0,
    tables: Optional[list[str]] = None,
    grep: Optional[str] = None,
    duplicates_only: bool = False,
    max_columns: int = 8,
    show_params: bool = True,
    by_request: bool = False,
    slowest: int = 0,
    width: int = 100,
    as_table: bool = False,
) -> str:
    output = [describe_analysis(analysis)]

    groups = filter_groups(
        group_queries(analysis.queries),
        min_ms=min_ms,
        tables=tables,
        grep=grep,
        duplicates_only=duplicates_only,
    )
    groups = sort_groups(groups, sort)
    if top > 0:
        groups = groups[:top]

    output.append("")
    if not groups:
        output.append("No queries matched the filters.")
    elif as_table:
        total = analysis.total_db_ms or 1.0
        rows = []
        for group in groups:
            params = ""
            if show_params and group.params:
                params = "  [" + ", ".join(group.params) + "]"
            rows.append(
                [
                    str(group.count),
                    format_ms(group.total_ms),
                    format_ms(group.avg_ms),
                    format_ms(group.max_ms),
                    f"{group.total_ms / total * 100:.1f}%",
                    shorten_select(group.fingerprint, max_columns) + params,
                ]
            )
        output.append(
            format_table(
                ["COUNT", "TOTAL", "AVG", "MAX", "SHARE", "SQL"],
                rows,
                right={0, 1, 2, 3, 4},
            )
        )
    else:
        output.append(
            render_group_blocks(
                groups,
                total_ms=analysis.total_db_ms,
                width=width,
                max_columns=max_columns,
                show_params=show_params,
            )
        )

    if slowest > 0:
        output.append("")
        output.append(f"Slowest individual queries (top {slowest})")
        slow = sorted(analysis.queries, key=lambda q: q.duration_ms, reverse=True)
        for query in slow[:slowest]:
            stamp = query.ts.strftime("%H:%M:%S.%f")[:-3] if query.ts else "?"
            sql = shorten_select(normalize_sql(query.sql), max_columns)
            short = textwrap.shorten(
                sql, width=max(40, width - 28), placeholder=" …"
            )
            output.append(
                f"  {format_ms(query.duration_ms):>9}  {stamp}  {short}"
            )

    if by_request:
        rows, unattributed_count, unattributed_ms = attribute_queries(analysis)
        output.append("")
        output.append("Per-request (queries attributed to the next completed request)")
        request_rows = [
            [
                str(count),
                format_ms(total_ms),
                str(request.status),
                request.method,
                request.path,
            ]
            for request, count, total_ms in rows
        ]
        output.append(
            format_table(
                ["COUNT", "DB TIME", "STATUS", "METHOD", "PATH"],
                request_rows,
                right={0, 1, 2},
            )
        )
        if unattributed_count:
            output.append(
                f"Unattributed: {unattributed_count:,} queries, "
                f"{format_ms(unattributed_ms)}"
            )
        output.append(
            "Note: concurrent requests are interleaved, so this split is approximate."
        )

    return "\n".join(output)


def analysis_to_dict(
    analysis: Analysis,
    *,
    top: int = 0,
    sort: str = "total",
    min_ms: float = 0.0,
    tables: Optional[list[str]] = None,
    grep: Optional[str] = None,
    duplicates_only: bool = False,
    max_columns: int = 8,
    by_request: bool = False,
) -> dict:
    groups = filter_groups(
        group_queries(analysis.queries),
        min_ms=min_ms,
        tables=tables,
        grep=grep,
        duplicates_only=duplicates_only,
    )
    groups = sort_groups(groups, sort)
    if top > 0:
        groups = groups[:top]

    payload = {
        "stats": {
            "lines": analysis.lines,
            "skipped": analysis.skipped,
            "queries": len(analysis.queries),
            "requests": len(analysis.requests),
            "total_db_ms": round(analysis.total_db_ms, 3),
            "wall_seconds": (
                round(analysis.wall_seconds, 3)
                if analysis.wall_seconds is not None
                else None
            ),
            "start": analysis.start.isoformat() if analysis.start else None,
            "end": analysis.end.isoformat() if analysis.end else None,
        },
        "queries": [
            {
                "sql": shorten_select(group.fingerprint, max_columns),
                "fingerprint": group.fingerprint,
                "count": group.count,
                "total_ms": round(group.total_ms, 3),
                "avg_ms": round(group.avg_ms, 3),
                "max_ms": round(group.max_ms, 3),
                "tables": list(group.tables),
                "params": group.params,
            }
            for group in groups
        ],
    }
    if by_request:
        rows, unattributed_count, unattributed_ms = attribute_queries(analysis)
        payload["requests"] = [
            {
                "path": request.path,
                "method": request.method,
                "status": request.status,
                "count": count,
                "total_ms": round(total_ms, 3),
                "timestamp": request.ts.isoformat(),
            }
            for request, count, total_ms in rows
        ]
        payload["unattributed"] = {
            "count": unattributed_count,
            "total_ms": round(unattributed_ms, 3),
        }
    return payload


def compare_analyses(
    baseline: Analysis,
    current: Analysis,
    *,
    min_delta_ms: float = 0.5,
    top: int = 30,
    max_columns: int = 8,
    show_params: bool = True,
) -> str:
    baseline_groups = {g.fingerprint: g for g in group_queries(baseline.queries)}
    current_groups = {g.fingerprint: g for g in group_queries(current.queries)}
    keys = set(baseline_groups) | set(current_groups)
    rows = []
    for key in keys:
        before = baseline_groups.get(key)
        after = current_groups.get(key)
        before_ms = before.total_ms if before else 0.0
        after_ms = after.total_ms if after else 0.0
        before_count = before.count if before else 0
        after_count = after.count if after else 0
        delta_ms = after_ms - before_ms
        delta_count = after_count - before_count
        if abs(delta_ms) < min_delta_ms and delta_count == 0:
            continue
        params = ""
        source = after or before
        if show_params and source and source.params:
            params = "  [" + ", ".join(source.params) + "]"
        rows.append(
            [
                f"{delta_ms:+,.1f}",
                f"{delta_count:+,d}",
                format_ms(before_ms),
                format_ms(after_ms),
                str(after_count),
                shorten_select(key, max_columns) + params,
            ]
        )
    rows.sort(key=lambda row: float(row[0].replace(",", "")))
    if top > 0:
        rows = rows[:top]

    header = (
        f"Comparison {baseline.lines:,} lines → {current.lines:,} lines\n"
        f"Baseline {len(baseline.queries):,} queries / "
        f"{format_ms(baseline.total_db_ms)}\n"
        f"Current  {len(current.queries):,} queries / "
        f"{format_ms(current.total_db_ms)}\n"
        f"Delta    {len(current.queries) - len(baseline.queries):+,} queries / "
        f"{format_ms(current.total_db_ms - baseline.total_db_ms)}"
    )
    if not rows:
        return header + "\n\nNo meaningful differences."
    table = format_table(
        ["Δ TOTAL", "Δ COUNT", "BEFORE", "AFTER", "AFTER COUNT", "SQL"],
        rows,
        right={0, 1, 2, 3, 4},
    )
    return header + "\n\n" + table


def emit(text: str, output: Optional[str]) -> None:
    if not output:
        print(text)
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    print(f"Wrote {path}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Readable SQL report from Django/loguru request logs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 scripts/analyze_sql_log.py org_loading\n"
            "  python3 scripts/analyze_sql_log.py org_loading --by-request\n"
            "  python3 scripts/analyze_sql_log.py org_loading --slowest 10\n"
            "  python3 scripts/analyze_sql_log.py after.log --compare before.log\n"
        ),
    )
    parser.add_argument("logfile", help="Log file to analyze, or '-' for stdin")
    parser.add_argument(
        "--compare",
        metavar="BASELINE",
        help="Show per-query deltas against an earlier log file",
    )
    parser.add_argument(
        "--top", type=int, default=15, help="Rows to show (0 = all, default 15)"
    )
    parser.add_argument(
        "--sort",
        choices=["total", "count", "avg", "max"],
        default="total",
        help="Sort groups by this metric (default total)",
    )
    parser.add_argument(
        "--min-ms",
        type=float,
        default=0.0,
        help="Hide groups whose total DB time is below this many ms",
    )
    parser.add_argument(
        "--min-delta-ms",
        type=float,
        default=0.5,
        help="Hide comparison rows whose total time changed less than this",
    )
    parser.add_argument(
        "--table",
        action="append",
        metavar="NAME",
        help="Only queries touching this table (repeatable)",
    )
    parser.add_argument(
        "--grep",
        metavar="REGEX",
        help="Only queries whose normalized SQL matches this regex",
    )
    parser.add_argument(
        "--duplicates-only",
        action="store_true",
        help="Only queries that ran more than once",
    )
    parser.add_argument(
        "--max-columns",
        type=int,
        default=8,
        help="Columns shown per SELECT before abbreviating (default 8)",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=0,
        help="Wrap SQL at this width (default: terminal width, or 100)",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Use a compact table instead of one block per query",
    )
    parser.add_argument(
        "--slowest",
        type=int,
        default=0,
        metavar="N",
        help="Also list the N slowest individual queries",
    )
    parser.add_argument(
        "--by-request",
        action="store_true",
        help="Add a per-request query count and DB time breakdown",
    )
    parser.add_argument(
        "--no-params",
        action="store_true",
        help="Do not show sample parameters next to each query",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of text",
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="PATH",
        help="Write the report to PATH instead of stdout (parents are created)",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    analysis = analyze_lines(read_lines(args.logfile))
    show_params = not args.no_params

    if args.compare:
        baseline = analyze_lines(read_lines(args.compare))
        if args.json:
            current_payload = analysis_to_dict(
                analysis,
                top=args.top,
                sort=args.sort,
                min_ms=args.min_ms,
                tables=args.table,
                grep=args.grep,
                duplicates_only=args.duplicates_only,
                max_columns=args.max_columns,
                by_request=args.by_request,
            )
            baseline_payload = analysis_to_dict(
                baseline,
                top=args.top,
                sort=args.sort,
                min_ms=args.min_ms,
                tables=args.table,
                grep=args.grep,
                duplicates_only=args.duplicates_only,
                max_columns=args.max_columns,
                by_request=args.by_request,
            )
            emit(
                json.dumps(
                    {"baseline": baseline_payload, "current": current_payload},
                    indent=2,
                ),
                args.output,
            )
            return 0
        emit(
            compare_analyses(
                baseline,
                analysis,
                min_delta_ms=args.min_delta_ms,
                top=args.top if args.top > 0 else 0,
                max_columns=args.max_columns,
                show_params=show_params,
            ),
            args.output,
        )
        return 0

    if args.json:
        emit(
            json.dumps(
                analysis_to_dict(
                    analysis,
                    top=args.top if args.top > 0 else 0,
                    sort=args.sort,
                    min_ms=args.min_ms,
                    tables=args.table,
                    grep=args.grep,
                    duplicates_only=args.duplicates_only,
                    max_columns=args.max_columns,
                    by_request=args.by_request,
                ),
                indent=2,
            ),
            args.output,
        )
        return 0

    width = args.width
    if not width:
        width = shutil.get_terminal_size((100, 24)).columns
        if not sys.stdout.isatty():
            width = 100
    emit(
        render_report(
            analysis,
            top=args.top,
            sort=args.sort,
            min_ms=args.min_ms,
            tables=args.table,
            grep=args.grep,
            duplicates_only=args.duplicates_only,
            max_columns=args.max_columns,
            show_params=show_params,
            by_request=args.by_request,
            slowest=args.slowest,
            width=width,
            as_table=args.compact,
        ),
        args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
