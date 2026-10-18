"""
Tests for the ``backfill_one_liners`` management command.

The command resolves its target decisions, skips decisions without cached
extraction text (unless ``--with-extraction``), and enqueues
``generate_decision_one_liner`` per remaining decision — billed to the
resolved user.
"""

from unittest.mock import patch

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db


def _make_admin_user():
    from conftest import AdminUserFactory

    # AdminUserFactory (not UserFactory kwargs): the factory's
    # django_get_or_create("username") can return a pre-existing user and
    # silently ignore override kwargs.
    return AdminUserFactory(email="admin@example.com")


class TestBackfillOneLiners:
    def test_dispatches_per_decision_with_extraction(self):
        from conftest import DecisionFactory, DocumentExtractionFactory

        admin = _make_admin_user()
        d1 = DecisionFactory(ada="ADA_BF1")
        d2 = DecisionFactory(ada="ADA_BF2")
        DocumentExtractionFactory(decision=d1, raw_text="T1.")
        DocumentExtractionFactory(decision=d2, raw_text="T2.")

        with patch(
            "core.tasks.tasks_decision_ai.generate_decision_one_liner.delay"
        ) as mock_delay:
            call_command("backfill_one_liners", ada=["ADA_BF1", "ADA_BF2"])

        assert mock_delay.call_count == 2
        called_ids = {c.kwargs["decision_id"] for c in mock_delay.call_args_list}
        assert called_ids == {d1.id, d2.id}
        # All dispatches billed to the resolved superuser (NOT a hardcoded
        # id — Postgres sequences do not reset between tests in a session).
        assert all(c.kwargs["user_id"] == admin.id for c in mock_delay.call_args_list)

    def test_skips_decisions_without_cached_text(self):
        from conftest import DecisionFactory

        _make_admin_user()
        no_text = DecisionFactory(ada="ADA_BF3")
        with_text = DecisionFactory(ada="ADA_BF4")
        from conftest import DocumentExtractionFactory

        DocumentExtractionFactory(decision=with_text, raw_text="T.")

        with patch(
            "core.tasks.tasks_decision_ai.generate_decision_one_liner.delay"
        ) as mock_delay:
            call_command("backfill_one_liners", ada=["ADA_BF3", "ADA_BF4"])

        called_ids = {c.kwargs["decision_id"] for c in mock_delay.call_args_list}
        assert called_ids == {with_text.id}
        assert no_text.id not in called_ids

    def test_with_extraction_flag_includes_missing_text(self):
        from conftest import DecisionFactory

        _make_admin_user()
        no_text = DecisionFactory(ada="ADA_BF5")

        with patch(
            "core.tasks.tasks_decision_ai.generate_decision_one_liner.delay"
        ) as mock_delay:
            call_command(
                "backfill_one_liners", ada=["ADA_BF5"], with_extraction=True
            )

        assert mock_delay.call_count == 1
        assert mock_delay.call_args.kwargs["decision_id"] == no_text.id

    def test_limit_caps_dispatch(self):
        from conftest import DecisionFactory, DocumentExtractionFactory

        _make_admin_user()
        for i in range(3):
            d = DecisionFactory(ada=f"ADA_BFL{i}")
            DocumentExtractionFactory(decision=d, raw_text=f"T{i}.")

        with patch(
            "core.tasks.tasks_decision_ai.generate_decision_one_liner.delay"
        ) as mock_delay:
            call_command("backfill_one_liners", since="2000-01-01", limit=2)

        assert mock_delay.call_count == 2

    def test_force_flag_forwarded(self):
        from conftest import DecisionFactory, DocumentExtractionFactory

        _make_admin_user()
        d = DecisionFactory(ada="ADA_BFF")
        DocumentExtractionFactory(decision=d, raw_text="T.")

        with patch(
            "core.tasks.tasks_decision_ai.generate_decision_one_liner.delay"
        ) as mock_delay:
            call_command("backfill_one_liners", ada=["ADA_BFF"], force=True)

        assert mock_delay.call_args.kwargs["force"] is True

    def test_unknown_ada_fails(self):
        _make_admin_user()
        with patch(
            "core.tasks.tasks_decision_ai.generate_decision_one_liner.delay"
        ) as mock_delay:
            with pytest.raises(Exception) as exc_info:
                call_command("backfill_one_liners", ada=["ADA_MISSING"])
        assert "No decisions found" in str(exc_info.value)
        mock_delay.assert_not_called()

    def test_user_email_billing(self):
        from conftest import DecisionFactory, DocumentExtractionFactory, UserFactory

        bill_to = UserFactory(email="ops@example.com")
        d = DecisionFactory(ada="ADA_BFU")
        DocumentExtractionFactory(decision=d, raw_text="T.")

        with patch(
            "core.tasks.tasks_decision_ai.generate_decision_one_liner.delay"
        ) as mock_delay:
            call_command(
                "backfill_one_liners", ada=["ADA_BFU"], user_email="ops@example.com"
            )

        assert mock_delay.call_args.kwargs["user_id"] == bill_to.id
