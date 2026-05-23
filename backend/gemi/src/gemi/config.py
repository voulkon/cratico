"""Configuration management for the GEMI API client."""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class GemiConfig:
    """Configuration settings for the GEMI API client."""

    api_key: Optional[str] = None
    base_url: str = "https://opendata-api.businessportal.gr/api/opendata/v1"
    timeout: int = 30
    max_retries: int = 3
    rate_limit_retry: bool = True

    @classmethod
    def from_env(cls) -> "GemiConfig":
        """Create configuration from environment variables."""
        return cls(
            api_key=os.getenv("GEMI_API_KEY"),
            base_url=os.getenv("GEMI_BASE_URL", cls.base_url),
            timeout=int(os.getenv("GEMI_TIMEOUT", str(cls.timeout))),
            max_retries=int(os.getenv("GEMI_MAX_RETRIES", str(cls.max_retries))),
            rate_limit_retry=os.getenv("GEMI_RATE_LIMIT_RETRY", "true").lower()
            == "true",
        )

    def validate(self) -> None:
        """Validate configuration settings."""
        if not self.api_key:
            raise ValueError("API key is required")
        if self.timeout <= 0:
            raise ValueError("Timeout must be positive")
        if self.max_retries < 0:
            raise ValueError("Max retries must be non-negative")
