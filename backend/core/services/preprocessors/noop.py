"""Noop preprocessor — returns text unchanged."""

from .registry import PreprocessorRegistry


def noop(text: str, params: dict | None = None) -> str:
    """Return *text* unchanged."""
    return text


PreprocessorRegistry.register("noop", noop)
