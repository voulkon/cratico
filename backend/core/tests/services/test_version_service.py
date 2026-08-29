import tomllib

import pytest

from core.services.version_service import VersionService


@pytest.fixture(autouse=True)
def reset_version_cache():
    """Each test gets a fresh version cache."""
    VersionService._reset_cache()
    yield
    VersionService._reset_cache()


class TestGetVersion:
    def test_reads_version_from_pyproject(self):
        """Version matches the real pyproject.toml (single source of truth)."""
        with open(VersionService._pyproject_path(), "rb") as f:
            expected = tomllib.load(f)["tool"]["poetry"]["version"]

        assert VersionService().get_version() == expected
        assert expected != "unknown"

    def test_caches_version(self):
        service = VersionService()
        first = service.get_version()
        # Even if the cache-reset static is bypassed, second call returns cached value
        assert service.get_version() is first

    def test_missing_pyproject_returns_unknown(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            VersionService, "_pyproject_path", staticmethod(lambda: tmp_path / "nope.toml")
        )
        assert VersionService().get_version() == "unknown"

    def test_pyproject_without_version_returns_unknown(self, tmp_path, monkeypatch):
        fake_pyproject = tmp_path / "pyproject.toml"
        fake_pyproject.write_text('[tool.poetry]\nname = "x"\n')
        monkeypatch.setattr(
            VersionService, "_pyproject_path", staticmethod(lambda: fake_pyproject)
        )
        assert VersionService().get_version() == "unknown"


class TestGetGitSha:
    def test_git_sha_from_env(self, monkeypatch):
        monkeypatch.setenv("GIT_SHA", "abc1234")
        assert VersionService.get_git_sha() == "abc1234"

    def test_git_sha_defaults_to_unknown(self, monkeypatch):
        monkeypatch.delenv("GIT_SHA", raising=False)
        assert VersionService.get_git_sha() == "unknown"


class TestHealthInfo:
    def test_shape_and_values(self, monkeypatch):
        monkeypatch.setenv("GIT_SHA", "deadbeef")
        monkeypatch.setenv("DJANGO_ENV", "production")

        info = VersionService().get_health_info()

        assert info["status"] == "healthy"
        assert info["version"] == VersionService().get_version()
        assert info["git_sha"] == "deadbeef"
        assert info["environment"] == "production"
        # Timestamp parses as ISO 8601
        from datetime import datetime

        datetime.fromisoformat(info["timestamp"])
