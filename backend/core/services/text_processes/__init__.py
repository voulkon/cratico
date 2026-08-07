"""
Text process registry.

Mirrors the ``STEP_EXECUTORS`` pattern in ``pipeline_engine.py``: each
process is registered by slug and dispatched by ``TextProcessService``.
Importing this package registers all built-in processes.
"""

from .amount import AmountProcess
from .amount_grouped import GroupedAmountProcess
from .dates import DateProcess

TEXT_PROCESSES = {
    AmountProcess.slug: AmountProcess,
    GroupedAmountProcess.slug: GroupedAmountProcess,
    DateProcess.slug: DateProcess,
}

__all__ = ["TEXT_PROCESSES", "AmountProcess", "GroupedAmountProcess", "DateProcess"]
