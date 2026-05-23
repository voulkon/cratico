"""Rate limiting that can be shared across client instances."""

import time
from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Dict, Optional


@dataclass
class RateLimitState:
    """Shared rate limiting state for an API key."""

    last_429_time: Optional[float] = None
    consecutive_429s: int = 0
    backoff_until: Optional[float] = None
    request_times: deque = None  # For tracking request frequency

    def __post_init__(self):
        if self.request_times is None:
            self.request_times = deque()


class SharedRateLimiter:
    """Shared rate limiter that can be used across multiple client instances."""

    _state_by_api_key: Dict[str, RateLimitState] = {}
    _lock = Lock()

    @classmethod
    def get_state(cls, api_key: str) -> RateLimitState:
        """Get or create rate limit state for an API key."""
        with cls._lock:
            if api_key not in cls._state_by_api_key:
                cls._state_by_api_key[api_key] = RateLimitState()
            return cls._state_by_api_key[api_key]

    @classmethod
    def should_back_off(cls, api_key: str) -> Optional[float]:
        """Check if we should back off due to recent rate limiting."""
        state = cls.get_state(api_key)

        if state.backoff_until and time.time() < state.backoff_until:
            return state.backoff_until - time.time()

        return None

    @classmethod
    def record_429_response(cls, api_key: str, retry_after: Optional[int] = None):
        """Record that we got a 429 response."""
        state = cls.get_state(api_key)

        with cls._lock:
            state.last_429_time = time.time()
            state.consecutive_429s += 1

            # Calculate backoff time
            if retry_after:
                backoff_time = retry_after
            else:
                # Exponential backoff: 60s, 120s, 240s, etc.
                backoff_time = min(
                    60 * (2 ** (state.consecutive_429s - 1)), 600
                )  # Max 10 minutes

            state.backoff_until = time.time() + backoff_time

    @classmethod
    def record_successful_request(cls, api_key: str):
        """Record a successful request (resets consecutive 429s)."""
        state = cls.get_state(api_key)

        with cls._lock:
            state.consecutive_429s = 0
            state.backoff_until = None

            # Track request timing for future rate limit prediction
            now = time.time()
            state.request_times.append(now)

            # Keep only last minute of requests (for 8 req/min limit)
            while state.request_times and now - state.request_times[0] > 60:
                state.request_times.popleft()

    @classmethod
    def get_request_count_last_minute(cls, api_key: str) -> int:
        """Get number of requests in the last minute."""
        state = cls.get_state(api_key)
        now = time.time()

        # Clean old requests
        while state.request_times and now - state.request_times[0] > 60:
            state.request_times.popleft()

        return len(state.request_times)

    @classmethod
    def clear_state(cls, api_key: Optional[str] = None):
        """Clear rate limit state (useful for testing)."""
        with cls._lock:
            if api_key:
                cls._state_by_api_key.pop(api_key, None)
            else:
                cls._state_by_api_key.clear()
