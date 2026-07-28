"""Preprocessors package — pluggable text preprocessing steps."""

from .registry import PreprocessorRegistry
from core.services.preprocessors import noop  # noqa: F401
from core.services.preprocessors import regex_strip  # noqa: F401

__all__ = ["PreprocessorRegistry"]
