import datetime
import os
from pathlib import Path


class VersionService:
    _instance = None
    _version = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(VersionService, cls).__new__(cls)
        return cls._instance

    def get_version(self):
        """Get the application version from version.txt."""
        if self._version is None:
            version_path = Path(__file__).parents[2] / "version" / "version.txt"
            try:
                with open(version_path, "r") as f:
                    self._version = f.read().strip()
            except FileNotFoundError:
                self._version = "unknown"
        return self._version

    def get_health_info(self):
        """Get health check information."""
        return {
            "status": "healthy",
            "version": self.get_version(),
            "timestamp": datetime.datetime.now().isoformat(),
            "environment": os.environ.get("DJANGO_ENV", "development"),
        }
