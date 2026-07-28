"""
Preprocessor registry — mirrors the ProviderRegistry pattern.

Register preprocessors by name, then look them up at pipeline runtime.
"""

from typing import Callable, Dict


class PreprocessorRegistry:
    """Registry of available text preprocessors."""

    _preprocessors: Dict[str, Callable] = {}

    @classmethod
    def register(cls, name: str, func: Callable) -> None:
        """Register a preprocessor function under *name*."""
        cls._preprocessors[name] = func

    @classmethod
    def get(cls, name: str) -> Callable:
        """Return the preprocessor registered under *name*.

        Raises ``KeyError`` if not found.
        """
        if name not in cls._preprocessors:
            raise KeyError(
                f"Unknown preprocessor '{name}'. "
                f"Available: {list(cls._preprocessors.keys())}"
            )
        return cls._preprocessors[name]

    @classmethod
    def available(cls) -> list[str]:
        """Return a list of registered preprocessor names."""
        return list(cls._preprocessors.keys())
