"""
Tests for diavgeia_project.settings.ai — default values and env-var parsing.
"""

import os
from importlib import reload

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# Helper
# ═══════════════════════════════════════════════════════════════════════════

def _reload_ai_settings():
    """Re-import the ai settings module to pick up env changes."""
    import diavgeia_project.settings.ai as ai_mod
    reload(ai_mod)
    return ai_mod


# ═══════════════════════════════════════════════════════════════════════════
# AI_SECRETS_KEY
# ═══════════════════════════════════════════════════════════════════════════


class TestAISecretsKey:

    def test_default_is_empty_string(self, monkeypatch):
        monkeypatch.delenv("AI_SECRETS_KEY", raising=False)
        mod = _reload_ai_settings()
        assert mod.AI_SECRETS_KEY == ""

    def test_reads_from_env(self, monkeypatch):
        monkeypatch.setenv("AI_SECRETS_KEY", "test-key-value")
        mod = _reload_ai_settings()
        assert mod.AI_SECRETS_KEY == "test-key-value"


# ═══════════════════════════════════════════════════════════════════════════
# OPENROUTER_API_KEY / OPENROUTER_API_BASE
# ═══════════════════════════════════════════════════════════════════════════


class TestOpenRouterSettings:

    def test_api_key_default_empty(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        mod = _reload_ai_settings()
        assert mod.OPENROUTER_API_KEY == ""

    def test_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-1234")
        mod = _reload_ai_settings()
        assert mod.OPENROUTER_API_KEY == "sk-or-v1-1234"

    def test_api_base_default(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_BASE", raising=False)
        mod = _reload_ai_settings()
        assert mod.OPENROUTER_API_BASE == "https://openrouter.ai/api/v1"

    def test_api_base_custom(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_BASE", "https://proxy.example.com/v1")
        mod = _reload_ai_settings()
        assert mod.OPENROUTER_API_BASE == "https://proxy.example.com/v1"


# ═══════════════════════════════════════════════════════════════════════════
# SYSTEM_AI_MONTHLY_CAP
# ═══════════════════════════════════════════════════════════════════════════


class TestSystemAIMonthlyCap:

    def test_default_is_zero(self, monkeypatch):
        monkeypatch.delenv("SYSTEM_AI_MONTHLY_CAP", raising=False)
        mod = _reload_ai_settings()
        assert mod.SYSTEM_AI_MONTHLY_CAP == 0.0

    def test_parses_float(self, monkeypatch):
        monkeypatch.setenv("SYSTEM_AI_MONTHLY_CAP", "150.75")
        mod = _reload_ai_settings()
        assert mod.SYSTEM_AI_MONTHLY_CAP == 150.75

    def test_parses_integer_string(self, monkeypatch):
        monkeypatch.setenv("SYSTEM_AI_MONTHLY_CAP", "200")
        mod = _reload_ai_settings()
        assert mod.SYSTEM_AI_MONTHLY_CAP == 200.0
        assert isinstance(mod.SYSTEM_AI_MONTHLY_CAP, float)

    def test_empty_string_yields_zero(self, monkeypatch):
        """os.getenv('X', '0') or '0' → float('0') → 0.0"""
        monkeypatch.setenv("SYSTEM_AI_MONTHLY_CAP", "")
        mod = _reload_ai_settings()
        assert mod.SYSTEM_AI_MONTHLY_CAP == 0.0

    def test_invalid_string_raises_value_error(self, monkeypatch):
        monkeypatch.setenv("SYSTEM_AI_MONTHLY_CAP", "not-a-number")
        with pytest.raises(ValueError):
            _reload_ai_settings()