"""
Tests for the PreprocessorRegistry — pluggable text preprocessing steps.
"""

import pytest
from core.services.preprocessors.registry import PreprocessorRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _identity(text: str, params: dict | None = None) -> str:
    return text


def _upper(text: str, params: dict | None = None) -> str:
    return text.upper()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPreprocessorRegistry:
    """Unit tests for ``PreprocessorRegistry``."""

    def test_register_and_get(self):
        """After registration, ``get`` returns the registered function."""
        PreprocessorRegistry.register("_identity", _identity)
        func = PreprocessorRegistry.get("_identity")
        assert func("hello") == "hello"

    def test_get_unknown_raises_keyerror(self):
        """``get`` with an unregistered name raises ``KeyError``."""
        with pytest.raises(KeyError, match="Unknown preprocessor"):
            PreprocessorRegistry.get("nonexistent_xyz")

    def test_available_returns_names(self):
        """``available()`` lists all registered preprocessor names."""
        PreprocessorRegistry.register("_upper", _upper)
        names = PreprocessorRegistry.available()
        assert "_upper" in names

    def test_register_overwrites(self):
        """Re-registering under the same name replaces the function."""
        PreprocessorRegistry.register("_overwrite", _identity)
        PreprocessorRegistry.register("_overwrite", _upper)
        func = PreprocessorRegistry.get("_overwrite")
        assert func("hello") == "HELLO"
