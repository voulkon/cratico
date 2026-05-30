"""
Integration tests for SearchService against a real PostgreSQL database.

Each test class creates a small, controlled "universe" of records and verifies
that search returns exactly the right subset under both search tiers:

  - Tier 1 (postgres_simple): basic ILIKE / icontains  — always available
  - Tier 2 (postgres_fts):    PostgreSQL full-text search via DB triggers

FTS tests are marked `requires_postgresql` because they depend on the
BEFORE INSERT triggers from migration 0053_add_search_vector_triggers.
Those triggers fire automatically when factory records are inserted, so no
manual backfill is needed in tests — the search_vector column is populated
the moment the row lands in the DB.

Run all tests:
    pytest api/tests/test_search_service_integration.py

Run only FTS tests (requires PostgreSQL):
    PG_TEST=1 pytest api/tests/test_search_service_integration.py -m requires_postgresql
"""

import pytest


from core.services.search_service import SearchService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _labels(qs):
    return [o.label for o in qs]


def _names(qs):
    """Return full name strings for signers."""
    return [f"{s.first_name} {s.last_name}" for s in qs]


# ===========================================================================
# Organizations
# ===========================================================================


@pytest.mark.django_db
class TestOrganizationSimpleSearch:
    """
    Universe
    --------
    A  MUNICIPALITY ATHENS        (matches "MUNICIPALITY", "ATHENS")
    B  MUNICIPALITY THESSALONIKI  (matches "MUNICIPALITY", "THESSALONIKI")
    C  PREFECTURE ATTICA          (matches "PREFECTURE", "ATTICA")
    """

    @pytest.fixture(autouse=True)
    def setup_universe(self, db):
        from conftest import (
            CompanyFactory,
            CompanyPersonFactory,
            OrganizationFactory,
            SignerFactory,
            UnitFactory,
        )
        self.org_a = OrganizationFactory(
            label="MUNICIPALITY ATHENS", latin_name="Municipality of Athens"
        )
        self.org_b = OrganizationFactory(
            label="MUNICIPALITY THESSALONIKI",
            latin_name="Municipality of Thessaloniki",
        )
        self.org_c = OrganizationFactory(
            label="PREFECTURE ATTICA", latin_name="Prefecture of Attica"
        )
        self.service = SearchService()

    def test_shared_word_returns_both_matches(self):
        results = list(self.service._search_organizations_simple("MUNICIPALITY", limit=10))
        labels = _labels(results)
        assert "MUNICIPALITY ATHENS" in labels
        assert "MUNICIPALITY THESSALONIKI" in labels
        assert "PREFECTURE ATTICA" not in labels

    def test_unique_word_returns_one_match(self):
        results = list(self.service._search_organizations_simple("ATHENS", limit=10))
        assert len(results) == 1
        assert results[0].label == "MUNICIPALITY ATHENS"

    def test_latin_name_field_is_also_searched(self):
        # latin_name contains "Thessaloniki"; label does not contain "Thess..."
        results = list(
            self.service._search_organizations_simple("Thessaloniki", limit=10)
        )
        labels = _labels(results)
        assert "MUNICIPALITY THESSALONIKI" in labels

    def test_no_match_returns_empty(self):
        results = list(
            self.service._search_organizations_simple("XXXXXXNOTEXISTS", limit=10)
        )
        assert results == []

    def test_limit_is_respected(self):
        results = list(self.service._search_organizations_simple("MUNICIPALITY", limit=1))
        assert len(results) == 1

    def test_empty_query_short_circuits(self):
        results = list(self.service.search_organizations(""))
        assert list(results) == []


@pytest.mark.django_db
@pytest.mark.requires_postgresql
class TestOrganizationFTSSearch:
    """
    Same universe as simple.  DB triggers populate search_vector on INSERT.

    Latin words with the 'greek' FTS config are kept as plain lowercased
    lexemes (no stemming for unrecognised words), so:
        "MUNICIPALITY ATHENS" → 'athens':2 'municipality':1
    """

    @pytest.fixture(autouse=True)
    def setup_universe(self, db):
        from conftest import OrganizationFactory
        self.org_a = OrganizationFactory(label="MUNICIPALITY ATHENS")
        self.org_b = OrganizationFactory(label="MUNICIPALITY THESSALONIKI")
        self.org_c = OrganizationFactory(label="PREFECTURE ATTICA")
        self.service = SearchService()

    def test_shared_word_returns_both_matches(self):
        results = list(self.service._search_organizations_fts("MUNICIPALITY", limit=10))
        labels = _labels(results)
        assert "MUNICIPALITY ATHENS" in labels
        assert "MUNICIPALITY THESSALONIKI" in labels
        assert "PREFECTURE ATTICA" not in labels

    def test_unique_word_returns_one_match(self):
        results = list(self.service._search_organizations_fts("ATHENS", limit=10))
        assert len(results) == 1
        assert results[0].label == "MUNICIPALITY ATHENS"

    def test_prefix_match(self):
        # "MUNICIP" is a prefix of "MUNICIPALITY"
        results = list(self.service._search_organizations_fts("MUNICIP", limit=10))
        labels = _labels(results)
        assert "MUNICIPALITY ATHENS" in labels
        assert "MUNICIPALITY THESSALONIKI" in labels
        assert "PREFECTURE ATTICA" not in labels

    def test_multi_word_uses_and_logic(self):
        # Both words must be present → only org_a matches
        results = list(
            self.service._search_organizations_fts("MUNICIPALITY ATHENS", limit=10)
        )
        assert len(results) == 1
        assert results[0].label == "MUNICIPALITY ATHENS"

    def test_no_match_returns_empty(self):
        results = list(
            self.service._search_organizations_fts("XXXXXXNOTEXISTS", limit=10)
        )
        assert results == []


# ===========================================================================
# Signers
# ===========================================================================


@pytest.mark.django_db
class TestSignerSimpleSearch:
    """
    Universe
    --------
    A  NIKOLAOS  GEORGIOU      (matches "NIKOLAOS", "GEORGIOU")
    B  IOANNIS   PAPADOPOULOS  (matches "IOANNIS",  "PAPADOPOULOS")
    C  MARIA     GEORGIOU      (matches "MARIA",    "GEORGIOU")
    """

    @pytest.fixture(autouse=True)
    def setup_universe(self, db):
        from conftest import (
            OrganizationFactory,
            SignerFactory,
        )
        org = OrganizationFactory()
        self.signer_a = SignerFactory(
            first_name="NIKOLAOS", last_name="GEORGIOU", organization=org
        )
        self.signer_b = SignerFactory(
            first_name="IOANNIS", last_name="PAPADOPOULOS", organization=org
        )
        self.signer_c = SignerFactory(
            first_name="MARIA", last_name="GEORGIOU", organization=org
        )
        self.service = SearchService()

    def test_shared_last_name_returns_two(self):
        results = list(self.service._search_signers_simple("GEORGIOU", limit=10))
        names = _names(results)
        assert "NIKOLAOS GEORGIOU" in names
        assert "MARIA GEORGIOU" in names
        assert "IOANNIS PAPADOPOULOS" not in names

    def test_unique_first_name_returns_one(self):
        results = list(self.service._search_signers_simple("NIKOLAOS", limit=10))
        assert len(results) == 1
        assert results[0].first_name == "NIKOLAOS"

    def test_filter_by_organization(self):
        from conftest import (OrganizationFactory, SignerFactory)
        other_org = OrganizationFactory()
        SignerFactory(first_name="NIKOLAOS", last_name="OTHER", organization=other_org)

        results = list(
            self.service._search_signers_simple(
                "NIKOLAOS", organization_id=self.signer_a.organization.uid, limit=10
            )
        )
        # Only the signer in the specified org
        assert len(results) == 1
        assert results[0].last_name == "GEORGIOU"

    def test_no_match_returns_empty(self):
        results = list(self.service._search_signers_simple("XXXXXXNOTEXISTS", limit=10))
        assert results == []


@pytest.mark.django_db
@pytest.mark.requires_postgresql
class TestSignerFTSSearch:
    """Signer search_vector is built from first_name + last_name (trigger on those cols)."""

    @pytest.fixture(autouse=True)
    def setup_universe(self, db):
        from conftest import (OrganizationFactory, SignerFactory)
        org = OrganizationFactory()
        self.signer_a = SignerFactory(
            first_name="NIKOLAOS", last_name="GEORGIOU", organization=org
        )
        self.signer_b = SignerFactory(
            first_name="IOANNIS", last_name="PAPADOPOULOS", organization=org
        )
        self.signer_c = SignerFactory(
            first_name="MARIA", last_name="GEORGIOU", organization=org
        )
        self.service = SearchService()

    def test_shared_last_name_returns_two(self):
        results = list(self.service._search_signers_fts("GEORGIOU", limit=10))
        names = _names(results)
        assert "NIKOLAOS GEORGIOU" in names
        assert "MARIA GEORGIOU" in names
        assert "IOANNIS PAPADOPOULOS" not in names

    def test_prefix_match(self):
        # "PAPADOP" prefix of "PAPADOPOULOS"
        results = list(self.service._search_signers_fts("PAPADOP", limit=10))
        names = _names(results)
        assert "IOANNIS PAPADOPOULOS" in names
        assert "NIKOLAOS GEORGIOU" not in names

    def test_first_and_last_name_together(self):
        # Both words must appear → narrows to only signer_a
        results = list(self.service._search_signers_fts("NIKOLAOS GEORGIOU", limit=10))
        assert len(results) == 1
        assert results[0].first_name == "NIKOLAOS"


# ===========================================================================
# Units
# ===========================================================================


@pytest.mark.django_db
class TestUnitSimpleSearch:
    """
    Universe (all under the same org unless noted)
    --------
    A  DEPARTMENT OF FINANCE
    B  DEPARTMENT OF EDUCATION
    C  OFFICE OF PROCUREMENT
    """

    @pytest.fixture(autouse=True)
    def setup_universe(self, db):
        from conftest import (
            OrganizationFactory,
            UnitFactory,
        )
        self.org = OrganizationFactory()
        self.unit_a = UnitFactory(
            label="DEPARTMENT OF FINANCE", organization=self.org
        )
        self.unit_b = UnitFactory(
            label="DEPARTMENT OF EDUCATION", organization=self.org
        )
        self.unit_c = UnitFactory(
            label="OFFICE OF PROCUREMENT", organization=self.org
        )
        self.service = SearchService()

    def test_shared_word_returns_two(self):
        results = list(self.service._search_units_simple("DEPARTMENT", limit=10))
        labels = _labels(results)
        assert "DEPARTMENT OF FINANCE" in labels
        assert "DEPARTMENT OF EDUCATION" in labels
        assert "OFFICE OF PROCUREMENT" not in labels

    def test_unique_word_returns_one(self):
        results = list(self.service._search_units_simple("FINANCE", limit=10))
        assert len(results) == 1
        assert results[0].label == "DEPARTMENT OF FINANCE"

    def test_filter_by_organization_excludes_other_org(self):
        from conftest import (OrganizationFactory, UnitFactory)
        other_org = OrganizationFactory()
        UnitFactory(label="DEPARTMENT OF FINANCE", organization=other_org)

        results = list(
            self.service._search_units_simple(
                "DEPARTMENT", organization_id=self.org.uid, limit=10
            )
        )
        for r in results:
            assert r.organization_id == self.org.uid

    def test_no_match_returns_empty(self):
        results = list(self.service._search_units_simple("XXXXXXNOTEXISTS", limit=10))
        assert results == []


@pytest.mark.django_db
@pytest.mark.requires_postgresql
class TestUnitFTSSearch:

    @pytest.fixture(autouse=True)
    def setup_universe(self, db):
        from conftest import (
            OrganizationFactory,
            UnitFactory,
        )
        self.org = OrganizationFactory()
        self.unit_a = UnitFactory(
            label="DEPARTMENT OF FINANCE", organization=self.org
        )
        self.unit_b = UnitFactory(
            label="DEPARTMENT OF EDUCATION", organization=self.org
        )
        self.unit_c = UnitFactory(
            label="OFFICE OF PROCUREMENT", organization=self.org
        )
        self.service = SearchService()

    def test_shared_word_returns_two(self):
        results = list(self.service._search_units_fts("DEPARTMENT", limit=10))
        labels = _labels(results)
        assert "DEPARTMENT OF FINANCE" in labels
        assert "DEPARTMENT OF EDUCATION" in labels
        assert "OFFICE OF PROCUREMENT" not in labels

    def test_prefix_match(self):
        # "DEPART" prefix of "DEPARTMENT"
        results = list(self.service._search_units_fts("DEPART", limit=10))
        labels = _labels(results)
        assert "DEPARTMENT OF FINANCE" in labels
        assert "DEPARTMENT OF EDUCATION" in labels
        assert "OFFICE OF PROCUREMENT" not in labels

    def test_multi_word_narrows_to_one(self):
        results = list(
            self.service._search_units_fts("DEPARTMENT FINANCE", limit=10)
        )
        assert len(results) == 1
        assert results[0].label == "DEPARTMENT OF FINANCE"


# ===========================================================================
# Companies
# ===========================================================================


@pytest.mark.django_db
class TestCompanySimpleSearch:
    """
    Universe  (mirrors the user's AFMEntity example for companies)
    --------
    A  UMBRELLA CORPORATION EE
    B  BANANA GMBH
    C  UMBRELLA LTD
    """

    @pytest.fixture(autouse=True)
    def setup_universe(self, db):
        from conftest import CompanyFactory
        self.co_a = CompanyFactory(co_name_el="UMBRELLA CORPORATION EE")
        self.co_b = CompanyFactory(co_name_el="BANANA GMBH")
        self.co_c = CompanyFactory(co_name_el="UMBRELLA LTD")
        self.service = SearchService()

    def test_shared_word_returns_two(self):
        results = list(self.service._search_companies_simple("UMBRELLA", limit=10))
        names = [c.co_name_el for c in results]
        assert "UMBRELLA CORPORATION EE" in names
        assert "UMBRELLA LTD" in names
        assert "BANANA GMBH" not in names

    def test_unique_word_returns_one(self):
        results = list(self.service._search_companies_simple("CORPORATION", limit=10))
        assert len(results) == 1
        assert results[0].co_name_el == "UMBRELLA CORPORATION EE"

    def test_no_match_returns_empty(self):
        results = list(
            self.service._search_companies_simple("XXXXXXNOTEXISTS", limit=10)
        )
        assert results == []

    def test_branches_excluded(self):
        from conftest import CompanyFactory
        CompanyFactory(co_name_el="UMBRELLA BRANCH", is_branch=True)
        results = list(self.service._search_companies_simple("UMBRELLA", limit=10))
        names = [c.co_name_el for c in results]
        assert "UMBRELLA BRANCH" not in names


@pytest.mark.django_db
@pytest.mark.requires_postgresql
class TestCompanyFTSSearch:
    """
    Same universe as simple.

    search_vector for 'UMBRELLA CORPORATION EE' with to_tsvector('greek', ...)
    yields: 'corporation':2 'ee':3 'umbrella':1
    (Latin words are not stemmed by the Greek dictionary — kept as lowercased lexemes.)
    """

    @pytest.fixture(autouse=True)
    def setup_universe(self, db):
        from conftest import (
            CompanyFactory,
        )
        self.co_a = CompanyFactory(co_name_el="UMBRELLA CORPORATION EE")
        self.co_b = CompanyFactory(co_name_el="BANANA GMBH")
        self.co_c = CompanyFactory(co_name_el="UMBRELLA LTD")
        self.service = SearchService()

    def test_shared_word_returns_two(self):
        results = list(self.service._search_companies_fts("UMBRELLA", limit=10))
        names = [c.co_name_el for c in results]
        assert "UMBRELLA CORPORATION EE" in names
        assert "UMBRELLA LTD" in names
        assert "BANANA GMBH" not in names

    def test_unique_word_returns_one(self):
        results = list(self.service._search_companies_fts("CORPORATION", limit=10))
        assert len(results) == 1
        assert results[0].co_name_el == "UMBRELLA CORPORATION EE"

    def test_prefix_match(self):
        # "UMBREL" is a prefix of "UMBRELLA"
        results = list(self.service._search_companies_fts("UMBREL", limit=10))
        names = [c.co_name_el for c in results]
        assert "UMBRELLA CORPORATION EE" in names
        assert "UMBRELLA LTD" in names
        assert "BANANA GMBH" not in names

    def test_multi_word_uses_and_logic(self):
        # "UMBRELLA" AND "CORPORATION" → only company A
        results = list(
            self.service._search_companies_fts("UMBRELLA CORPORATION", limit=10)
        )
        assert len(results) == 1
        assert results[0].co_name_el == "UMBRELLA CORPORATION EE"

    def test_no_match_returns_empty(self):
        results = list(
            self.service._search_companies_fts("XXXXXXNOTEXISTS", limit=10)
        )
        assert results == []

    def test_branches_excluded(self):
        from conftest import (
            CompanyFactory,
        )
        CompanyFactory(co_name_el="UMBRELLA BRANCH", is_branch=True)
        results = list(self.service._search_companies_fts("UMBRELLA", limit=10))
        names = [c.co_name_el for c in results]
        assert "UMBRELLA BRANCH" not in names


# ===========================================================================
# Company Persons
# ===========================================================================


@pytest.mark.django_db
class TestCompanyPersonSimpleSearch:
    """
    Universe (all under the same company)
    --------
    A  JOHN UMBRELLA  (matches "JOHN", "UMBRELLA")
    B  JANE BANANA    (matches "JANE", "BANANA")
    C  JOHN SMITH     (matches "JOHN", "SMITH")
    """

    @pytest.fixture(autouse=True)
    def setup_universe(self, db):
        from conftest import (
            CompanyFactory,
            CompanyPersonFactory
        )
        self.company = CompanyFactory()
        self.person_a = CompanyPersonFactory(
            person_name="JOHN UMBRELLA", company=self.company
        )
        self.person_b = CompanyPersonFactory(
            person_name="JANE BANANA", company=self.company
        )
        self.person_c = CompanyPersonFactory(
            person_name="JOHN SMITH", company=self.company
        )
        self.service = SearchService()

    def test_shared_first_name_returns_two(self):
        results = list(
            self.service._search_company_persons_simple("JOHN", limit=10)
        )
        names = [p.person_name for p in results]
        assert "JOHN UMBRELLA" in names
        assert "JOHN SMITH" in names
        assert "JANE BANANA" not in names

    def test_unique_name_returns_one(self):
        results = list(
            self.service._search_company_persons_simple("UMBRELLA", limit=10)
        )
        assert len(results) == 1
        assert results[0].person_name == "JOHN UMBRELLA"

    def test_filter_by_company(self):
        from conftest import (CompanyFactory, CompanyPersonFactory)
        other_company = CompanyFactory()
        CompanyPersonFactory(person_name="JOHN OTHER", company=other_company)

        results = list(
            self.service._search_company_persons_simple(
                "JOHN", company_id=self.company.id, limit=10
            )
        )
        for r in results:
            assert r.company_id == self.company.id

    def test_no_match_returns_empty(self):
        results = list(
            self.service._search_company_persons_simple("XXXXXXNOTEXISTS", limit=10)
        )
        assert results == []


@pytest.mark.django_db
@pytest.mark.requires_postgresql
class TestCompanyPersonFTSSearch:
    """search_vector for company persons is built from person_name (trigger on that col)."""

    @pytest.fixture(autouse=True)
    def setup_universe(self, db):
        from conftest import (CompanyFactory, CompanyPersonFactory)
        self.company = CompanyFactory()
        self.person_a = CompanyPersonFactory(
            person_name="JOHN UMBRELLA", company=self.company
        )
        self.person_b = CompanyPersonFactory(
            person_name="JANE BANANA", company=self.company
        )
        self.person_c = CompanyPersonFactory(
            person_name="JOHN SMITH", company=self.company
        )
        self.service = SearchService()

    def test_shared_name_returns_two(self):
        results = list(self.service._search_company_persons_fts("JOHN", limit=10))
        names = [p.person_name for p in results]
        assert "JOHN UMBRELLA" in names
        assert "JOHN SMITH" in names
        assert "JANE BANANA" not in names

    def test_prefix_match(self):
        # "UMBREL" is a prefix of "UMBRELLA"
        results = list(
            self.service._search_company_persons_fts("UMBREL", limit=10)
        )
        names = [p.person_name for p in results]
        assert "JOHN UMBRELLA" in names
        assert "JANE BANANA" not in names
        assert "JOHN SMITH" not in names

    def test_multi_word_narrows_to_one(self):
        results = list(
            self.service._search_company_persons_fts("JOHN UMBRELLA", limit=10)
        )
        assert len(results) == 1
        assert results[0].person_name == "JOHN UMBRELLA"

    def test_no_match_returns_empty(self):
        results = list(
            self.service._search_company_persons_fts("XXXXXXNOTEXISTS", limit=10)
        )
        assert results == []
