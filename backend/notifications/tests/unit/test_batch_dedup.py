"""
Regression tests for duplicate ``NotificationBatch`` rows (bug 2026-09-15).

Two *concurrent* checks of the same subscription used to each create their own
batch for the same decision, because none of the three layers that were
supposed to stop it could:

1. the "already in a batch?" pre-check is a read-then-write, so a second run
   that read before the first run committed sees nothing;
2. ``NotificationBatch.unique_subscription_time_window`` cannot dedupe the two
   runs either — ``check_window_start`` / ``check_window_end`` are derived from
   ``timezone.now()`` and therefore differ by microseconds per run (production:
   batch 459 ``…03.576Z`` vs batch 460 ``…03.557Z``);
3. the loser's junction rows are then silently dropped by
   ``NotificationBatchDecision.unique_subscription_decision``
   (``ignore_conflicts=True``), leaving an empty duplicate batch behind whose
   ``match_count`` still claims a decision — the ``"No decisions in batch to
   summarize"`` fingerprint seen on batch 460.

``test_concurrent_check_does_not_create_a_second_batch`` reproduces that
interleaving deterministically: it deliberately forces the pre-check to report
"nothing batched yet", which is exactly what a run that read before the other
committed would see.  It fails before the fix and passes after it.

The last test pins the second half of the bug: the AI summarization task must
be queued only after the creating transaction has committed, otherwise the
worker can read the batch before its decisions are visible.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


@pytest.fixture
def subscription(user, organization):
    from conftest import NotificationSubscriptionFactory

    return NotificationSubscriptionFactory(user=user, organization=organization)


@pytest.fixture
def decision(organization):
    from conftest import DecisionFactory

    return DecisionFactory(
        organization=organization,
        subject="Decision for the batch-dedup regression test",
        publish_timestamp=timezone.now(),
    )


def _create_batch(subscription, decisions, start, end):
    from notifications.tasks.notification_tasks import create_batch_for_matches

    return create_batch_for_matches(subscription, decisions, start, end)


# ---------------------------------------------------------------------------
# Race emulation
# ---------------------------------------------------------------------------
#
# A real race needs two overlapping transactions, which a single-threaded test
# cannot produce.  Instead we reproduce the exact interleaving that matters:
# the second run's "already in a batch?" read happens BEFORE the first run's
# junction row is visible.  Everything after that read runs against the real
# table — which is what makes the second run's ``bulk_create`` hit
# ``unique_subscription_decision`` and get its rows ignored.


class _StaleReadResult:
    """Stands in for a queryset evaluated before the other run committed."""

    def values_list(self, *args, **kwargs):
        return []

    def __iter__(self):
        return iter([])


class _StaleThenRealManager:
    """``NotificationBatchDecision.objects`` with one deliberately stale read.

    Only the first pre-check (``filter(subscription=…, decision__in=…)``)
    returns nothing; every later query is served by the real manager.
    """

    def __init__(self, real_manager):
        self._real = real_manager
        self._stale_read_used = False

    def filter(self, *args, **kwargs):
        is_precheck = "subscription" in kwargs and "decision__in" in kwargs
        if is_precheck and not self._stale_read_used:
            self._stale_read_used = True
            return _StaleReadResult()
        return self._real.filter(*args, **kwargs)

    def __getattr__(self, item):
        return getattr(self._real, item)


class _ModelWithStaleManager:
    """``NotificationBatchDecision`` whose manager does one stale read."""

    def __init__(self, real_model):
        self._real_model = real_model
        # Built once: the "stale read" budget belongs to the patched model,
        # not to each ``.objects`` access.
        self._manager = _StaleThenRealManager(real_model.objects)

    @property
    def objects(self):
        return self._manager

    def __call__(self, *args, **kwargs):
        return self._real_model(*args, **kwargs)

    def __getattr__(self, item):
        return getattr(self._real_model, item)


def test_concurrent_check_does_not_create_a_second_batch(subscription, decision):
    """The loser of the race must discard its batch instead of leaving a
    duplicate (and empty) one behind."""
    from notifications.models import NotificationBatch, NotificationBatchDecision
    from notifications.tasks import notification_tasks

    start = timezone.now()
    end = start + timedelta(days=1)

    # First run wins the race and commits its junction row.
    first = _create_batch(subscription, [decision], start, end)
    assert first["decisions_added"] == 1

    # Second, concurrent run: its pre-check read before the first run's row
    # became visible, so it still believes nothing is batched.  Its own check
    # window is now()-derived, so ``unique_subscription_time_window`` does not
    # stop it either — only ``unique_subscription_decision`` does, by silently
    # dropping the junction rows.
    with patch.object(
        notification_tasks,
        "NotificationBatchDecision",
        _ModelWithStaleManager(NotificationBatchDecision),
    ):
        second = _create_batch(
            subscription,
            [decision],
            start + timedelta(seconds=1),
            end + timedelta(seconds=1),
        )

    batches = NotificationBatch.objects.filter(subscription=subscription)
    assert batches.count() == 1, "a second (empty) batch was left behind"

    batch = batches.get()
    assert first["batch_id"] == batch.id
    assert second["batch_id"] == batch.id
    assert second["decisions_added"] == 0
    assert second["all_duplicates"] is True

    # No phantom counts: the batch claims exactly the decisions it owns.
    assert batch.match_count == batch.batch_decisions.count() == 1
    assert (
        NotificationBatchDecision.objects.filter(
            subscription=subscription, decision=decision
        ).count()
        == 1
    )


def test_sequential_recheck_keeps_a_single_batch(subscription, decision):
    """Idempotency for the plain (non-racing) re-run case must be preserved."""
    from notifications.models import NotificationBatch

    start = timezone.now()
    end = start + timedelta(days=1)

    first = _create_batch(subscription, [decision], start, end)
    second = _create_batch(subscription, [decision], end, end + timedelta(days=1))

    assert NotificationBatch.objects.filter(subscription=subscription).count() == 1
    assert second["batch_id"] == first["batch_id"]
    assert second["decisions_added"] == 0
    assert second["all_duplicates"] is True


def test_ai_summary_is_queued_only_after_commit(subscription, decision):
    """A summary task dispatched inside the open transaction can read the
    batch before its decisions are committed → "No decisions in batch to
    summarize"."""
    start = timezone.now()

    subscription.ai_summary_enabled = True
    subscription.save(update_fields=["ai_summary_enabled"])

    with (
        patch("django.db.transaction.on_commit") as on_commit,
        patch(
            "notifications.tasks.ai_summary_tasks.summarize_notification_batch.delay"
        ) as delay,
    ):
        result = _create_batch(
            subscription, [decision], start, start + timedelta(days=1)
        )

        assert result["decisions_added"] == 1

        # Nothing may be queued while the transaction is still open.
        delay.assert_not_called()
        on_commit.assert_called_once()

        # …and the callback registered for the commit dispatches it.
        on_commit.call_args.args[0]()
        delay.assert_called_once_with(batch_id=result["batch_id"])
