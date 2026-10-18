"""
Unit tests for ``dispatch_summaries_then_email`` — the chord callback that
runs the user's batch summaries BEFORE the consolidated email.

Also covers the ``send_consolidated_email_for_user`` header_result override
used when it runs as the summaries-chord body.
"""

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db


HEADER_RESULT = {
    "user_id": 7,
    "batches_created": 2,
    "total_decisions": 5,
    "errors": 0,
    "batch_ids": [11, 12, 13],
    "new_batch_ids": [11, 12],
}


def _call(args=(HEADER_RESULT,), user_id=7):
    from notifications.tasks.notification_tasks import dispatch_summaries_then_email

    return dispatch_summaries_then_email(*args, user_id=user_id)


class TestDispatchSummariesThenEmail:

    def test_dispatches_inner_chord_for_new_batches(self):
        """
        With new_batch_ids present, an inner chord runs one
        ``summarize_notification_batch`` task per new batch, with the email
        task as its body (forwarding the header result).

        The email task is NOT patched here: ``.s()`` only builds a signature
        (no broker interaction) and ``chord`` itself is mocked.
        """
        with patch(
            "notifications.tasks.notification_tasks.chord"
        ) as mock_chord:
            result = _call()

        mock_chord.assert_called_once()
        header = mock_chord.call_args[0][0]
        # Header: a celery group of summarize signatures — one per new batch
        tasks = list(header.tasks)
        assert len(tasks) == 2
        assert [t.args[0] for t in tasks] == [11, 12]
        assert all(
            t.task.endswith("summarize_notification_batch") for t in tasks
        )

        # Body: the email task with the original header result forwarded
        body = mock_chord.return_value.call_args[0][0]
        assert body.kwargs["user_id"] == 7
        assert body.kwargs["header_result"] == HEADER_RESULT

        assert result == {
            "user_id": 7,
            "summaries_dispatched": 2,
            "email_deferred": True,
        }

    def test_emails_directly_when_no_new_batches(self):
        """Empty new_batch_ids → email directly with the header result."""
        header = {**HEADER_RESULT, "new_batch_ids": []}

        with patch(
            "notifications.tasks.notification_tasks.chord"
        ) as mock_chord, patch(
            "notifications.tasks.notification_tasks.send_consolidated_email_for_user",
            return_value={"user_id": 7, "batches_emailed": 3, "success": True},
        ) as mock_email_task:
            result = _call(args=(header,))

        mock_chord.assert_not_called()
        mock_email_task.assert_called_once_with(header, user_id=7)
        assert result == {"user_id": 7, "batches_emailed": 3, "success": True}

    def test_emails_directly_without_usable_header_result(self):
        """
        No usable header result (e.g. raw/unwrapped args) → no summaries
        can be identified; email runs directly on its own fallback.
        """
        with patch(
            "notifications.tasks.notification_tasks.chord"
        ) as mock_chord, patch(
            "notifications.tasks.notification_tasks.send_consolidated_email_for_user",
            return_value={"user_id": 7, "batches_emailed": 0, "success": True},
        ) as mock_email_task:
            result = _call(args=())

        mock_chord.assert_not_called()
        mock_email_task.assert_called_once_with(user_id=7)
        assert result == {"user_id": 7, "batches_emailed": 0, "success": True}

    def test_unwraps_single_element_header_list(self):
        """Celery wraps single-header results in a list — unwrap one level."""
        with patch(
            "notifications.tasks.notification_tasks.chord"
        ) as mock_chord, patch(
            "notifications.tasks.notification_tasks.send_consolidated_email_for_user"
        ):
            _call(args=([HEADER_RESULT],))

        header = mock_chord.call_args[0][0]
        assert len(list(header.tasks)) == 2

    def test_missing_user_id_returns_error(self):
        result = _call(user_id=None)
        assert result == {
            "user_id": None,
            "summaries_dispatched": 0,
            "success": False,
        }


class TestSendConsolidatedEmailHeaderOverride:
    """``send_consolidated_email_for_user`` header_result override kwarg."""

    @pytest.fixture(autouse=True)
    def verified_user(self, user):
        """Email sending requires a verified address."""
        user.email_verified = True
        user.save(update_fields=["email_verified"])
        return user

    def test_header_result_override_wins_over_args(self, user):
        """
        As the summaries-chord body, *args hold summary results (useless);
        the forwarded header_result must drive the batch selection.
        """
        from conftest import NotificationBatchFactory
        from notifications.tasks.notification_tasks import (
            send_consolidated_email_for_user,
        )

        batch = NotificationBatchFactory(user=user, email_sent=False)

        with patch(
            "core.email_service.NotificationEmailService.send_consolidated_batch_summary",
            return_value=True,
        ) as mock_send:
            result = send_consolidated_email_for_user(
                [{"status": "COMPLETED"}],  # summary results, not header data
                user_id=user.id,
                header_result={"batch_ids": [batch.id]},
            )

        assert result["success"] is True
        assert result["batches_emailed"] == 1
        kwargs = mock_send.call_args.kwargs
        # Only the override batch was emailed
        assert [b["id"] for b in kwargs["batches"]] == [batch.id]

    def test_batch_data_includes_ai_summary_items(self, user):
        """Email batch data carries ai_summary_items for the template bullets."""
        from conftest import NotificationBatchFactory
        from notifications.tasks.notification_tasks import (
            send_consolidated_email_for_user,
        )

        items = [
            {
                "decision_id": 42,
                "ada": "ΩΡΞΨ65Ν6Ζ-ΡΓΔ",
                "subject": "Some decision",
                "one_liner": "Εγκρίθηκε δαπάνη.",
            }
        ]
        batch = NotificationBatchFactory(
            user=user,
            email_sent=False,
            ai_summary_status="COMPLETED",
            ai_summary_items=items,
        )

        with patch(
            "core.email_service.NotificationEmailService.send_consolidated_batch_summary",
            return_value=True,
        ) as mock_send:
            send_consolidated_email_for_user(
                {"batch_ids": [batch.id]}, user_id=user.id
            )

        batch_entry = mock_send.call_args.kwargs["batches"][0]
        assert batch_entry["ai_summary_status"] == "COMPLETED"
        assert batch_entry["ai_summary_items"] == items

    def test_batch_data_defaults_items_to_empty_list(self, user):
        """AI-disabled batches get an empty items list, not None."""
        from conftest import NotificationBatchFactory
        from notifications.tasks.notification_tasks import (
            send_consolidated_email_for_user,
        )

        batch = NotificationBatchFactory(
            user=user,
            email_sent=False,
            ai_summary_status="SKIPPED",
            ai_summary_items=None,
        )

        with patch(
            "core.email_service.NotificationEmailService.send_consolidated_batch_summary",
            return_value=True,
        ) as mock_send:
            send_consolidated_email_for_user(
                {"batch_ids": [batch.id]}, user_id=user.id
            )

        batch_entry = mock_send.call_args.kwargs["batches"][0]
        assert batch_entry["ai_summary_items"] == []
