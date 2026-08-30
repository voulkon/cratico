import pytest
from core.tasks.tasks_decisions_import import store_decisions_from_pickle


@pytest.mark.django_db(transaction=True)
def test_store_decisions_from_pickle_is_deprecated(a_pickle_to_store):
    """
    The pickle-based import path has been deprecated in favour of the Redis
    pipeline (fetch_daily_decisions_to_redis → store_decisions_from_redis).

    We intentionally do NOT test the old import behaviour here — it is no
    longer used — but we keep a regression test so anyone relying on the
    legacy task name gets a clear, expected failure instead of a silent no-op.
    """
    with pytest.raises(NotImplementedError, match="deprecated"):
        store_decisions_from_pickle.run(str(a_pickle_to_store))
