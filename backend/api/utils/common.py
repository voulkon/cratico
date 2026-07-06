"""Common utility functions for the API."""

# Re-export the canonical IP resolver for backward compatibility.
# New code should import directly from `api.utils.ip`.
from api.utils.ip import get_client_ip  # noqa: F401  (re-export)
