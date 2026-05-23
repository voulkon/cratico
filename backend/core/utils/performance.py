import functools
import time

from django.db import connection, reset_queries
from loguru import logger


def query_debugger(func):
    @functools.wraps(func)
    def inner_func(*args, **kwargs):
        reset_queries()

        start_queries = len(connection.queries)
        start = time.perf_counter()
        result = func(*args, **kwargs)
        end = time.perf_counter()

        end_queries = len(connection.queries)

        # TODO: Actually write them in database so that I can analyze
        logger.debug(f"Function : {func.__name__}")
        logger.debug(f"Number of Queries : {end_queries - start_queries}")
        logger.debug(f"Finished in : {(end - start):.5f}s")

        return result

    return inner_func
