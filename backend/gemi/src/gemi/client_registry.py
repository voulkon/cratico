"""Client factory/registry pattern for managing GEMI client instances."""

from threading import Lock
from typing import Dict, Optional

from gemi.src.client import GemiDataClient
from gemi.src.config import GemiConfig


class GemiClientRegistry:
    """Registry for managing GEMI client instances with shared rate limiting."""

    _instances: Dict[str, GemiDataClient] = {}
    _lock = Lock()

    @classmethod
    def get_client(
        cls, config_name: str = "default", config: Optional[GemiConfig] = None
    ) -> GemiDataClient:
        """
        Get or create a client instance with the given configuration.

        Args:
            config_name: Name for this configuration (e.g., "default", "high_timeout", "test")
            config: GemiConfig instance, or None to use environment variables

        Returns:
            GemiDataClient instance that's shared across the application
        """
        with cls._lock:
            if config_name not in cls._instances:
                if config is None:
                    config = GemiConfig.from_env()

                client = GemiDataClient.from_config(config)
                cls._instances[config_name] = client

            return cls._instances[config_name]

    @classmethod
    def clear_registry(cls):
        """Clear all cached clients (useful for testing)."""
        with cls._lock:
            cls._instances.clear()

    @classmethod
    def get_default_client(cls) -> GemiDataClient:
        """Get the default client instance."""
        return cls.get_client("default")


# Usage throughout your application:


# In your main application setup
def setup_gemi_clients():
    """Set up different client configurations."""

    # Default client with standard settings
    default_config = GemiConfig.from_env()
    GemiClientRegistry.get_client("default", default_config)

    # High-timeout client for batch operations
    batch_config = GemiConfig(
        api_key=default_config.api_key,
        timeout=120,  # 2 minutes for batch operations
        max_retries=5,
    )
    GemiClientRegistry.get_client("batch", batch_config)


# In your services
class CompanyService:
    def __init__(self):
        # All instances will share the same client (and rate limits)
        self.gemi_client = GemiClientRegistry.get_default_client()

    def find_company(self, name: str):
        return self.gemi_client.companies.search_companies(name=name)


class BatchService:
    def __init__(self):
        # Use high-timeout client for batch operations
        self.gemi_client = GemiClientRegistry.get_client("batch")

    def process_many_companies(self, gemh_numbers: list):
        results = []
        for gemh in gemh_numbers:
            company = self.gemi_client.companies.get_company(gemh)
            results.append(company)
        return results


# In your tests
def test_company_service():
    # Clear any existing clients
    GemiClientRegistry.clear_registry()

    # Set up test client
    test_config = GemiConfig(
        api_key="test-key", base_url="https://test-api.example.com"
    )
    GemiClientRegistry.get_client("default", test_config)

    # Now all services will use the test client
    CompanyService()
    # ... test logic
