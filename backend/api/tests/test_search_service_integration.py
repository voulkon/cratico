"""
Integration tests for SearchService against a real PostgreSQL database.

Test cases are entirely data-driven: each JSON file under
``api/tests/data/search_service/`` defines one scenario.

JSON schema
-----------
{
  "id":              str   — unique pytest node id
  "description":    str   — optional human-readable note
  "tier":           "simple" | "fts"
  "entity_type":    "organization" | "signer" | "unit" | "company" | "company_person"
  "records":        list  — factory kwargs for the *primary* context
  "other_records":  list  — optional; factory kwargs for a *secondary* org/company
                            used to verify filter isolation
  "query":          str   — search string
  "limit":          int   — default 10
  "filter_by_primary": bool — if true, pass the primary org/company id as filter
  "expected_in":    list[str] — result labels that MUST appear
  "expected_not_in":list[str] — result labels that must NOT appear
  "expected_exact_count": int — optional exact result-count assertion
}

Result label convention
-----------------------
  organization / unit  →  obj.label
  signer               →  "{first_name} {last_name}"
  company              →  obj.co_name_el
  company_person       →  obj.person_name

FTS tests are automatically marked ``requires_postgresql`` (driven by ``"tier": "fts"``
in the JSON).  Simple-tier tests run on any DB backend.

Run all tests:
    pytest api/tests/test_search_service_integration.py

Run only FTS tests (requires PostgreSQL):
    PG_TEST=1 pytest api/tests/test_search_service_integration.py -m requires_postgresql

Adding new scenarios
--------------------
Drop a new .json file into the appropriate sub-directory — no Python changes needed.
"""

import json
import pytest
from pathlib import Path

from core.services.search_service import SearchService

# ---------------------------------------------------------------------------
# Data directory
# ---------------------------------------------------------------------------

TEST_DATA_DIR = Path(__file__).parent / "data" / "search_service"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_label(entity_type: str, obj) -> str:
    if entity_type in ("organization", "unit"):
        return obj.label
    if entity_type == "signer":
        return f"{obj.first_name} {obj.last_name}"
    if entity_type == "company":
        return obj.co_name_el
    if entity_type == "company_person":
        return obj.person_name
    raise ValueError(f"Unknown entity_type: {entity_type!r}")


def _create_entities(entity_type: str, records_data: list, org=None, company=None):
    from conftest import (
        CompanyFactory,
        CompanyPersonFactory,
        OrganizationFactory,
        SignerFactory,
        UnitFactory,
    )

    created = []
    for data in records_data:
        if entity_type == "organization":
            obj = OrganizationFactory(**data)
        elif entity_type == "signer":
            obj = SignerFactory(organization=org, **data)
        elif entity_type == "unit":
            obj = UnitFactory(organization=org, **data)
        elif entity_type == "company":
            obj = CompanyFactory(**data)
        elif entity_type == "company_person":
            obj = CompanyPersonFactory(company=company, **data)
        else:
            raise ValueError(f"Unknown entity_type: {entity_type!r}")
        created.append(obj)
    return created


def _call_search(service: SearchService, entity_type: str, tier: str,
                 query: str, limit: int, filter_id=None):
    if entity_type == "organization":
        fn = (service._search_organizations_simple if tier == "simple"
              else service._search_organizations_fts)
        return fn(query, limit=limit)

    if entity_type == "signer":
        fn = (service._search_signers_simple if tier == "simple"
              else service._search_signers_fts)
        return fn(query, organization_id=filter_id, limit=limit)

    if entity_type == "unit":
        fn = (service._search_units_simple if tier == "simple"
              else service._search_units_fts)
        return fn(query, organization_id=filter_id, limit=limit)

    if entity_type == "company":
        fn = (service._search_companies_simple if tier == "simple"
              else service._search_companies_fts)
        return fn(query, limit=limit)

    if entity_type == "company_person":
        fn = (service._search_company_persons_simple if tier == "simple"
              else service._search_company_persons_fts)
        return fn(query, company_id=filter_id, limit=limit)

    raise ValueError(f"Unknown entity_type: {entity_type!r}")


def _run_search_case(case: dict) -> None:
    """Execute a single data-driven search scenario end-to-end."""
    from conftest import CompanyFactory, OrganizationFactory

    entity_type = case["entity_type"]
    tier = case["tier"]
    query = case["query"]
    limit = case.get("limit", 10)

    # Shared parent context for entities that belong to an org / company
    primary_org = OrganizationFactory() if entity_type in ("signer", "unit") else None
    primary_company = CompanyFactory() if entity_type == "company_person" else None

    _create_entities(entity_type, case.get("records", []),
                     org=primary_org, company=primary_company)

    # Records in a *different* org/company, used to verify filter isolation
    if case.get("other_records"):
        other_org = OrganizationFactory() if entity_type in ("signer", "unit") else None
        other_company = CompanyFactory() if entity_type == "company_person" else None
        _create_entities(entity_type, case["other_records"],
                         org=other_org, company=other_company)

    # Resolve filter id when the test wants filtering by the primary context
    filter_id = None
    if case.get("filter_by_primary"):
        if entity_type in ("signer", "unit"):
            filter_id = primary_org.uid
        elif entity_type == "company_person":
            filter_id = primary_company.id

    results = list(_call_search(SearchService(), entity_type, tier, query, limit, filter_id))
    labels = [_get_label(entity_type, obj) for obj in results]

    for label in case.get("expected_in", []):
        assert label in labels, f"Expected {label!r} in results: {labels}"

    for label in case.get("expected_not_in", []):
        assert label not in labels, f"Expected {label!r} NOT in results: {labels}"

    if "expected_exact_count" in case:
        assert len(results) == case["expected_exact_count"], (
            f"Expected exactly {case['expected_exact_count']} results, "
            f"got {len(results)}: {labels}"
        )


# ---------------------------------------------------------------------------
# Case loader
# ---------------------------------------------------------------------------

def _load_search_cases() -> list:
    cases = []
    for json_file in sorted(TEST_DATA_DIR.rglob("*.json")):
        with open(json_file, encoding="utf-8") as fh:
            data = json.load(fh)
        marks = ([pytest.mark.requires_postgresql] if data.get("tier") == "fts" else [])
        cases.append(pytest.param(data, id=data["id"], marks=marks))
    return cases


SEARCH_CASES = _load_search_cases()


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSearchService:
    """
    Data-driven integration tests for SearchService.

    Each parametrized case loads a JSON file and runs it through
    ``_run_search_case``.  To add a new scenario, drop a new .json file
    into the appropriate sub-directory of ``api/tests/data/search_service/``.
    """

    @pytest.mark.parametrize("case", SEARCH_CASES)
    def test_case(self, case):
        _run_search_case(case)

    # ------------------------------------------------------------------
    # Behavioral tests that are not data-driven (entry-point behaviour)
    # ------------------------------------------------------------------

    def test_empty_query_organizations_short_circuits(self, db):
        """search_organizations('') must return an empty queryset without hitting the DB."""
        results = list(SearchService().search_organizations(""))
        assert results == []
