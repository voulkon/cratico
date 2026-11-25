"""
Profile one or more Django URLs in-process with per-query DB timings.

This exists for environments where ``DEBUG=True`` cannot be enabled (for
example, production).  Django only records ``connection.queries`` and emits
SQL logs when the debug cursor is active; ``CaptureQueriesContext`` enables it
for this process only, so no settings change, log-level change or restart is
needed.

The command accepts an API path, an organization page URL, or a temporal page
URL (``/explore/temporal/...``, ``/explore/month/...``, ``/explore/week/...``).
Page URLs expand to the same requests the frontend makes, which makes a cold
page measurement a single command.

Examples (inside the backend container):

    python manage.py profile_request \
      "/entity/organization/100054489?start_date=2025-11-01&end_date=2026-10-31"

    python manage.py profile_request --repeat 2 --db-info \
      "/api/decisions/unified/?source=entity&entity_type=organization&entity_id=100054489&view=date_range"

    python manage.py profile_request --explain --explain-min-ms 200 \
      "/api/organizations/100054489/top-counterparts/?start_date=2025-11-01&end_date=2026-10-31"

The first measured pass is usually cold.  A second pass (``--repeat 2``) shows
the warm-cache path.  If pass 1 is slow and pass 2 is fast, the fix is caching
or pre-warming.  If both are slow, the query itself is the problem and
``--explain`` shows why.
"""

from __future__ import annotations

import json

from core.services.request_profiler import (
    MAX_PROFILE_TARGETS,
    parse_profile_input,
    profile_requests,
    shorten,
)
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Run real Django requests in-process and report wall time, DB time, "
        "per-query timings and optional EXPLAIN ANALYZE plans."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "paths",
            nargs="*",
            help=(
                "API paths (/api/...), page URLs, cURL commands, or HAR JSON. "
                "Page URLs expand to the requests the frontend makes; cURL/HAR "
                "input is reduced to the GET /api/ calls the browser made."
            ),
        )
        parser.add_argument(
            "--har",
            action="append",
            default=[],
            metavar="PATH",
            help="HAR file to extract GET /api/ requests from (repeatable).",
        )
        parser.add_argument(
            "--method",
            default="GET",
            help="HTTP method (default: GET).",
        )
        parser.add_argument(
            "--host",
            default=None,
            help="Host header. Defaults to the first ALLOWED_HOSTS entry.",
        )
        parser.add_argument(
            "--client-ip",
            default="127.0.0.1",
            help="REMOTE_ADDR for the synthetic request (default: 127.0.0.1).",
        )
        parser.add_argument(
            "--token",
            default=None,
            help="DRF token sent as 'Authorization: Token …'.",
        )
        parser.add_argument(
            "--bearer",
            default=None,
            help="Clerk/JWT bearer token sent as 'Authorization: Bearer …'.",
        )
        parser.add_argument(
            "--header",
            action="append",
            default=[],
            metavar="NAME: VALUE",
            help="Extra request header (repeatable).",
        )
        parser.add_argument(
            "--user",
            default=None,
            help="Username or email to force_login as.",
        )
        parser.add_argument(
            "--insecure",
            action="store_true",
            help="Do not set the request scheme to https (secure=True).",
        )
        parser.add_argument(
            "--warmup",
            type=int,
            default=0,
            help="Requests to run before measuring (default: 0).",
        )
        parser.add_argument(
            "--repeat",
            type=int,
            default=1,
            help="Measured passes per path (default: 1; use 2 for cold+warm).",
        )
        parser.add_argument(
            "--top",
            type=int,
            default=10,
            help="Number of grouped query shapes to print (default: 10).",
        )
        parser.add_argument(
            "--no-sql",
            action="store_true",
            help="Hide SQL text and print only timings.",
        )
        parser.add_argument(
            "--bust-cache",
            action="store_true",
            help="Delete the known cache entries for the profiled paths first.",
        )
        parser.add_argument(
            "--explain",
            action="store_true",
            help="Run EXPLAIN (ANALYZE, BUFFERS) for slow SELECTs.",
        )
        parser.add_argument(
            "--explain-min-ms",
            type=float,
            default=200.0,
            help="Only EXPLAIN queries at or above this duration (default: 200).",
        )
        parser.add_argument(
            "--explain-top",
            type=int,
            default=3,
            help="Maximum number of query shapes to EXPLAIN (default: 3).",
        )
        parser.add_argument(
            "--explain-timeout-ms",
            type=int,
            default=30000,
            help="statement_timeout for EXPLAIN ANALYZE (default: 30000).",
        )
        parser.add_argument(
            "--db-info",
            action="store_true",
            help="Print database size and planner/memory settings.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit JSON instead of text.",
        )

    def handle(self, *args, **options):
        raw_inputs = list(options["paths"])
        for har_path in options["har"]:
            try:
                with open(har_path, encoding="utf-8") as har_file:
                    raw_inputs.append(har_file.read())
            except OSError as exc:
                raise CommandError(f"Could not read {har_path}: {exc}") from exc

        paths = []
        for raw in raw_inputs:
            try:
                paths.extend(parse_profile_input(raw))
            except ValueError as exc:
                raise CommandError(str(exc)) from exc

        paths = list(dict.fromkeys(paths))
        if len(paths) > MAX_PROFILE_TARGETS:
            self.stderr.write(
                f"Profiling only the first {MAX_PROFILE_TARGETS} of "
                f"{len(paths)} API calls."
            )
            paths = paths[:MAX_PROFILE_TARGETS]
        if not paths:
            raise CommandError("No GET /api/ requests found in the input.")

        payload = profile_requests(
            paths,
            method=options["method"].upper(),
            host=options["host"],
            token=options["token"],
            bearer=options["bearer"],
            headers=options["header"],
            user=options["user"],
            insecure=options["insecure"],
            warmup=options["warmup"],
            repeat=options["repeat"],
            explain=options["explain"],
            explain_min_ms=options["explain_min_ms"],
            explain_top=options["explain_top"],
            explain_timeout_ms=options["explain_timeout_ms"],
            include_db_info=options["db_info"],
            client_ip=options["client_ip"],
            bust_cache=options["bust_cache"],
        )

        if options["json"]:
            self.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False))
            return

        if options["db_info"]:
            self._print_db_info(payload["db"])
        if payload["cache_busted"]:
            self.stdout.write(f"Deleted {len(payload['cache_busted'])} cache key(s).")

        for result in payload["requests"]:
            self._print_result(result, options)

    def _print_db_info(self, info):
        if not info:
            return
        self.stdout.write("Database")
        for key in (
            "server_addr",
            "database_name",
            "server_version",
            "postmaster_start_time",
            "database_size",
            "shared_buffers",
            "effective_cache_size",
            "work_mem",
            "maintenance_work_mem",
            "random_page_cost",
            "effective_io_concurrency",
            "max_parallel_workers_per_gather",
        ):
            if key in info:
                self.stdout.write(f"  {key}: {info[key]}")
        if info.get("error"):
            self.stdout.write(f"  error: {info['error']}")
        for table in info.get("largest_tables") or []:
            self.stdout.write(f"  {table['table']}: {table['size']}")
        self.stdout.write("")

    def _print_result(self, result, options):
        self.stdout.write("")
        self.stdout.write(
            f"{result['method']} {result['path']}  (pass {result['iteration']})"
        )
        self.stdout.write(
            f"  status={result['status']}  "
            f"wall={result['wall_ms']:.1f}ms  "
            f"db={result['db_ms']:.1f}ms ({result['db_pct']:.1f}%)  "
            f"queries={result['query_count']}  "
            f"response={result['response_bytes'] / 1024:.1f}KB"
        )

        for line in result["cache"]["summary"]:
            self.stdout.write(f"  cache: {line}")
        for line in result["cache"]["defer"]:
            self.stdout.write(f"  cache: {line}")
        if result.get("defer"):
            retry_after = result["defer"].get("retry_after")
            self.stdout.write(
                "  defer: 202 warming"
                + (f"; retry after {retry_after}s" if retry_after else "")
                + " (frontend retries up to 5x; the query runs in the warmup task)"
            )

        if result.get("error"):
            self.stdout.write("  error:")
            for line in result["error"].splitlines():
                self.stdout.write(f"    {line}")

        if result.get("body_preview"):
            self.stdout.write("  body:")
            for line in result["body_preview"].splitlines():
                self.stdout.write(f"    {line}")

        groups = result["queries"]["groups"][: max(0, options["top"])]
        if groups:
            self.stdout.write("  slowest query shapes:")
            for index, group in enumerate(groups, start=1):
                tables = ", ".join(group["tables"][:4]) or "?"
                self.stdout.write(
                    f"    {index:>2}. {group['total_ms']:>9.1f}ms total  "
                    f"{group['count']:>3}×  max {group['max_ms']:>7.1f}ms  "
                    f"[{tables}]"
                )
                if not options["no_sql"]:
                    self.stdout.write(f"        {shorten(group['sql'])}")

        for plan in result.get("explain") or []:
            self.stdout.write(
                f"  EXPLAIN ANALYZE ({plan['duration_ms']:.1f}ms observed) "
                f"[{', '.join(plan['tables'][:4])}]"
            )
            for line in plan["plan"]:
                self.stdout.write(f"    {line}")
