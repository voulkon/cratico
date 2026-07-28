"""
Pipeline step executors package.

Each executor implements ``execute(step, step_run, context, run)`` and
mutates the ``PipelineContext`` + ``PipelineStepRun``.

Importing this package registers all built-in preprocessors and makes the
``STEP_EXECUTORS`` dict available.
"""

# Register built-in preprocessors so they're available when steps run
from core.services.preprocessors import noop as _noop  # noqa: F401
from core.services.preprocessors import regex_strip as _regex_strip  # noqa: F401

from .aggregate import AggregateStep
from .ai_call import AICallStep
from .extract import ExtractStep
from .preprocess import PreprocessStep

STEP_EXECUTORS = {
    "EXTRACT": ExtractStep,
    "PREPROCESS": PreprocessStep,
    "AI_CALL": AICallStep,
    "AGGREGATE": AggregateStep,
}

__all__ = ["STEP_EXECUTORS"]
