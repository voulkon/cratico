"""
Text process registry.

Mirrors the ``STEP_EXECUTORS`` pattern in ``pipeline_engine.py``: each
process is registered by slug and dispatched by ``TextProcessService``.
Importing this package registers all built-in processes.
"""

from .amount import AmountProcess
from .dates import DateProcess

TEXT_PROCESSES = {
    AmountProcess.slug: AmountProcess,
    DateProcess.slug: DateProcess,
}

__all__ = ["TEXT_PROCESSES", "AmountProcess", "DateProcess"]
