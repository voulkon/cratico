"""
Tests for the noop preprocessor.
"""

from core.services.preprocessors.noop import noop


class TestNoopPreprocessor:
    """Unit tests for the noop preprocessor."""

    def test_returns_text_unchanged(self):
        """Text is returned exactly as provided."""
        assert noop("hello world") == "hello world"

    def test_empty_string(self):
        assert noop("") == ""

    def test_whitespace_only(self):
        assert noop("   \t\n  ") == "   \t\n  "

    def test_greek_text(self):
        greek = "Η απόφαση αυτή αφορά ανάθεση έργου"
        assert noop(greek) == greek

    def test_none_params_ignored(self):
        """Passing ``params=None`` is safe and returns text unchanged."""
        assert noop("text", params=None) == "text"

    def test_params_ignored(self):
        """Any extra params are silently ignored."""
        assert noop("text", params={"foo": "bar"}) == "text"
