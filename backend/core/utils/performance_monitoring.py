"""
Performance monitoring utilities for the diavgeia application.
This provides a lightweight, non-database approach to monitoring query performance.
"""

import json
import time
from collections import defaultdict, deque
from datetime import datetime
from functools import wraps
from typing import Any, Dict, Optional

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from loguru import logger


class PerformanceMonitor:
    """
    Lightweight performance monitor that stores metrics in memory/cache
    instead of database to avoid write overhead.
    """

    def __init__(self):
        self.metrics = defaultdict(
            lambda: {
                "total_calls": 0,
                "total_time": 0.0,
                "avg_time": 0.0,
                "max_time": 0.0,
                "min_time": float("inf"),
                "slow_calls": 0,  # calls > 1 second
                "recent_calls": deque(maxlen=100),  # Keep last 100 calls
            }
        )
        self.slow_threshold = 1.0  # seconds

    def record_performance(
        self,
        function_name: str,
        execution_time: float,
        query_count: int,
        context: Dict[str, Any] = None,
    ):
        """Record performance metrics for a function call."""

        metrics = self.metrics[function_name]
        metrics["total_calls"] += 1
        metrics["total_time"] += execution_time
        metrics["avg_time"] = metrics["total_time"] / metrics["total_calls"]
        metrics["max_time"] = max(metrics["max_time"], execution_time)
        metrics["min_time"] = min(metrics["min_time"], execution_time)

        if execution_time > self.slow_threshold:
            metrics["slow_calls"] += 1

        # Store recent call details
        call_info = {
            "timestamp": datetime.now().isoformat(),
            "execution_time": execution_time,
            "query_count": query_count,
            "context": context or {},
        }
        metrics["recent_calls"].append(call_info)

        # Log slow calls immediately
        if execution_time > self.slow_threshold:
            logger.warning(
                f"Slow function call: {function_name} took {execution_time:.2f}s "
                f"with {query_count} queries. Context: {context}"
            )

        # Store aggregated metrics in cache (lightweight persistence)
        self._cache_metrics(function_name, metrics)

    def _cache_metrics(self, function_name: str, metrics: Dict[str, Any]):
        """Store metrics in cache for persistence across requests."""
        cache_key = f"perf_metrics:{function_name}"

        # Convert deque to list for JSON serialization
        cacheable_metrics = dict(metrics)
        cacheable_metrics["recent_calls"] = list(metrics["recent_calls"])

        cache.set(cache_key, cacheable_metrics, timeout=3600)  # 1 hour

    def get_performance_summary(
        self, function_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get performance summary for analysis."""
        if function_name:
            return dict(self.metrics.get(function_name, {}))

        # Return summary of all functions
        summary = {}
        for func_name, metrics in self.metrics.items():
            summary[func_name] = {
                "total_calls": metrics["total_calls"],
                "avg_time": metrics["avg_time"],
                "max_time": metrics["max_time"],
                "slow_calls": metrics["slow_calls"],
                "slow_percentage": (
                    (metrics["slow_calls"] / metrics["total_calls"] * 100)
                    if metrics["total_calls"] > 0
                    else 0
                ),
            }
        return summary

    def export_metrics_for_analysis(self) -> str:
        """Export metrics as JSON for external analysis."""
        exportable_data = {}
        for func_name, metrics in self.metrics.items():
            exportable_data[func_name] = {
                "summary": {
                    "total_calls": metrics["total_calls"],
                    "avg_time": metrics["avg_time"],
                    "max_time": metrics["max_time"],
                    "min_time": metrics["min_time"],
                    "slow_calls": metrics["slow_calls"],
                },
                "recent_calls": list(metrics["recent_calls"]),
            }
        return json.dumps(exportable_data, indent=2, default=str)


# Global monitor instance
performance_monitor = PerformanceMonitor()


def monitor_query_performance(
    func=None, *, include_context=False, threshold=1.0, operation=None
):
    """
    Decorator to monitor query performance without database overhead.

    Args:
        include_context: Whether to include function arguments in monitoring
        threshold: Time threshold in seconds to consider a call "slow"
        operation: Custom operation name for monitoring (defaults to function name)

    Usage:
        @monitor_query_performance
        def my_function():
            pass

        @monitor_query_performance(include_context=True, threshold=0.5, operation="custom_name")
        def my_slow_function(entity_id, date_range):
            pass
    """

    def decorator(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            start_queries = len(connection.queries)

            try:
                result = function(*args, **kwargs)
                success = True
            except Exception:
                success = False
                raise
            finally:
                end_time = time.time()
                end_queries = len(connection.queries)
                execution_time = end_time - start_time
                query_count = end_queries - start_queries

                # Prepare context information
                context = {}
                if include_context:
                    context.update(
                        {
                            "args_count": len(args),
                            "kwargs_keys": list(kwargs.keys()),
                            "success": success,
                        }
                    )

                    # Include specific context for financial service methods
                    if "entity" in kwargs:
                        context["entity_afm"] = getattr(kwargs["entity"], "afm", None)
                    if "organization" in kwargs:
                        context["org_uid"] = getattr(
                            kwargs["organization"], "uid", None
                        )

                # Use operation name if provided, otherwise use function name
                operation_name = operation or function.__name__

                # Record the performance
                performance_monitor.record_performance(
                    operation_name, execution_time, query_count, context
                )

            return result

        return wrapper

    # Handle both @monitor_query_performance and @monitor_query_performance()
    if func is None:
        return decorator
    else:
        return decorator(func)


def get_performance_report() -> Dict[str, Any]:
    """Get a comprehensive performance report."""
    return performance_monitor.get_performance_summary()


def export_performance_data() -> str:
    """Export performance data for external analysis."""
    return performance_monitor.export_metrics_for_analysis()


# Management command helper
def log_performance_summary():
    """Log current performance summary - useful for management commands."""
    summary = performance_monitor.get_performance_summary()

    if not summary:
        logger.info("No performance data collected yet.")
        return

    logger.info("=== PERFORMANCE SUMMARY ===")
    for func_name, metrics in summary.items():
        logger.info(
            f"{func_name}: {metrics['total_calls']} calls, "
            f"avg: {metrics['avg_time']:.3f}s, "
            f"max: {metrics['max_time']:.3f}s, "
            f"slow: {metrics['slow_calls']} ({metrics['slow_percentage']:.1f}%)"
        )


# API endpoint for getting performance data (for development)
def get_performance_api_data() -> Dict[str, Any]:
    """Format performance data for API consumption."""
    summary = performance_monitor.get_performance_summary()

    # Sort by average time descending
    sorted_functions = sorted(
        summary.items(), key=lambda x: x[1].get("avg_time", 0), reverse=True
    )

    return {
        "timestamp": datetime.now().isoformat(),
        "total_functions_monitored": len(summary),
        "functions": dict(sorted_functions),
        "top_slow_functions": [
            {
                "name": name,
                "avg_time": metrics["avg_time"],
                "slow_percentage": metrics["slow_percentage"],
            }
            for name, metrics in sorted_functions[:10]
            if metrics["slow_percentage"] > 0
        ],
    }


# Settings-based configuration
class PerformanceConfig:
    """Configuration for performance monitoring."""

    @property
    def enabled(self) -> bool:
        return getattr(settings, "PERFORMANCE_MONITORING_ENABLED", True)

    @property
    def slow_threshold(self) -> float:
        return getattr(settings, "PERFORMANCE_SLOW_THRESHOLD", 1.0)

    @property
    def log_slow_queries(self) -> bool:
        return getattr(settings, "PERFORMANCE_LOG_SLOW_QUERIES", True)

    @property
    def include_query_details(self) -> bool:
        return getattr(settings, "PERFORMANCE_INCLUDE_QUERY_DETAILS", settings.DEBUG)

    @property
    def sample_rate(self) -> float:
        """Control sampling rate (0.0-1.0)"""
        return getattr(settings, "PERFORMANCE_SAMPLE_RATE", 1.0)

    @property
    def max_recent_calls(self) -> int:
        """Control memory usage"""
        return getattr(settings, "PERFORMANCE_MAX_RECENT_CALLS", 100)


perf_config = PerformanceConfig()
