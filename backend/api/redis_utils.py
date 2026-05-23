"""
Utility functions for working with Redis.
"""

from django.core.cache import cache


def safe_incr(key, amount=1, timeout=None):
    """
    Safely increment a counter in Redis, creating it if it doesn't exist.

    Args:
        key: The Redis key
        amount: How much to increment by
        timeout: Optional TTL in seconds, None means no expiration

    Returns:
        The new value after incrementing
    """
    try:
        return cache.incr(key, amount)
    except ValueError:
        # Key doesn't exist, create it
        cache.set(key, amount, timeout=timeout)
        return amount
