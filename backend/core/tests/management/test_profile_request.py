import json
from urllib.parse import parse_qs, urlparse

import pytest
from core.services.request_profiler import (
    default_host,
    expand_profile_targets,
    normalize_sql,
    parse_header,
    parse_profile_input,
    shorten,
)

pytestmark = pytest.mark.fast


def test_normalize_sql_replaces_literals_numbers_and_in_lists():
    sql = (
        "SELECT * FROM core_decision "
        "WHERE organization_id = 100054489 "
        "AND ada = 'ABC' AND id IN (1, 2, 3) LIMIT 20"
    )

    assert normalize_sql(sql) == (
        "SELECT * FROM core_decision "
        "WHERE organization_id = ? "
        "AND ada = ? AND id IN (?) LIMIT ?"
    )


def test_normalize_sql_handles_placeholders_and_whitespace():
    sql = "SELECT  *\n  FROM core_decision\n WHERE id = %s\n"

    assert normalize_sql(sql) == "SELECT * FROM core_decision WHERE id = ?"


def test_parse_header_converts_dashes_to_wsgi_keys():
    assert parse_header("X-Trace-Id: abc") == ("HTTP_X_TRACE_ID", "abc")
    assert parse_header("Content-Type: application/json") == (
        "CONTENT_TYPE",
        "application/json",
    )


def test_parse_header_rejects_missing_separator():
    with pytest.raises(ValueError):
        parse_header("X-Trace-Id")


def test_default_host_skips_wildcards_and_leading_dots(settings):
    settings.ALLOWED_HOSTS = ["*", ".crati.co", "crati.co"]

    assert default_host() == "crati.co"


def test_shorten_collapses_whitespace_and_truncates():
    assert shorten("SELECT  *\nFROM t") == "SELECT * FROM t"
    assert shorten("x" * 10, limit=5) == "xxxx…"


def test_expand_api_path_is_preserved():
    path = "/api/decisions/unified/?source=entity&view=date_range"

    assert expand_profile_targets(path) == [path]


def test_expand_org_page_into_frontend_requests():
    targets = expand_profile_targets(
        "/entity/organization/100054489"
        "?start_date=2025-11-01&end_date=2026-10-31"
        "&sort=recent&direct_assignments_only=true&search=foo&types=1,2"
    )

    assert len(targets) == 4
    assert all(target.startswith("/api/") for target in targets)

    date_range = parse_qs(urlparse(targets[0]).query)
    assert date_range["view"] == ["date_range"]
    assert date_range["entity_id"] == ["100054489"]

    decision_types = parse_qs(urlparse(targets[1]).query)
    assert decision_types["view"] == ["decision_types"]
    assert decision_types["start_date"] == ["2025-11-01"]
    assert decision_types["end_date"] == ["2026-10-31"]

    decisions = parse_qs(urlparse(targets[2]).query)
    assert decisions["view"] == ["decisions"]
    assert decisions["sort_by"] == ["recent"]
    assert decisions["direct_assignments_only"] == ["true"]
    assert decisions["q"] == ["foo"]
    assert decisions["decision_types"] == ["1,2"]

    assert targets[3].startswith("/api/organizations/100054489/top-counterparts/?")
    counterparts = parse_qs(urlparse(targets[3]).query)
    assert counterparts["limit"] == ["5"]
    assert counterparts["offset"] == ["0"]


def test_expand_full_url_uses_path_and_query():
    targets = expand_profile_targets(
        "https://crati.co/entity/organization/123"
        "?start_date=2025-01-01&end_date=2025-12-31"
    )

    assert len(targets) == 4
    assert all(target.startswith("/api/") for target in targets)
    decisions = parse_qs(urlparse(targets[2]).query)
    assert decisions["entity_id"] == ["123"]
    assert decisions["start_date"] == ["2025-01-01"]
    assert decisions["end_date"] == ["2025-12-31"]


def test_expand_org_page_without_dates_uses_a_default_window():
    targets = expand_profile_targets("/entity/organization/123")

    decisions = parse_qs(urlparse(targets[2]).query)
    assert decisions["start_date"]
    assert decisions["end_date"]
    assert decisions["start_date"] < decisions["end_date"]


def test_expand_temporal_range_page():
    targets = expand_profile_targets(
        "/explore/temporal/2026-10-24/2026-11-24?sort=amount_desc"
    )

    assert len(targets) == 3
    decision_types = parse_qs(urlparse(targets[0]).query)
    assert decision_types["source"] == ["temporal"]
    assert decision_types["view"] == ["decision_types"]
    assert decision_types["start_date"] == ["2026-10-24"]
    assert decision_types["end_date"] == ["2026-11-24"]

    decisions = parse_qs(urlparse(targets[1]).query)
    assert decisions["source"] == ["temporal"]
    assert decisions["view"] == ["decisions"]
    assert decisions["sort_by"] == ["amount_desc"]

    assert targets[2].startswith("/api/direct-assignments/top-pairs/?")
    pairs = parse_qs(urlparse(targets[2]).query)
    assert pairs["start_date"] == ["2026-10-24"]
    assert pairs["limit"] == ["10"]


def test_expand_temporal_single_day_page():
    targets = expand_profile_targets("/explore/temporal/2026-11-24")

    decisions = parse_qs(urlparse(targets[1]).query)
    assert decisions["start_date"] == ["2026-11-24"]
    assert decisions["end_date"] == ["2026-11-24"]


def test_expand_month_page():
    targets = expand_profile_targets("/explore/month/2026/2")

    decisions = parse_qs(urlparse(targets[1]).query)
    assert decisions["start_date"] == ["2026-02-01"]
    assert decisions["end_date"] == ["2026-02-28"]


def test_expand_week_page_matches_frontend_js_sunday_start():
    targets = expand_profile_targets("/explore/week/2026/1")

    decisions = parse_qs(urlparse(targets[1]).query)
    assert decisions["start_date"] == ["2025-12-28"]
    assert decisions["end_date"] == ["2026-01-03"]


def test_expand_rejects_unsupported_page_routes():
    with pytest.raises(ValueError):
        expand_profile_targets("/explore/unknown/2025-01-01")


def test_parse_har_keeps_get_api_requests_and_drops_assets_and_posts():
    har = json.dumps(
        {
            "log": {
                "entries": [
                    {
                        "request": {
                            "method": "GET",
                            "url": "https://crati.co/api/decisions/unified/"
                            "?source=entity&view=date_range",
                        }
                    },
                    {
                        "request": {
                            "method": "GET",
                            "url": "https://crati.co/api/organizations/1/"
                            "top-counterparts/?start_date=2025-01-01"
                            "&end_date=2025-12-31",
                        }
                    },
                    {
                        "request": {
                            "method": "POST",
                            "url": "https://crati.co/api/foo/",
                        }
                    },
                    {
                        "request": {
                            "method": "GET",
                            "url": "https://crati.co/static/app.js",
                        }
                    },
                ]
            }
        }
    )

    paths = parse_profile_input(har)

    assert len(paths) == 2
    assert paths[0].startswith("/api/decisions/unified/?")
    assert paths[1].startswith("/api/organizations/1/top-counterparts/?")


def test_parse_curl_keeps_get_api_requests():
    raw = (
        "curl 'https://crati.co/api/decisions/unified/"
        "?source=entity&view=date_range' \\\n"
        "  -H 'accept: application/json' \\\n"
        "  --compressed\n"
        "curl 'https://crati.co/api/organizations/1/top-counterparts/"
        "?start_date=2025-01-01&end_date=2025-12-31' \\\n"
        "  -H 'accept: application/json'"
    )

    paths = parse_profile_input(raw)

    assert len(paths) == 2
    assert paths[0].startswith("/api/decisions/unified/?")
    assert paths[1].startswith("/api/organizations/1/top-counterparts/?")


def test_parse_curl_skips_non_get_requests():
    raw = "curl -X POST 'https://crati.co/api/foo/' -H 'content-type: application/json'"

    assert parse_profile_input(raw) == []


def test_parse_curl_mixed_methods_keeps_only_gets():
    raw = (
        "curl 'https://crati.co/api/one/?x=1'\n"
        "curl -X POST 'https://crati.co/api/two/'\n"
        "curl 'https://crati.co/api/three/?y=2'"
    )

    paths = parse_profile_input(raw)

    assert paths == ["/api/one/?x=1", "/api/three/?y=2"]


def test_parse_profile_input_dedupes_and_expands_page_urls():
    raw = (
        "/explore/temporal/2026-10-24/2026-11-24?sort=amount_desc\n"
        "/explore/temporal/2026-10-24/2026-11-24?sort=amount_desc"
    )

    assert len(parse_profile_input(raw)) == 3


def test_parse_invalid_har_raises():
    with pytest.raises(ValueError):
        parse_profile_input('{"not": "a har"}')


def test_parse_sql_log_line_explains_it_is_not_a_har():
    line = (
        '{"message": "(0.002) SELECT 1", "sql": "SELECT 1", '
        '"logger": "django.db.backends"}'
    )

    with pytest.raises(ValueError, match="SQL log"):
        parse_profile_input(line)
