"""
``recover_self_counterparts`` post-import task.

The task is a thin orchestrator: flag/hourly short-circuits, per-decision
isolation, counts, and targeted stats/cache refresh.  The recovery service
itself is covered by test_counterpart_recovery.py.
"""

from unittest.mock import patch

import pytest
from conftest import DecisionEntityRelationshipFactory, DecisionFactory

pytestmark = pytest.mark.django_db


def _enable_recovery(name):
    return name == "COUNTERPART_RECOVERY_ENABLED"


def test_skips_when_flag_disabled():
    from core.tasks.tasks_post_import import recover_self_counterparts

    with patch(
        "core.tasks.tasks_post_import.feature_flags.is_enabled",
        return_value=False,
    ):
        result = recover_self_counterparts(reference_date_str="2026-11-08")

    assert result == {"status": "skipped", "reason": "feature_flag_disabled"}


def test_skips_hourly_tail():
    from core.tasks.tasks_post_import import recover_self_counterparts

    result = recover_self_counterparts(
        reference_date_str="2026-11-08", tail_kind="hourly"
    )
    assert result == {"status": "skipped", "reason": "hourly_tail"}


def test_counts_isolates_errors_and_refreshes(monkeypatch):
    from core.tasks import tasks_post_import

    # The task closes stale persistent connections; inside a test transaction
    # that would close the connection pytest-django is using.
    monkeypatch.setattr("django.db.close_old_connections", lambda: None)

    recovered = DecisionFactory(ada="RECOVERED")
    review = DecisionFactory(ada="REVIEW")
    broken = DecisionFactory(ada="BROKEN")

    # A real relationship makes the task collect an affected entity id.
    DecisionEntityRelationshipFactory(decision=recovered)

    class FakeService:
        def get_candidates(self, **kwargs):
            return [recovered, review, broken]

        def recover_decision(self, decision):
            if decision.id == broken.id:
                raise RuntimeError("boom")
            if decision.id == recovered.id:
                return {
                    "status": "recovered",
                    "method": "AI_TEXT",
                    "chosen_afm": "899972873",
                }
            return {"status": "needs_review"}

    monkeypatch.setattr(
        "core.services.counterpart_recovery_service.CounterpartRecoveryService",
        FakeService,
    )

    recomputed = []
    monkeypatch.setattr(
        "core.services.afm_entity_stats_service.AFMEntityStatsService.compute_entities",
        lambda self, ids: recomputed.extend(ids),
    )
    invalidated = []
    monkeypatch.setattr(
        "core.services.response_cache_service.response_cache.invalidate_prefix",
        lambda prefix: invalidated.append(prefix) or 0,
    )

    with patch(
        "core.tasks.tasks_post_import.feature_flags.is_enabled",
        side_effect=_enable_recovery,
    ):
        result = tasks_post_import.recover_self_counterparts(
            reference_date_str="2026-11-08"
        )

    assert result["candidates"] == 3
    assert result["recovered"] == 1
    assert result["needs_review"] == 1
    assert result["errors"] == 1
    assert result["ai_calls"] == 1

    assert recomputed  # affected entity ids were refreshed
    assert "top_" in invalidated
    assert "browse" in invalidated
