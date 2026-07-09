"""
Tests for the shared decision-projection layer
(``core.services.decision_projections``).
"""

from datetime import datetime, timezone

import pytest

from core.models.decisions import Decision
from core.services.decision_projections import (
    aggregate_decision_types,
    compute_date_range,
    compute_statistics,
    paginate_decisions,
)


@pytest.mark.django_db
class TestAggregateDecisionTypes:
    """
    Tests for ``aggregate_decision_types`` — the canonical fix for the
    "duplicate decision-type rows" bug (grouping by uid, not label).
    """

    def test_basic_aggregation(self, decision_type):
        """Two decisions of the same type → one row with count=2."""
        from conftest import DecisionFactory

        dt = decision_type
        dt.uid = "Δ001"
        dt.label = "Ανάθεση"
        dt.save()
        DecisionFactory(decision_type=dt, amount=100)
        DecisionFactory(decision_type=dt, amount=200)

        qs = Decision.objects.all()
        result = aggregate_decision_types(qs)

        assert result["total_types"] == 1
        assert result["decision_types"][0]["uid"] == "Δ001"
        assert result["decision_types"][0]["count"] == 2
        assert result["decision_types"][0]["total_amount"] == 300.0

    def test_no_duplicate_rows_for_same_uid(self):
        """
        Even if two DecisionType rows share the same UID but have
        different labels, we should get exactly ONE row (using Max(label)).
        """
        from conftest import DecisionFactory, DecisionTypeFactory

        dt1 = DecisionTypeFactory(uid="Δ001", label="Label A")
        dt2 = DecisionTypeFactory(uid="Δ001", label="Label B")
        DecisionFactory(decision_type=dt1, amount=50)
        DecisionFactory(decision_type=dt2, amount=150)

        qs = Decision.objects.all()
        result = aggregate_decision_types(qs)

        assert result["total_types"] == 1
        row = result["decision_types"][0]
        assert row["uid"] == "Δ001"
        assert row["count"] == 2
        assert row["total_amount"] == 200.0
        # Max(label) picks one of the labels
        assert row["label"] in ("Label A", "Label B")

    def test_multiple_types(self):
        """Multiple types → separate rows, ordered by count descending."""
        from conftest import DecisionFactory, DecisionTypeFactory

        dt_a = DecisionTypeFactory(uid="ΔA", label="Type A")
        dt_b = DecisionTypeFactory(uid="ΔB", label="Type B")
        DecisionFactory(decision_type=dt_a)  # 1
        DecisionFactory(decision_type=dt_b)  # 1
        DecisionFactory(decision_type=dt_b)  # 2
        DecisionFactory(decision_type=dt_b)  # 3

        qs = Decision.objects.all()
        result = aggregate_decision_types(qs)

        assert result["total_types"] == 2
        # Most frequent first
        assert result["decision_types"][0]["uid"] == "ΔB"
        assert result["decision_types"][0]["count"] == 3
        assert result["decision_types"][1]["uid"] == "ΔA"
        assert result["decision_types"][1]["count"] == 1

    def test_null_decision_type_excluded(self, decision_type):
        """Decisions with no decision_type are excluded."""
        from conftest import DecisionFactory

        DecisionFactory(decision_type=None, amount=100)

        qs = Decision.objects.all()
        result = aggregate_decision_types(qs)

        assert result["total_types"] == 0
        assert result["decision_types"] == []

    def test_empty_queryset(self):
        """Empty queryset → empty result."""
        qs = Decision.objects.none()
        result = aggregate_decision_types(qs)
        assert result == {"decision_types": [], "total_types": 0}


@pytest.mark.django_db
class TestPaginateDecisions:
    """Tests for ``paginate_decisions``."""

    def test_pagination_structure(self, decision_type):
        """Returns the expected keys."""
        from conftest import DecisionFactory

        for i in range(25):
            DecisionFactory(ada=f"ADA{i:06d}", decision_type=decision_type)

        qs = Decision.objects.all()
        result = paginate_decisions(qs, page=1, page_size=10)

        assert "results" in result
        assert "pagination" in result
        assert result["pagination"]["current_page"] == 1
        assert result["pagination"]["page_size"] == 10
        assert result["pagination"]["total_count"] == 25
        assert result["pagination"]["total_pages"] == 3
        assert result["pagination"]["has_next"] is True
        assert result["pagination"]["has_previous"] is False
        assert len(result["results"]) == 10

    def test_second_page(self, decision_type):
        """Second page has correct metadata."""
        from conftest import DecisionFactory

        for i in range(25):
            DecisionFactory(ada=f"ADA{i:06d}", decision_type=decision_type)

        qs = Decision.objects.all().order_by("id")
        result = paginate_decisions(qs, page=2, page_size=10)

        assert result["pagination"]["current_page"] == 2
        assert result["pagination"]["has_previous"] is True
        assert result["pagination"]["has_next"] is True
        assert len(result["results"]) == 10

    def test_last_page(self, decision_type):
        """Last page has has_next=False."""
        from conftest import DecisionFactory

        for i in range(25):
            DecisionFactory(ada=f"ADA{i:06d}", decision_type=decision_type)

        qs = Decision.objects.all().order_by("id")
        result = paginate_decisions(qs, page=3, page_size=10)

        assert result["pagination"]["current_page"] == 3
        assert result["pagination"]["has_next"] is False
        assert len(result["results"]) == 5

    def test_empty_queryset(self):
        """Empty queryset → empty results."""
        qs = Decision.objects.none()
        result = paginate_decisions(qs, page=1, page_size=20)

        assert result["results"] == []
        assert result["pagination"]["total_count"] == 0


@pytest.mark.django_db
class TestComputeStatistics:
    """Tests for ``compute_statistics``."""

    def test_basic_stats(self, decision_type):
        from conftest import DecisionFactory

        DecisionFactory(ada="A1", amount=100, decision_type=decision_type)
        DecisionFactory(ada="A2", amount=200, decision_type=decision_type)
        DecisionFactory(ada="A3", amount=300, decision_type=decision_type)

        qs = Decision.objects.all()
        result = compute_statistics(qs)

        assert result["summary"]["decisions"]["total_count"] == 3
        assert result["summary"]["decisions"]["total_amount"] == 600.0
        assert result["summary"]["decisions"]["avg_amount"] == 200.0
        assert "organizations_count" in result["summary"]

    def test_empty_queryset(self):
        qs = Decision.objects.none()
        result = compute_statistics(qs)

        assert result["summary"]["decisions"]["total_count"] == 0
        assert result["summary"]["decisions"]["total_amount"] == 0.0


@pytest.mark.django_db
class TestComputeDateRange:
    """Tests for ``compute_date_range``."""

    def test_has_data(self, decision_type):
        from conftest import DecisionFactory
        from datetime import datetime, timezone

        DecisionFactory(
            ada="OLD",
            issue_date=datetime(2020, 1, 1, tzinfo=timezone.utc),
            decision_type=decision_type,
        )
        DecisionFactory(
            ada="NEW",
            issue_date=datetime(2024, 12, 31, tzinfo=timezone.utc),
            decision_type=decision_type,
        )

        qs = Decision.objects.all()
        result = compute_date_range(qs)

        assert result["has_data"] is True
        assert result["date_range"] is not None
        # earliest/latest are ISO strings (dates from the DB, not datetimes)
        assert "2020-01-01" in str(result["date_range"]["earliest"])
        assert "2024-12-31" in str(result["date_range"]["latest"])
        assert result["summary"]["total_decisions"] == 2
        assert "activity_chart" in result
        assert len(result["activity_chart"]["data"]) > 0

    def test_no_data(self):
        """Empty queryset → has_data=False."""
        qs = Decision.objects.none()
        result = compute_date_range(qs)

        assert result["has_data"] is False
        assert result["date_range"] is None
