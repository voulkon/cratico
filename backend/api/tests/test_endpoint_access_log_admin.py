"""
Tests for the EndpointAccessLog admin visitor views (admin_custom/admin_classes/analytics.py).

Covers:
  - Visitors list: unique IP / request totals respect the date range
  - Visitors list: sorting whitelist and default ordering
  - Visitors list: query count does not grow with the number of visitors
  - IP drill-down: sessions split on the inactivity gap
  - IP drill-down: invalid IP is rejected
"""

from datetime import datetime, time, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from api.models import EndpointAccessLog


def _log(ip, when, endpoint="/api/decisions/", status=200):
    entry = EndpointAccessLog.objects.create(
        ip_address=ip,
        endpoint=endpoint,
        method="GET",
        status_code=status,
    )
    EndpointAccessLog.objects.filter(pk=entry.pk).update(timestamp=when)
    return entry


def _at(day_offset=0, hour=12, minute=0):
    day = timezone.localdate() - timedelta(days=day_offset)
    return timezone.make_aware(
        datetime.combine(day, time(hour, minute)),
        timezone.get_current_timezone(),
    )


def _summary_url():
    return reverse("admin:endpointaccesslog_ip_summary")


def _detail_url():
    return reverse("admin:endpointaccesslog_ip_detail")


@pytest.mark.django_db
class TestVisitorsSummary:
    def test_totals_respect_date_range(self, admin_client):
        _log("203.0.113.1", _at(0))
        _log("203.0.113.1", _at(0, hour=13))
        _log("203.0.113.2", _at(0))
        _log("203.0.113.3", _at(10))

        today = timezone.localdate().isoformat()
        resp = admin_client.get(_summary_url(), {"start": today, "end": today})

        assert resp.status_code == 200
        assert resp.context["totals"]["unique_ips"] == 2
        assert resp.context["totals"]["requests"] == 3

    def test_empty_start_and_end_means_all_time(self, admin_client):
        _log("203.0.113.1", _at(0))
        _log("203.0.113.3", _at(40))

        resp = admin_client.get(_summary_url(), {"start": "", "end": ""})

        assert resp.context["totals"]["unique_ips"] == 2

    def test_sort_by_requests_ascending(self, admin_client):
        for _ in range(3):
            _log("203.0.113.1", _at(0))
        _log("203.0.113.2", _at(0))

        resp = admin_client.get(_summary_url(), {"sort": "requests", "dir": "asc"})

        ips = [row["ip_address"] for row in resp.context["visitors"]]
        assert ips == ["203.0.113.2", "203.0.113.1"]

    def test_unknown_sort_falls_back_to_last_seen(self, admin_client):
        _log("203.0.113.1", _at(0, hour=9))
        _log("203.0.113.2", _at(0, hour=10))

        resp = admin_client.get(_summary_url(), {"sort": "drop table"})

        assert resp.status_code == 200
        assert resp.context["sort"] == "last_seen"
        ips = [row["ip_address"] for row in resp.context["visitors"]]
        assert ips == ["203.0.113.2", "203.0.113.1"]

    def test_query_count_does_not_grow_with_visitors(self, admin_client):
        for i in range(2):
            _log(f"198.51.100.{i}", _at(0))
        admin_client.get(_summary_url())

        with CaptureQueriesContext(connection) as few:
            admin_client.get(_summary_url())

        for i in range(2, 40):
            _log(f"198.51.100.{i}", _at(0))

        with CaptureQueriesContext(connection) as many:
            resp = admin_client.get(_summary_url())

        assert len(resp.context["visitors"]) == 40
        assert len(many.captured_queries) == len(few.captured_queries)


@pytest.mark.django_db
class TestVisitorDetail:
    def test_sessions_split_after_inactivity_gap(self, admin_client):
        ip = "203.0.113.7"
        _log(ip, _at(0, hour=12, minute=0))
        _log(ip, _at(0, hour=12, minute=5))
        _log(ip, _at(0, hour=13, minute=0))

        today = timezone.localdate().isoformat()
        resp = admin_client.get(_detail_url(), {"ip": ip, "start": today, "end": today})

        assert resp.status_code == 200
        sessions = resp.context["sessions"]
        assert [s["requests"] for s in sessions] == [2, 1]

    def test_per_day_breakdown(self, admin_client):
        ip = "203.0.113.8"
        _log(ip, _at(1))
        _log(ip, _at(0))
        _log(ip, _at(0, hour=18))

        resp = admin_client.get(_detail_url(), {"ip": ip, "start": "", "end": ""})

        assert [d["requests"] for d in resp.context["daily"]] == [1, 2]

    def test_invalid_ip_is_not_found(self, admin_client):
        resp = admin_client.get(_detail_url(), {"ip": "not-an-ip"})

        assert resp.status_code == 404


@pytest.mark.django_db
class TestChangelistLinks:
    def test_day_link_opens_filtered_changelist(self, admin_client):
        ip = "203.0.113.9"
        _log(ip, _at(1))
        _log(ip, _at(0))
        _log(ip, _at(0, hour=18))

        detail = admin_client.get(_detail_url(), {"ip": ip, "start": "", "end": ""})
        today_link = detail.context["daily"][-1]["requests_url"]

        resp = admin_client.get(today_link)

        assert resp.status_code == 200
        assert resp.context["cl"].result_count == 2


@pytest.mark.django_db
class TestDefaultDay:
    def test_defaults_to_latest_logged_day(self, admin_client):
        _log("203.0.113.1", _at(3))

        resp = admin_client.get(_summary_url())

        expected = (timezone.localdate() - timedelta(days=3)).isoformat()
        assert resp.context["range_query"] == {"start": expected, "end": expected}
        assert resp.context["totals"]["unique_ips"] == 1

    def test_defaults_to_today_when_table_is_empty(self, admin_client):
        resp = admin_client.get(_summary_url())

        today = timezone.localdate().isoformat()
        assert resp.context["range_query"] == {"start": today, "end": today}
