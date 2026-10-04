"""
Live window smoke test — T12 (cheap tripwire for the real fetch path).

A time-relative sanity check of the real advanced-search window fetch against
the real Diavgeia API. Unlike T00's characterization suite this module uses **no
VCR**: the windows are computed from ``timezone.now()`` / fixed past dates, so
cassettes would pin "now"-relative URIs and replay stale windows. Every test is
skipped unless ``--run-live`` is passed, so CI stays offline-safe.

This is *not* the gate (T00 is). It is a cheap regression tripwire for query
rendering (T05 ``build_window_query``) and fetcher plumbing (T04
``fetch_decisions_advanced``).

Usage::

    pytest core/tests/integration/test_hourly_window_live_smoke.py -v --run-live
    # without --run-live: all three skip (CI-safe)

Recorded API contract (observed live on 2026-10-06, ~16:45 Europe/Athens)
-----------------------------------------------------------------------
* ``info.query`` **echo** — the API echoes the submitted submissionTimestamp
  window byte-identically, including the ``+03:00`` (EEST) offset, then
  force-appends an ``issueDate`` window anchored to the execution day::

      submissionTimestamp:[DT(2026-10-06T16:30:42+03:00) TO DT(2026-10-06T16:45:42+03:00)] \
      AND status:"Αναρτημένη" \
      AND issueDate:[DT(2026-04-09T00:00:00) TO DT(2026-10-06T23:59:59)]

  The echoed submissionTimestamp clause matching the sent ``q`` is the proof the
  API parsed the window rather than silently ignoring the ``DT()`` literals.

* ``info.size`` — ``size=500`` is honored: the request asked for 500 and the
  response reported ``info.size == 500`` (confirms the page-size cap assumption
  the plan flagged to "verify ``info.size`` on first live run").

* Sanity totals — a 15-minute recent window returned a small total (72 on the
  probe run); the fixed past Sunday window returned ``total == 0`` with no
  exception. A 6-month-sized total would mean the ``DT()`` literals were
  ignored, and is failed loudly by ``test_recent_window_fetch_sane``.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.utils import timezone

from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.services.decision_fetch_reconcile_service import (
    DecisionFetchReconcileService,
)


pytestmark = [
    pytest.mark.integration,
    pytest.mark.live_api,
    pytest.mark.skipif(
        "not config.getoption('--run-live', default=False)",
        reason="Skipping live API test. Use --run-live to enable.",
    ),
]

# A 15-minute window is a few hundred decisions at the weekday peak. If the
# ``DT()`` literals were ignored the API would return a day-sized (~35k) or
# 6-month-sized (millions) total; anything above this bound fails loudly.
MAX_SANE_WINDOW_TOTAL = 5000

# Past Sunday 04:00–04:15 Athens: a first-class zero hour, no submissions.
ZERO_WINDOW_START = datetime(2026, 9, 20, 4, 0, tzinfo=ZoneInfo(settings.TIME_ZONE))
ZERO_WINDOW_END = ZERO_WINDOW_START + timedelta(minutes=15)


def test_recent_window_fetch_sane():
    """A recent 15-minute window returns a small, pagination-consistent count."""
    service = DecisionFetchReconcileService()
    now = timezone.now()

    decisions, api_total, types_filtered = service.fetch_decisions_for_window(
        now - timedelta(minutes=15), now
    )

    assert isinstance(decisions, list)
    assert isinstance(api_total, int)
    assert isinstance(types_filtered, bool)
    assert api_total >= 0

    # A 15-minute window must be small. A 6-month-sized total means the DT
    # literals were ignored — fail loudly rather than pass a hollow assertion.
    assert api_total <= MAX_SANE_WINDOW_TOTAL, (
        f"15-minute window reported api_total={api_total} "
        f"(> {MAX_SANE_WINDOW_TOTAL}) — the submissionTimestamp DT() literals "
        "were likely ignored and the API returned an unfiltered window"
    )

    # Pagination consistency: client-side filtering may only shrink the count.
    if types_filtered:
        assert 0 <= len(decisions) <= api_total
    else:
        assert 0 <= len(decisions) == api_total


def test_advanced_query_echo_and_size_cap():
    """The API echoes the submitted window and honors the size=500 cap."""
    service = DecisionFetchReconcileService()
    now = timezone.now()
    q = service.build_window_query(now - timedelta(minutes=15), now)

    raw = DiavgeiaFetcher().fetch_decisions_advanced(q=q, size=500)

    assert raw is not None, "Advanced fetch returned None against the live API"
    assert raw.info.size == 500, (
        f"Requested size=500 but API reported info.size={raw.info.size}"
    )

    # The sent window (submissionTimestamp clause) must appear in the echo;
    # its presence proves the API parsed the window rather than ignoring it.
    submitted_range = q.split(" AND status", 1)[0]
    assert "submissionTimestamp:[DT(" in raw.info.query
    assert submitted_range in raw.info.query, (
        f"API echo did not contain the submitted window.\n"
        f"  sent: {submitted_range!r}\n"
        f"  echo: {raw.info.query!r}"
    )


def test_zero_decision_window_completes():
    """A fixed quiet past window completes cleanly as a first-class zero hour."""
    service = DecisionFetchReconcileService()

    decisions, api_total, types_filtered = service.fetch_decisions_for_window(
        ZERO_WINDOW_START, ZERO_WINDOW_END
    )

    assert decisions == []
    assert api_total == 0
    assert isinstance(types_filtered, bool)
