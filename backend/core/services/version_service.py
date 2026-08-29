import datetime
import os
import tomllib
from pathlib import Path


class VersionService:
    _instance = None
    _version = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(VersionService, cls).__new__(cls)
        return cls._instance

    @staticmethod
    def _pyproject_path() -> Path:
        return Path(__file__).parents[2] / "pyproject.toml"

    @classmethod
    def _reset_cache(cls):
        """Clear cached version. Intended for tests."""
        cls._version = None

    def get_version(self):
        """Get the application version from pyproject.toml (single source of truth)."""
        # Cache on the CLASS (type(self)._version) so the singleton instance never
        # shadows it with an instance attribute that _reset_cache() can't clear.
        cls = type(self)
        if cls._version is None:
            try:
                with open(self._pyproject_path(), "rb") as f:
                    cls._version = tomllib.load(f)["tool"]["poetry"]["version"]
            except (FileNotFoundError, KeyError):
                cls._version = "unknown"
        return cls._version

    @staticmethod
    def get_git_sha():
        """Git commit SHA baked into the Docker image at build time."""
        return os.environ.get("GIT_SHA", "unknown")

    def get_health_info(self):
        """Get health check information."""
        return {
            "status": "healthy",
            "version": self.get_version(),
            "git_sha": self.get_git_sha(),
            "timestamp": datetime.datetime.now().isoformat(),
            "environment": os.environ.get("DJANGO_ENV", "development"),
        }
