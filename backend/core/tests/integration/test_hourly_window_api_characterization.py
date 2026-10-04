"""
Hourly window API characterization suite — T00 (HARD GATE for hourly imports).

Empirically proves that advanced-search hour windows are correct (complete,
gapless, sane boundaries) against the known-good simple-search day query — the
exact ``from_date`` path the daily import uses. **No pipeline code may start
before this module is green.**

Recorded day
------------
``D = 2026-09-20`` (Sunday, 301 decisions submitted that day).

The plan's ``find_lowest_volume_date(min_count=100, max_count=1000,
exclude_weekends=True)`` returned ``None`` at selection time (2026-10-06): the
official daily counts had *no weekday* under ~12.8k decisions, so the
100–1000 range contained only weekend days. A normal, stable weekend day was
chosen as the low-volume fallback — the boundary semantics under test are
day-type independent, and 301 decisions keep the committed cassettes small.

``D`` is hard-coded on purpose: VCR matches on ``["uri", "method"]``, so every
query must render byte-identically on replay. Never derive ``D`` at runtime.

Measured on the live API (2026-10-06; replayable from the committed cassettes):

* ``test_day_equals_union_of_hours`` — the ADA set of the simple day query
  (301) is exactly equal to the union of the 24 hour windows (301); 0 missing,
  0 extra ADAs.
* ``test_hour_boundary_inclusivity`` — two decisions sit within ±2s of the
  09:00 boundary (08:59:58.677 and 09:00:00.819); each appears in exactly the
  one adjacent window its timestamp strictly falls into. No decision falls
  exactly *on* an hour boundary on D, so inclusive-vs-exclusive endpoints are
  not directly observable on this day; there is no hole at any boundary.
* ``test_timezone_offset_is_honored`` — Athens-offset day window ``total``
  is 301 vs 300 for the same wall-clock window sent with ``+00:00``.
* ``test_advanced_pagination_walk`` — busiest hour (10:00, total=56) walked
  with ``size=50``: two pages, 50 + 6 = 56 = ``info.total``, no duplicate ADAs,
  ``info.total`` stable across page fetches.
* ``test_status_filter_parity`` — day window without the status clause (302)
  is a superset of the window with ``AND status:"Αναρτημένη"`` (301), and the
  with-status set equals the simple-search set (301): the Greek status literal
  matches the simple search's default ``status=published`` filter. The single
  decision excluded by the status clause on D is ``ΨΓ9ΠΟΛΛΘ-6ΥΔ``
  (status ``REVOKED`` at query time).
* ``test_six_month_issuedate_gap_quantified`` — 0 decisions in the day set
  have ``issueDate`` older than D − 6 months. The API force-appends an
  ``issueDate`` window to *every* search (visible in the ``info.query`` echo
  as ``AND issueDate:[DT(2026-04-09T00:00:00) TO DT(2026-10-06T23:59:59)]``,
  i.e. query-day − 180 days through "today"), which is the mechanism behind
  the known gap: a decision submitted on D but issued >6 months earlier is
  invisible to advanced-search windows. Note the *simple* day search's echo
  shows the same force-appended, execution-anchored ``issueDate`` window, so
  the measured 0 is a lower bound — the clamp is shared by both paths and the
  gap is pre-existing for the daily import as well.

The unexplained ±1 from the original live probes (34,822 advanced day-window
total vs 34,821 simple-day total on a ~35k-decision weekday): it does **not**
reproduce on D — the advanced day-window total equals the simple-day total
exactly (301 = 301). On days with no submission at an exact window endpoint
the two paths agree exactly, which localises the probe-day ±1 to an
endpoint-boundary submission (expected ≈0.4 decisions per exact second on a
35k-decision day) or to a decision added/revoked between the two probe calls.
Either way the 10-minute watermark overlap of the hourly design absorbs it:
consecutive windows overlap, so a decision at an exact boundary is fetched by
at least one window under any inclusivity mode — and this suite proves there
is no hole.

Recording (run once, locally or in the backend container, then commit the
cassettes under ``backend/fixtures/vcr_cassettes/``)::

    pytest core/tests/integration/test_hourly_window_api_characterization.py -v --run-live

Afterwards the module replays fully offline (no ``--run-live`` needed). Any
change to the query rendering, ``D``, page sizes, or request order invalidates
the cassettes — re-recording is a deliberate, reviewed action (delete the
cassette, re-run with ``--run-live``).
"""

from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from dateutil.relativedelta import relativedelta
from django.conf import settings

from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.services.decision_fetch_reconcile_service import (
    DecisionFetchReconcileService,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.live_api,
]

# The recorded day. Frozen on purpose: VCR matches on URI, so every query must
# render byte-identically on replay — never derive D at runtime.
D = date(2026, 9, 20)

ATHENS = ZoneInfo(settings.TIME_ZONE)
CASSETTE_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "vcr_cassettes"

# Inlined from T01's ADVANCED_QUERY_TEMPLATE (byte-significant). Do not
# refactor after recording: any change to query rendering invalidates the
# committed cassettes. build_window_query (T05) must render byte-identically.
ADVANCED_QUERY_TEMPLATE = (
    'submissionTimestamp:[DT({from_ts}) TO DT({to_ts})] AND status:"Αναρτημένη"'
)
STATUS_CLAUSE = ' AND status:"Αναρτημένη"'

ADVANCED_PAGE_SIZE = 500  # same cap as the simple search
PROBE_PAGE_SIZE = 1  # totals-only probes keep cassettes small
WALK_PAGE_SIZE = 50  # forced small page so the pagination walk spans pages
BOUNDARY_EPSILON = timedelta(seconds=2)
SIX_MONTH_GAP_MAX = 5  # sanity bound for the quantified issueDate gap


def _cassette_name(test_name: str) -> str:
    return f"test_hourly_window_characterization_{test_name}.yaml"


def _skip_unless_live_or_recorded(request, cassette_name: str) -> None:
    """Skip when --run-live is absent and the cassette isn't recorded yet."""
    if request.config.getoption("--run-live", default=False):
        return
    if not (CASSETTE_DIR / cassette_name).exists():
        pytest.skip(
            f"Cassette {cassette_name!r} not recorded yet — "
            "run with --run-live to record it."
        )


def _window_dt(day: date, hour: int) -> datetime:
    """Athens-local wall-clock datetime; hour may exceed 23 (24 → next day)."""
    return datetime.combine(day, time(), tzinfo=ATHENS) + timedelta(hours=hour)


def _render_window_query(from_dt: datetime, to_dt: datetime, with_status: bool = True) -> str:
    """Render the advanced-search q for a timestamp window.

    The datetimes are formatted verbatim (their tzinfo carries the offset),
    which lets the timezone test deliberately send a ``+00:00`` window.
    """
    from_ts = from_dt.isoformat(timespec="seconds")
    to_ts = to_dt.isoformat(timespec="seconds")
    query = f"submissionTimestamp:[DT({from_ts}) TO DT({to_ts})]"
    if with_status:
        query += STATUS_CLAUSE
    return query


def _day_query(from_dt: datetime, to_dt: datetime) -> str:
    return _render_window_query(from_dt, to_dt, with_status=True)


def _fetch_day_decisions():
    """Simple search, all pages — the exact ``from_date`` path the daily
    import uses (dates only; never datetimes in ``from_date``/``to_date``)."""
    service = DecisionFetchReconcileService(use_submission_date=True)
    decisions, api_total = service.fetch_decisions_for_day(
        D, include_feature_flags=False
    )
    return decisions, api_total


def _fetch_day_adas():
    decisions, _ = _fetch_day_decisions()
    return decisions, {d.ada for d in decisions}


def _advanced_client():
    return DiavgeiaFetcher()._get_client()


def _fetch_advanced_all_pages(query: str, size: int = ADVANCED_PAGE_SIZE):
    """Walk every page of an advanced-search query.

    Returns ``(decisions, api_total)``. Pagination mirrors
    ``fetch_decisions_for_day``: stop on a short page or once the first page's
    ``info.total`` is reached.
    """
    client = _advanced_client()
    decisions = []
    page = 0
    api_total = None
    while True:
        response = client.search_advanced(q=query, page=page, size=size)
        info = response.info
        if api_total is None:
            api_total = info.total
        decisions.extend(response.decisions)
        if info.actualSize < size or len(decisions) >= api_total:
            return decisions, api_total
        page += 1


def _fetch_advanced_total(query: str) -> tuple[int, str]:
    """First page only: ``(info.total, info.query echo)`` — the total is the
    query's total regardless of the requested page size."""
    response = _advanced_client().search_advanced(
        q=query, page=0, size=PROBE_PAGE_SIZE
    )
    return response.info.total, response.info.query


def _fetch_hour_window(hour: int):
    """One hour window of D, all pages: [D hh:00 Athens, D hh+1:00 Athens)."""
    start = _window_dt(D, hour)
    return _fetch_advanced_all_pages(_render_window_query(start, start + timedelta(hours=1)))


def test_day_equals_union_of_hours(vcr_config, request):
    """The fundamental gate: simple-day ADA set == union of 24 hour windows."""
    name = _cassette_name("day_equals_union_of_hours")
    _skip_unless_live_or_recorded(request, name)
    with vcr_config.use_cassette(name):
        day_decisions, day_adas = _fetch_day_adas()

        union_adas = set()
        ts_by_ada = {d.ada: d.submissionTimestamp for d in day_decisions}
        per_hour_totals = {}
        for hour in range(24):
            decisions, api_total = _fetch_hour_window(hour)
            per_hour_totals[hour] = api_total
            for d in decisions:
                union_adas.add(d.ada)
                ts_by_ada.setdefault(d.ada, d.submissionTimestamp)

        missing = day_adas - union_adas
        extra = union_adas - day_adas

        detail = [
            f"day={len(day_adas)} unique ADAs, union={len(union_adas)} unique ADAs",
        ]
        if missing or extra:
            detail.append("missing (in day, not in any hour window):")
            detail += [
                f"  {ada} submissionTimestamp={ts_by_ada.get(ada)}"
                for ada in sorted(missing)
            ]
            detail.append("extra (in an hour window, not in the day):")
            detail += [
                f"  {ada} submissionTimestamp={ts_by_ada.get(ada)}"
                for ada in sorted(extra)
            ]
        assert not missing and not extra, (
            "Day != union of hour windows:\n" + "\n".join(detail)
        )
        print(f"\nday == union of hours: {len(day_adas)} == {len(union_adas)} ADAs")
        print(f"per-hour totals: {per_hour_totals}")


def test_hour_boundary_inclusivity(vcr_config, request):
    """Decisions within ±2s of an hour boundary must appear in at least one
    adjacent window. Absence from both is a blocker (redesign the window
    math). The inclusivity mode (both / left-only / right-only) is recorded,
    not failed on — the 10-min overlap makes any mode safe.
    """
    name = _cassette_name("hour_boundary_inclusivity")
    _skip_unless_live_or_recorded(request, name)
    with vcr_config.use_cassette(name):
        day_decisions, _ = _fetch_day_decisions()
        decisions, _ = zip(*(_fetch_hour_window(hour) for hour in range(24)))
        hour_sets = [{d.ada for d in page} for page in decisions]
        # Shoulder windows give the day-edge boundaries (00:00 and 24:00) both
        # of their adjacent windows, so "absence from both" is checkable there too.
        left_shoulder = _fetch_advanced_all_pages(
            _render_window_query(
                _window_dt(D, 0) - timedelta(hours=1), _window_dt(D, 0)
            )
        )[0]
        right_shoulder = _fetch_advanced_all_pages(
            _render_window_query(
                _window_dt(D, 24), _window_dt(D, 24) + timedelta(hours=1)
            )
        )[0]
        shoulder_sets = (
            {d.ada for d in left_shoulder},
            {d.ada for d in right_shoulder},
        )

        boundaries = [(_window_dt(D, hour), hour) for hour in range(25)]

        seen = {}
        sources = list(day_decisions) + [d for page in decisions for d in page]
        sources += left_shoulder + right_shoulder
        for d in sources:
            ts = d.submissionTimestamp
            for boundary, hour in boundaries:
                delta = abs((ts - boundary).total_seconds())
                if delta <= BOUNDARY_EPSILON.total_seconds():
                    seen[(d.ada, hour)] = (ts, delta)
                    break

        failures = []
        records = []
        for (ada, hour), (ts, delta) in sorted(
            seen.items(), key=lambda item: (item[0][1], item[1][0])
        ):
            if hour == 0:
                left, right = shoulder_sets[0], hour_sets[0]
            elif hour == 24:
                left, right = hour_sets[23], shoulder_sets[1]
            else:
                left, right = hour_sets[hour - 1], hour_sets[hour]
            in_left, in_right = ada in left, ada in right
            if not in_left and not in_right:
                failures.append(
                    f"{ada} submissionTimestamp={ts.isoformat()} is within ±2s "
                    f"of boundary {hour:02d}:00 but appears in NEITHER adjacent "
                    "window (blocker — window math must be redesigned)"
                )
            where = (
                "both (inclusive-inclusive)"
                if in_left and in_right
                else "left-only"
                if in_left
                else "right-only"
            )
            exactness = "exact boundary" if delta == 0 else f"near boundary ({delta:.3f}s)"
            records.append(
                f"{ada} ts={ts.isoformat()} boundary={hour:02d}:00 "
                f"{where} [{exactness}]"
            )

        assert not failures, "Boundary decisions missing from all adjacent windows:\n" + "\n".join(
            failures
        )
        print(f"\nboundary-near decisions (±{BOUNDARY_EPSILON.total_seconds():.0f}s): {len(seen)}")
        for record in records:
            print(f"  {record}")
        if not any(delta == 0 for _, delta in seen.values()):
            print(
                "  no decision sits exactly on an hour boundary on D — "
                "endpoint inclusivity mode not directly observable on this day"
            )


def test_timezone_offset_is_honored(vcr_config, request):
    """Same wall-clock window, correct Athens offset vs +00:00, must return
    different totals — proves the offset is parsed, not ignored."""
    name = _cassette_name("timezone_offset_is_honored")
    _skip_unless_live_or_recorded(request, name)
    with vcr_config.use_cassette(name):
        athens_total, _ = _fetch_advanced_total(
            _day_query(_window_dt(D, 0), _window_dt(D, 24))
        )
        utc_from = datetime.combine(D, time(), tzinfo=ZoneInfo("UTC"))
        utc_total, _ = _fetch_advanced_total(
            _render_window_query(utc_from, utc_from + timedelta(days=1))
        )
        assert athens_total > 0
        assert athens_total != utc_total, (
            f"Athens-offset window total ({athens_total}) equals the +00:00 "
            f"window total ({utc_total}) — the API may be ignoring the offset"
        )
        print(f"\nAthens day window total={athens_total}, +00:00 total={utc_total}")


def test_advanced_pagination_walk(vcr_config, request):
    """Highest-volume hour walked with size=50: pages sum to info.total,
    no duplicate ADAs across pages, info.total stable across fetches."""
    name = _cassette_name("advanced_pagination_walk")
    _skip_unless_live_or_recorded(request, name)
    with vcr_config.use_cassette(name):
        hour_totals = {
            hour: _fetch_advanced_total(
                _render_window_query(
                    _window_dt(D, hour), _window_dt(D, hour) + timedelta(hours=1)
                )
            )[0]
            for hour in range(24)
        }
        busiest_hour = max(hour_totals, key=hour_totals.get)
        busiest_start = _window_dt(D, busiest_hour)
        query = _render_window_query(
            busiest_start, busiest_start + timedelta(hours=1)
        )

        pages = []
        page = 0
        fetched = 0
        while True:
            response = _advanced_client().search_advanced(
                q=query, page=page, size=WALK_PAGE_SIZE
            )
            pages.append(response)
            fetched += len(response.decisions)
            if (
                response.info.actualSize < WALK_PAGE_SIZE
                or fetched >= response.info.total
            ):
                break
            page += 1

        total = pages[0].info.total
        all_adas = [d.ada for p in pages for d in p.decisions]
        totals_across_pages = {p.info.total for p in pages}

        assert sum(len(p.decisions) for p in pages) == total, (
            f"Walked {sum(len(p.decisions) for p in pages)} items across "
            f"{len(pages)} pages but info.total={total} "
            f"(hour {busiest_hour:02d}:00, size={WALK_PAGE_SIZE})"
        )
        assert len(all_adas) == len(set(all_adas)), (
            "Duplicate ADAs across pagination pages"
        )
        assert len(totals_across_pages) == 1, (
            f"info.total not stable across page fetches: {sorted(totals_across_pages)}"
        )
        print(
            f"\nbusiest hour {busiest_hour:02d}:00 (total={total}) walked with "
            f"size={WALK_PAGE_SIZE}: {len(pages)} pages, "
            f"{[len(p.decisions) for p in pages]} items per page, stable total"
        )


def test_status_filter_parity(vcr_config, request):
    """Without-status day window ⊇ with-status window, and the with-status
    set equals the simple-search set (simple search defaults to published)."""
    name = _cassette_name("status_filter_parity")
    _skip_unless_live_or_recorded(request, name)
    with vcr_config.use_cassette(name):
        with_status, _ = _fetch_advanced_all_pages(
            _day_query(_window_dt(D, 0), _window_dt(D, 24))
        )
        without_status, _ = _fetch_advanced_all_pages(
            _render_window_query(
                _window_dt(D, 0), _window_dt(D, 24), with_status=False
            )
        )
        _, day_adas = _fetch_day_adas()

        with_set = {d.ada for d in with_status}
        without_set = {d.ada for d in without_status}

        assert without_set >= with_set, (
            "Day window without the status clause is NOT a superset of the "
            f"window with it: {sorted(with_set - without_set)}"
        )
        assert with_set == day_adas, (
            "With-status advanced set != simple-search set:\n"
            f"  missing (simple only): {sorted(day_adas - with_set)}\n"
            f"  extra (advanced only): {sorted(with_set - day_adas)}"
        )
        status_by_ada = {d.ada: d.status for d in without_status}
        non_published = sorted(without_set - with_set)
        print(f"\nwithout-status={len(without_set)} ⊇ with-status={len(with_set)} == simple day={len(day_adas)}")
        for ada in non_published:
            print(f"  excluded by status clause: {ada} status={status_by_ada[ada]}")


def test_six_month_issuedate_gap_quantified(vcr_config, request):
    """Quantify the known API gap: decisions in the day set whose issueDate is
    older than D − 6 months (the API force-appends a ~6-month issueDate
    window to advanced queries, making such decisions invisible to hourly
    imports). Expected ≈ 0; the measured number is recorded in the module
    docstring."""
    name = _cassette_name("six_month_issuedate_gap_quantified")
    _skip_unless_live_or_recorded(request, name)
    with vcr_config.use_cassette(name):
        day_decisions, day_total = _fetch_day_decisions()
        cutoff = datetime.combine(
            D - relativedelta(months=6), time(), tzinfo=ATHENS
        )
        gap = [d for d in day_decisions if d.issueDate < cutoff]

        assert len(gap) <= SIX_MONTH_GAP_MAX, (
            f"{len(gap)} decisions submitted on {D} have issueDate < "
            f"{cutoff.date()} (expected ≈ 0): "
            + ", ".join(f"{d.ada} issueDate={d.issueDate.date().isoformat()}" for d in gap)
        )

        window_total, echoed_query = _fetch_advanced_total(
            _day_query(_window_dt(D, 0), _window_dt(D, 24))
        )
        assert "issueDate:[DT(" in echoed_query, (
            "API no longer force-appends an issueDate window to advanced "
            f"queries — echo was: {echoed_query!r}"
        )
        assert window_total == day_total, (
            f"Advanced day-window total ({window_total}) != simple-day total "
            f"({day_total}) on D — the probe-day ±1 reproduced"
        )

        print(f"\nsix-month issueDate gap on {D}: {len(gap)} decisions (day set={len(day_decisions)})")
        print(f"force-appended issueDate window visible in echo: {echoed_query!r}")
        print(f"advanced day-window total={window_total} == simple-day total={day_total}")
