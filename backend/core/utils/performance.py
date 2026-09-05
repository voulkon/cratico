import functools
import time

from django.conf import settings
from django.db import connection, reset_queries
from loguru import logger

from core.utils.search_trace import get_current_trace

# SEARCH_SLOW_QUERY_THRESHOLD lives in settings/logging.py (seconds, 0=off).
# Read lazily so tests can override via override_settings. The debug-trace
# toggle is the DEBUG_SEARCH_SERVICE feature flag, checked once per request
# inside start_search_trace (see search_trace.py).


def _slow_query_threshold() -> float:
    return float(getattr(settings, "SEARCH_SLOW_QUERY_THRESHOLD", 0) or 0)


def query_debugger(func):
    @functools.wraps(func)
    def inner_func(*args, **kwargs):
        SLOW_THRESHOLD = _slow_query_threshold()
        trace = get_current_trace()

        if trace is None and not SLOW_THRESHOLD:
            return func(*args, **kwargs)

        reset_queries()

        start_queries = len(connection.queries)
        start = time.perf_counter()
        result = func(*args, **kwargs)
        duration = time.perf_counter() - start

        end_queries = len(connection.queries)

        # If the decorated function returns a lazy QuerySet, force evaluation
        # so the timing reflects the actual SQL, not just query construction.
        # NOTE: end_queries is re-captured AFTER evaluation so the trace's
        # query_count includes the actual search SQL, not just queries run
        # during query construction (e.g. prerequisite checks).
        result_count = None
        if trace is not None and hasattr(result, "__iter__") and hasattr(
            result, "query"
        ):
            result = list(result)
            result_count = len(result)
            duration = time.perf_counter() - start
            end_queries = len(connection.queries)

        if trace is not None:
            trace.add(
                "type_search",
                func=func.__name__,
                duration_ms=round(duration * 1000, 1),
                count=result_count,
                query_count=end_queries - start_queries,
            )

        # Structured single line: Grafana/Loki-friendly (E6-style).
        # Bind extra fields so JSON logging picks them up as record.extra.*.
        with logger.contextualize(
            search_func=func.__name__,
            duration_ms=round(duration * 1000, 1),
            query_count=end_queries - start_queries,
        ):
            if SLOW_THRESHOLD and duration >= SLOW_THRESHOLD:
                logger.warning(
                    "SLOW_SEARCH query_debugger: func={func} duration={dur:.3f}s "
                    "queries={qc}",
                    func=func.__name__,
                    dur=duration,
                    qc=end_queries - start_queries,
                )
            elif trace is not None:
                logger.info(
                    "SEARCH_TIMING func={func} duration={dur:.3f}s queries={qc}",
                    func=func.__name__,
                    dur=duration,
                    qc=end_queries - start_queries,
                )

        return result

    return inner_func
