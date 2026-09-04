"""
Per-request search trace (debug tooling for the search pipeline).

Enabled by DEBUG_SEARCH_SERVICE=1. When active, every search request gets a
short search_id and each step (tier resolution, transliteration, per-type
query, fallback merge) is recorded. A single structured summary line is
emitted at the end — one line per request in Loki/Grafana, filterable by
search_id or query.

Zero overhead when disabled: all helpers are no-ops and query_debugger
passes through untouched.
"""

import contextvars
import uuid
from typing import Any, Dict, Optional

from django.conf import settings
from loguru import logger

try:
    DEBUG_SEARCH_SERVICE = settings.DEBUG_SEARCH_SERVICE
except AttributeError:
    # Settings not loaded yet (e.g. imported during app loading) — fall back
    # to the env var directly.
    import os

    DEBUG_SEARCH_SERVICE = os.getenv("DEBUG_SEARCH_SERVICE", "False").lower() in (
        "true",
        "1",
        "t",
    )

# The active trace for this request/task. Contextvar so it survives
# async contexts and doesn't leak between threads.
_current_trace: contextvars.ContextVar[Optional["SearchTrace"]] = (
    contextvars.ContextVar("search_trace", default=None)
)


class SearchTrace:
    """Collects events for one search request."""

    def __init__(self, query: str):
        self.search_id = uuid.uuid4().hex[:8]
        self.query = query
        self.events: list[Dict[str, Any]] = []

    def add(self, event_type: str, **data: Any) -> None:
        data["event"] = event_type
        self.events.append(data)

    def summary(self) -> Dict[str, Any]:
        """Flatten the trace into a single loggable dict."""
        steps = []
        for ev in self.events:
            parts = [ev["event"]]
            parts += [f"{k}={v}" for k, v in ev.items() if k != "event"]
            steps.append(" ".join(parts))

        # Percentage breakdown of measured query time per search function.
        # Only meaningful for type_search events (they carry duration_ms).
        durations = {
            ev["func"]: ev["duration_ms"]
            for ev in self.events
            if ev.get("event") == "type_search" and "duration_ms" in ev
        }
        total_ms = sum(durations.values())
        breakdown = (
            {
                func: f"{round(ms / total_ms * 100)}%"
                for func, ms in sorted(
                    durations.items(), key=lambda kv: kv[1], reverse=True
                )
            }
            if total_ms
            else {}
        )

        return {
            "search_id": self.search_id,
            "query": self.query,
            "total_ms": round(total_ms),
            "breakdown": breakdown,
            "steps": steps,
        }


def get_current_trace() -> Optional[SearchTrace]:
    if not DEBUG_SEARCH_SERVICE:
        return None
    return _current_trace.get()


def start_search_trace(query: str) -> Optional[SearchTrace]:
    """Begin tracing a search request. Returns the trace (or None if disabled)."""
    if not DEBUG_SEARCH_SERVICE:
        return None
    trace = SearchTrace(query)
    _current_trace.set(trace)
    return trace


def finish_search_trace(trace: Optional[SearchTrace]) -> None:
    """Emit the one-line summary and clear the context."""
    if trace is None:
        return
    _current_trace.set(None)
    summary = trace.summary()
    breakdown = " ".join(
        f"{func}={pct}" for func, pct in summary["breakdown"].items()
    )
    with logger.contextualize(
        search_id=summary["search_id"],
        search_query=summary["query"],
        search_total_ms=summary["total_ms"],
    ):
        logger.info(
            "SEARCH_TRACE query={q} total={total}ms breakdown=[{breakdown}] "
            "steps=[{steps}]",
            q=summary["query"],
            total=summary["total_ms"],
            breakdown=breakdown,
            steps="; ".join(summary["steps"]),
        )
