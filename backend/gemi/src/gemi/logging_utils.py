"""Logging utilities for the GEMI API client."""

import logging
import time
from functools import wraps


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Set up logging for the GEMI client."""
    logger = logging.getLogger("gemi")
    logger.setLevel(getattr(logging, level.upper()))

    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


def log_api_call(func):
    """Decorator to log API calls with timing and response info."""

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        logger = logging.getLogger("gemi.api")

        # Log request
        start_time = time.time()
        method = func.__name__.upper()
        endpoint = args[0] if args else "unknown"

        logger.debug(f"API Request: {method} {endpoint}")
        if kwargs.get("params"):
            logger.debug(f"Request params: {kwargs['params']}")

        try:
            result = func(self, *args, **kwargs)
            duration = time.time() - start_time
            logger.debug(
                f"API Response: {method} {endpoint} completed in {duration:.2f}s"
            )
            return result
        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                f"API Error: {method} {endpoint} failed after {duration:.2f}s: {e}"
            )
            raise

    return wrapper
