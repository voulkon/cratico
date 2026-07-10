"""
Tests for the shared decision-facet layer (``core.services.decision_facets``).

These tests are pure unit tests — they verify that each facet function
correctly transforms a Decision queryset without hitting the database.
"""

from datetime import datetime, timedelta, timezone

import pytest
from django.db.models import QuerySet
from django.test import RequestFactory

from core.models.decisions import Decision
from core.services.decision_facets import (
    apply_amount_range,
    apply_date_range,
    apply_decision_facets,
    apply_decision_type_filter,
    apply_direct_assignments_only,
    apply_search,
    apply_sort,
    apply_viewed,
    parse_amount_range,
    parse_date_range_from_request,
    parse_decision_type_uids,
    parse_direct_assignments_only,
    parse_sort_by,
    parse_viewed,
)


# ── Date-range parsing ──────────────────────────────────────────────

class TestParseDateRangeFromRequest:
    """Tests for ``parse_date_range_from_request``."""

    def test_both_dates_valid(self, rf: RequestFactory):
        req = rf.get("/", {"start_date": "2024-01-01", "end_date": "2024-12-31"})
        start, end, err = parse_date_range_from_request(req)
        assert err is None
        assert start is not None
        assert end is not None
        assert start.date().isoformat() == "2024-01-01"
        assert end.date().isoformat() == "2024-12-31"

    def test_only_start_date(self, rf: RequestFactory):
        req = rf.get("/", {"start_date": "2024-06-15"})
        start, end, err = parse_date_range_from_request(req)
        assert err is None
        assert start is not None
        assert end is None
        assert start.date().isoformat() == "2024-06-15"

    def test_only_end_date(self, rf: RequestFactory):
        req = rf.get("/", {"end_date": "2024-06-15"})
        start, end, err = parse_date_range_from_request(req)
        assert err is None
        assert start is None
        assert end is not None
        assert end.date().isoformat() == "2024-06-15"

    def test_no_dates(self, rf: RequestFactory):
        req = rf.get("/")
        start, end, err = parse_date_range_from_request(req)
        assert err is None
        assert start is None
        assert end is None

    def test_invalid_start_date(self, rf: RequestFactory):
        req = rf.get("/", {"start_date": "not-a-date"})
        _start, _end, err = parse_date_range_from_request(req)
        assert err is not None
        assert err.status_code == 400

    def test_invalid_end_date(self, rf: RequestFactory):
        req = rf.get("/", {"end_date": "garbage"})
        _start, _end, err = parse_date_range_from_request(req)
        assert err is not None
        assert err.status_code == 400


# ── Amount-range parsing ────────────────────────────────────────────

class TestParseAmountRange:
    """Tests for ``parse_amount_range``."""

    def test_both_amounts(self, rf: RequestFactory):
        req = rf.get("/", {"min_amount": "100", "max_amount": "5000"})
        lo, hi, err = parse_amount_range(req)
        assert err is None
        assert lo == 100.0
        assert hi == 5000.0

    def test_invalid_amount(self, rf: RequestFactory):
        req = rf.get("/", {"min_amount": "abc"})
        _lo, _hi, err = parse_amount_range(req)
        assert err is not None
        assert err.status_code == 400

    def test_missing_amounts(self, rf: RequestFactory):
        req = rf.get("/")
        lo, hi, err = parse_amount_range(req)
        assert err is None
        assert lo is None
        assert hi is None


# ── Decision-type parsing ───────────────────────────────────────────

class TestParseDecisionTypeUids:
    """Tests for ``parse_decision_type_uids``."""

    def test_comma_separated(self, rf: RequestFactory):
        req = rf.get("/", {"decision_types": "Δ1,Δ2, Δ3"})
        uids = parse_decision_type_uids(req)
        assert uids == ["Δ1", "Δ2", "Δ3"]

    def test_empty(self, rf: RequestFactory):
        req = rf.get("/")
        uids = parse_decision_type_uids(req)
        assert uids == []

    def test_whitespace_only(self, rf: RequestFactory):
        req = rf.get("/", {"decision_types": "  ,  "})
        uids = parse_decision_type_uids(req)
        assert uids == []


# ── Sort parsing ────────────────────────────────────────────────────

class TestParseSortBy:
    """Tests for ``parse_sort_by``."""

    def test_explicit_sort(self, rf: RequestFactory):
        req = rf.get("/", {"sort_by": "amount_desc"})
        assert parse_sort_by(req) == "amount_desc"

    def test_default(self, rf: RequestFactory):
        req = rf.get("/")
        assert parse_sort_by(req) == "recent"

    def test_custom_default(self, rf: RequestFactory):
        req = rf.get("/")
        assert parse_sort_by(req, default="oldest") == "oldest"


# ── Direct-assignments-only parsing ─────────────────────────────────

class TestParseDirectAssignmentsOnly:
    """Tests for ``parse_direct_assignments_only``."""

    @pytest.mark.parametrize("val", ["true", "True", "1", "yes", "YES"])
    def test_truthy(self, rf: RequestFactory, val: str):
        req = rf.get("/", {"direct_assignments_only": val})
        assert parse_direct_assignments_only(req) is True

    @pytest.mark.parametrize("val", ["false", "0", "no", ""])
    def test_falsey(self, rf: RequestFactory, val: str):
        req = rf.get("/", {"direct_assignments_only": val})
        assert parse_direct_assignments_only(req) is False

    def test_missing(self, rf: RequestFactory):
        req = rf.get("/")
        assert parse_direct_assignments_only(req) is False


# ── Viewed parsing ──────────────────────────────────────────────────

class TestParseViewed:
    """Tests for ``parse_viewed``."""

    @pytest.mark.parametrize("val,expected", [
        ("true", "true"),
        ("True", "true"),
        ("false", "false"),
        ("False", "false"),
    ])
    def test_explicit(self, rf: RequestFactory, val: str, expected: str):
        req = rf.get("/", {"viewed": val})
        assert parse_viewed(req) == expected

    def test_all_or_missing_is_none(self, rf: RequestFactory):
        req = rf.get("/", {"viewed": "all"})
        assert parse_viewed(req) is None
        req2 = rf.get("/")
        assert parse_viewed(req2) is None


# ── Composite: apply_decision_facets ────────────────────────────────

@pytest.mark.django_db
class TestApplyDecisionFacets:
    """Integration-level tests for the composite facet applier."""

    def test_empty_facets_noop(self, decision, decision_type):
        """No facets → same queryset (no filters applied)."""
        from conftest import DecisionFactory

        d1 = decision
        d2 = DecisionFactory(ada="ADA000002", decision_type=decision_type)
        qs = Decision.objects.all()
        result = apply_decision_facets(qs, sort_by="recent")
        ids = set(result.values_list("id", flat=True))
        assert d1.id in ids
        assert d2.id in ids

    def test_sort_recent(self, decision_type):
        """Sort by recent puts newest first."""
        from conftest import DecisionFactory
        from datetime import datetime, timezone

        old = DecisionFactory(
            ada="OLD", issue_date=datetime(2020, 1, 1, tzinfo=timezone.utc),
            decision_type=decision_type,
        )
        new = DecisionFactory(
            ada="NEW", issue_date=datetime(2024, 6, 15, tzinfo=timezone.utc),
            decision_type=decision_type,
        )
        qs = Decision.objects.all()
        result = apply_decision_facets(qs, sort_by="recent")
        ids = list(result.values_list("id", flat=True))
        assert ids[0] == new.id

    def test_search_filters_subject(self, decision_type):
        """Search filters by subject substring."""
        from conftest import DecisionFactory

        d1 = DecisionFactory(subject="Προμήθεια γραφικής ύλης", decision_type=decision_type)
        d2 = DecisionFactory(subject="Ανάθεση έργου καθαριότητας", decision_type=decision_type)
        qs = Decision.objects.all()
        result = apply_decision_facets(qs, search_query="προμήθεια")
        ids = set(result.values_list("id", flat=True))
        assert d1.id in ids
        assert d2.id not in ids

    def test_decision_type_filter(self, decision_type):
        """Filter by decision type UIDs."""
        from conftest import DecisionFactory, DecisionTypeFactory

        dt_a = decision_type
        dt_a.uid = "ΔA"
        dt_a.save()
        dt_b = DecisionTypeFactory(uid="ΔB")
        d1 = DecisionFactory(ada="A1", decision_type=dt_a)
        d2 = DecisionFactory(ada="B1", decision_type=dt_b)
        qs = Decision.objects.all()
        result = apply_decision_facets(qs, decision_type_uids=["ΔA"])
        ids = set(result.values_list("id", flat=True))
        assert d1.id in ids
        assert d2.id not in ids

    def test_amount_range(self, decision_type):
        """Filter by min and max amount."""
        from conftest import DecisionFactory, DecisionAmountFieldFactory

        d_low = DecisionFactory(ada="LOW", decision_type=decision_type)
        d_mid = DecisionFactory(ada="MID", decision_type=decision_type)
        d_high = DecisionFactory(ada="HIGH", decision_type=decision_type)
        DecisionAmountFieldFactory(decision=d_low, amount=50)
        DecisionAmountFieldFactory(decision=d_mid, amount=500)
        DecisionAmountFieldFactory(decision=d_high, amount=5000)
        qs = Decision.objects.all()
        result = apply_decision_facets(qs, min_amount=100, max_amount=1000)
        ids = set(result.values_list("id", flat=True))
        assert d_low.id not in ids
        assert d_mid.id in ids
        assert d_high.id not in ids

    def test_direct_assignments_only_filters_correctly(self, decision_type):
        """direct_assignments_only=True keeps only decisions whose
        DecisionClassification.is_direct_assignment is True."""
        from conftest import DecisionFactory
        from core.models.decision_classification import DecisionClassification

        d_direct = DecisionFactory(ada="DIRECT", decision_type=decision_type)
        d_indirect = DecisionFactory(ada="INDIRECT", decision_type=decision_type)
        d_no_class = DecisionFactory(ada="NOCLASS", decision_type=decision_type)

        DecisionClassification.objects.create(
            decision=d_direct, is_direct_assignment=True
        )
        DecisionClassification.objects.create(
            decision=d_indirect, is_direct_assignment=False
        )
        # d_no_class has no classification record

        qs = Decision.objects.all()
        result = apply_decision_facets(qs, direct_assignments_only=True)
        ids = set(result.values_list("id", flat=True))
        # Only the direct-assignment decision is returned
        assert d_direct.id in ids
        assert d_indirect.id not in ids
        assert d_no_class.id not in ids

    def test_direct_assignments_only_off_returns_all(self, decision_type):
        """direct_assignments_only=False returns all decisions regardless."""
        from conftest import DecisionFactory
        from core.models.decision_classification import DecisionClassification

        d_direct = DecisionFactory(ada="DIRECT", decision_type=decision_type)
        d_indirect = DecisionFactory(ada="INDIRECT", decision_type=decision_type)
        d_no_class = DecisionFactory(ada="NOCLASS", decision_type=decision_type)

        DecisionClassification.objects.create(
            decision=d_direct, is_direct_assignment=True
        )
        DecisionClassification.objects.create(
            decision=d_indirect, is_direct_assignment=False
        )

        qs = Decision.objects.all()
        result = apply_decision_facets(qs, direct_assignments_only=False)
        ids = set(result.values_list("id", flat=True))
        assert d_direct.id in ids
        assert d_indirect.id in ids
        assert d_no_class.id in ids
