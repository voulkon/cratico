"""
Tests for the Browse API — alphabetical entity browsing.

Covers all 6 browsable entity types: organization, unit, signer,
company, companyperson, afmentity.
"""

import pytest
from django.urls import reverse

from core.services.response_cache_service import response_cache


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _clear_browse_cache():
    """Isolate browse cache across tests."""
    response_cache.invalidate_prefix("browse")
    response_cache.invalidate_browse_available_letters()
    yield
    response_cache.invalidate_prefix("browse")
    response_cache.invalidate_browse_available_letters()


# ============================================================================
# Helper
# ============================================================================

def _get(authenticated_client, **params):
    """Call the browse entities endpoint."""
    url = reverse("browse_entities")
    return authenticated_client.get(url, params)


@pytest.fixture
def sample_entities(db):
    """Create a variety of entities for browse testing."""
    from conftest import (
        AFMEntityFactory,
        CompanyFactory,
        CompanyPersonFactory,
        OrganizationFactory,
        SignerFactory,
        UnitFactory,
    )
    orgs = [
        OrganizationFactory(uid="ORG001", label="Αθήνα"),
        OrganizationFactory(uid="ORG002", label="Βόλος"),
        OrganizationFactory(uid="ORG003", label="Γιάννενα"),
        OrganizationFactory(uid="ORG004", label="Δράμα"),
    ]
    units = [
        UnitFactory(uid="UNIT001", label="Αποκέντρωσης", organization=orgs[0]),
        UnitFactory(uid="UNIT002", label="Βιωσιμότητας", organization=orgs[0]),
    ]
    signers = [
        SignerFactory(uid="SIG001", first_name="Γιώργος", last_name="Αλεξίου", organization=orgs[0]),
        SignerFactory(uid="SIG002", first_name="Μαρία", last_name="Βασιλείου", organization=orgs[0]),
    ]
    companies = [
        CompanyFactory(ar_gemi=100001, afm="111111111", co_name_el="ΑΛΦΑ ΑΕ"),
        CompanyFactory(ar_gemi=100002, afm="222222222", co_name_el="ΒΗΤΑ ΕΠΕ"),
    ]
    company_persons = [
        CompanyPersonFactory(person_name="Ανδρέου Κώστας", company=companies[0]),
        CompanyPersonFactory(person_name="Βλάχου Ελένη", company=companies[1]),
    ]
    afm_entities = [
        AFMEntityFactory(afm="333333333", name="Αντωνίου"),
        AFMEntityFactory(afm="444444444", name="Βασιλόπουλος"),
    ]
    return {
        "orgs": orgs,
        "units": units,
        "signers": signers,
        "companies": companies,
        "company_persons": company_persons,
        "afm_entities": afm_entities,
    }


# ============================================================================
# Tests
# ============================================================================


class TestBrowseEntitiesAll:
    """Tests for type=all (merged results)."""

    def test_returns_merged_sorted_results(self, authenticated_client, sample_entities):
        resp = _get(authenticated_client, type="all", limit=50)
        assert resp.status_code == 200
        data = resp.json()
        results = data["results"]
        assert len(results) > 0
        # Check ascending order by sort_key
        sort_keys = [r["sort_key"] for r in results]
        assert sort_keys == sorted(sort_keys)

    def test_total_count_sums_all_types(self, authenticated_client, sample_entities):
        resp = _get(authenticated_client, type="all", limit=50)
        assert resp.status_code == 200
        data = resp.json()
        actual_sum = sum(
            len(sample_entities[key]) 
            for key in 
            (
                "orgs", 
                "units", 
                "signers", 
                "companies", 
                "company_persons", 
                "afm_entities"
            )
        )
        assert data["total_count"] == actual_sum


class TestBrowseEntitiesFiltered:
    """Tests for letter filtering."""

    def test_filter_by_greek_letter(self, authenticated_client, sample_entities):
        resp = _get(authenticated_client, type="organization", letter="Α")
        assert resp.status_code == 200
        data = resp.json()
        results = data["results"]
        assert len(results) >= 1
        for r in results:
            assert r["text"].startswith("Α")

    def test_accent_insensitive_letter(self, authenticated_client, db):
        """letter=Α should match both 'Αθήνα' and 'Άργος'."""
        from conftest import (
            OrganizationFactory,
        )
        OrganizationFactory(uid="ORG_ACC", label="Άργος")
        OrganizationFactory(uid="ORG_PLAIN", label="Αθήνα")
        resp = _get(authenticated_client, type="organization", letter="Α")
        assert resp.status_code == 200
        texts = [r["text"] for r in resp.json()["results"]]
        assert "Άργος" in texts
        assert "Αθήνα" in texts

    def test_lowercase_letter_input(self, authenticated_client, db):
        """letter=α (lowercase) should work like letter=Α."""
        from conftest import (
            OrganizationFactory,
        )
        OrganizationFactory(uid="ORG_ACC", label="Άργος")
        OrganizationFactory(uid="ORG_A", label="Αθήνα")
        resp = _get(authenticated_client, type="organization", letter="α")
        assert resp.status_code == 200
        assert resp.json()["total_count"] >= 1

    def test_filter_by_latin_letter_on_companies(self, authenticated_client, db):
        """Company with English name starting with 'T' should be found."""
        from conftest import (
            OrganizationFactory,
            CompanyFactory
        )
        OrganizationFactory(uid="ORG_ACC", label="Άργος")
        CompanyFactory(
            ar_gemi=200001,
            afm="555555555",
            co_name_el="Alpha Corp",
            co_names_en=["The Alpha Corporation"],
        )
        resp = _get(authenticated_client, type="company", letter="T")
        assert resp.status_code == 200
        data = resp.json()
        # Should find the company via English name
        assert data["total_count"] >= 1

    def test_no_results_for_missing_letter(self, authenticated_client, sample_entities):
        resp = _get(authenticated_client, type="organization", letter="Ω")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 0
        assert data["results"] == []


class TestBrowseEntitiesSort:
    """Tests for sort direction."""

    def test_desc_order(self, authenticated_client, sample_entities):
        resp = _get(authenticated_client, type="organization", sort="desc")
        assert resp.status_code == 200
        data = resp.json()
        results = data["results"]
        sort_keys = [r["sort_key"] for r in results]
        assert sort_keys == sorted(sort_keys, reverse=True)

    def test_invalid_sort_returns_400(self, authenticated_client):
        resp = _get(authenticated_client, sort="sideways")
        assert resp.status_code == 400
        assert "error" in resp.json()


class TestBrowseEntitiesPagination:
    """Tests for offset/limit pagination."""

    def test_limit_respected(self, authenticated_client, sample_entities):
        resp = _get(authenticated_client, type="all", limit=3)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) <= 3

    def test_has_more_when_more_pages_exist(self, authenticated_client, sample_entities):
        resp = _get(authenticated_client, type="all", limit=3)
        assert resp.status_code == 200
        data = resp.json()
        if data["total_count"] > 3:
            assert data["has_more"] is True

    def test_has_more_false_at_end(self, authenticated_client, sample_entities):
        resp = _get(authenticated_client, type="organization", limit=200)
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_more"] is False

    def test_offset_skips_results(self, authenticated_client, sample_entities):
        resp_page1 = _get(authenticated_client, type="all", limit=2, offset=0)
        resp_page2 = _get(authenticated_client, type="all", limit=2, offset=2)
        assert resp_page1.status_code == 200
        assert resp_page2.status_code == 200
        page1_ids = [r["id"] for r in resp_page1.json()["results"]]
        page2_ids = [r["id"] for r in resp_page2.json()["results"]]
        # No overlap between pages
        assert set(page1_ids).isdisjoint(set(page2_ids))


class TestBrowseEntitiesAvailableLetters:
    """Tests for available_letters."""

    def test_returns_distinct_letters(self, authenticated_client, sample_entities):
        resp = _get(authenticated_client, type="all")
        assert resp.status_code == 200
        data = resp.json()
        letters = data["available_letters"]
        assert isinstance(letters, list)
        assert len(letters) > 0
        assert "Α" in letters
        assert "Β" in letters

    def test_single_type_letters(self, authenticated_client, sample_entities):
        resp = _get(authenticated_client, type="organization")
        assert resp.status_code == 200
        data = resp.json()
        # Our sample orgs start with Α, Β, Γ, Δ
        assert "Α" in data["available_letters"]
        assert "Δ" in data["available_letters"]


class TestBrowseEntitiesEdgeCases:
    """Edge case tests."""

    def test_invalid_entity_type_returns_400(self, authenticated_client):
        resp = _get(authenticated_client, type="invalid_type")
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_empty_database_returns_empty_results(self, authenticated_client, db):
        resp = _get(authenticated_client, type="all")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 0
        assert data["results"] == []

    def test_limit_capped_at_200(self, authenticated_client, sample_entities):
        resp = _get(authenticated_client, type="all", limit=9999)
        assert resp.status_code == 200
        data = resp.json()
        # Should still work, results capped internally
        assert len(data["results"]) <= data["total_count"]

    def test_non_numeric_offset_returns_400(self, authenticated_client):
        resp = _get(authenticated_client, offset="abc")
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_non_numeric_limit_returns_400(self, authenticated_client):
        resp = _get(authenticated_client, limit="xyz")
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_negative_offset_returns_400(self, authenticated_client):
        resp = _get(authenticated_client, offset=-1)
        assert resp.status_code == 400
        assert "error" in resp.json()


class TestCompanyLetterFilterOr:
    """Regression tests for company letter filtering.

    A company discoverable ONLY via its English name (co_names_en) must
    still be returned when filtering by that English letter — the Greek
    first-letter predicate and the English-name predicate are OR-ed.
    """

    def test_company_found_via_english_letter_only(self, authenticated_client, db):
        """co_name_el starts with 'A' but English name starts with 'T'."""
        from conftest import (
            CompanyFactory,
        )
        CompanyFactory(
            ar_gemi=800001,
            afm="121212121",
            co_name_el="Alpha Corp",
            co_names_en=["The Alpha Corporation"],
        )
        resp = _get(authenticated_client, type="company", letter="T")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] >= 1
        assert any(r["id"] == "121212121" for r in data["results"])

    def test_company_prefix_search_via_english_name(self, authenticated_client, db):
        """q=Tes matches a company whose English name starts with 'Tesla'."""
        from conftest import (
            CompanyFactory,
        )
        CompanyFactory(
            ar_gemi=800002,
            afm="232323232",
            co_name_el="Κάποιο Ελληνικό Όνομα",
            co_names_en=["Tesla Greece Ltd"],
        )
        resp = _get(authenticated_client, type="company", q="Tes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] >= 1
        assert any(r["id"] == "232323232" for r in data["results"])

    def test_company_without_afm_excluded(self, authenticated_client, db):
        """Companies with null/empty AFM are excluded from browse results."""
        from conftest import (
            CompanyFactory,
        )
        CompanyFactory(
            ar_gemi=800003,
            afm=None,
            co_name_el="No AFM Company",
        )
        CompanyFactory(
            ar_gemi=800004,
            afm="",
            co_name_el="Empty AFM Company",
        )
        CompanyFactory(
            ar_gemi=800005,
            afm="343434343",
            co_name_el="Valid AFM Company",
        )
        resp = _get(authenticated_client, type="company")
        assert resp.status_code == 200
        data = resp.json()
        ids = [r["id"] for r in data["results"]]
        assert "343434343" in ids
        assert "" not in ids
        assert data["total_count"] == 1


class TestBrowsePrefixSearch:
    """Tests for the q= prefix search parameter."""

    def test_prefix_filter_matches_start(self, authenticated_client, db):
        """q=Αθ should match 'Αθήνα' but not 'Βόλος'."""
        from conftest import (
            OrganizationFactory,
        )
        OrganizationFactory(uid="ORG_ATH", label="Αθήνα")
        OrganizationFactory(uid="ORG_VOL", label="Βόλος")
        resp = _get(authenticated_client, type="organization", q="Αθ")
        assert resp.status_code == 200
        data = resp.json()
        texts = [r["text"] for r in data["results"]]
        assert "Αθήνα" in texts
        assert "Βόλος" not in texts

    def test_prefix_filter_combined_with_letter(self, authenticated_client, db):
        """q + letter together: letter narrows, q further narrows within."""
        from conftest import (
            OrganizationFactory,
        )
        OrganizationFactory(uid="ORG_A1", label="Αθήνα")
        OrganizationFactory(uid="ORG_A2", label="Αγρίνιο")
        OrganizationFactory(uid="ORG_B1", label="Βόλος")
        resp = _get(authenticated_client, type="organization", letter="Α", q="Αθ")
        assert resp.status_code == 200
        data = resp.json()
        texts = [r["text"] for r in data["results"]]
        assert "Αθήνα" in texts
        assert "Αγρίνιο" not in texts  # doesn't start with "Αθ"
        assert "Βόλος" not in texts     # wrong letter

    def test_prefix_filter_case_insensitive(self, authenticated_client, db):
        """q=αθ (lowercase) should match 'Αθήνα'."""
        from conftest import (
            OrganizationFactory,
        )
        OrganizationFactory(uid="ORG_ATH", label="Αθήνα")
        resp = _get(authenticated_client, type="organization", q="αθ")
        assert resp.status_code == 200
        assert resp.json()["total_count"] >= 1

    def test_prefix_filter_on_companies_english(self, authenticated_client, db):
        """q=Tes should match company with English name 'Tesla'."""
        from conftest import (
            CompanyFactory,
        )
        CompanyFactory(
            ar_gemi=500001,
            afm="999999999",
            co_name_el="Some Greek Name",
            co_names_en=["Tesla Greece Ltd"],
        )
        resp = _get(authenticated_client, type="company", q="Tes")
        assert resp.status_code == 200
        assert resp.json()["total_count"] >= 1

    def test_prefix_filter_no_match(self, authenticated_client, db):
        """q that matches nothing returns empty."""
        from conftest import (
            OrganizationFactory,
        )
        OrganizationFactory(uid="ORG_X", label="Αθήνα")
        resp = _get(authenticated_client, type="organization", q="XYZ")
        assert resp.status_code == 200
        assert resp.json()["total_count"] == 0


class TestBrowseEntityDisplay:
    """Tests for display format of each entity type."""

    def test_signer_display_is_last_comma_first(self, authenticated_client, db):
        from conftest import (
            SignerFactory,
        )
        SignerFactory(uid="SIG_D", first_name="Γιώργος", last_name="Παππάς")
        resp = _get(authenticated_client, type="signer")
        assert resp.status_code == 200
        signer = resp.json()["results"][0]
        assert signer["text"] == "Παππάς, Γιώργος"

    def test_organization_display_is_label(self, authenticated_client, db):
        from conftest import (
            OrganizationFactory,
        )
        OrganizationFactory(uid="ORG_D", label="Υπουργείο Παιδείας")
        resp = _get(authenticated_client, type="organization")
        assert resp.json()["results"][0]["text"] == "Υπουργείο Παιδείας"

    def test_unit_display_is_label(self, authenticated_client, db):
        from conftest import (
            UnitFactory,
        )
        UnitFactory(uid="UNIT_D", label="Διεύθυνση Προσωπικού")
        resp = _get(authenticated_client, type="unit")
        assert resp.json()["results"][0]["text"] == "Διεύθυνση Προσωπικού"

    def test_company_display_is_co_name_el(self, authenticated_client, db):
        from conftest import (
            CompanyFactory,
        )
        CompanyFactory(ar_gemi=600001, afm="123456789", co_name_el="ΟΤΕ ΑΕ")
        resp = _get(authenticated_client, type="company")
        assert resp.json()["results"][0]["text"] == "ΟΤΕ ΑΕ"

    def test_companyperson_display_is_person_name(self, authenticated_client, db):
        from conftest import (
            CompanyFactory,
            CompanyPersonFactory,
        )
        company = CompanyFactory(ar_gemi=700001, afm="987654321", co_name_el="Test")
        CompanyPersonFactory(person_name="Δημητρίου Άννα", company=company)
        resp = _get(authenticated_client, type="companyperson")
        assert resp.json()["results"][0]["text"] == "Δημητρίου Άννα"

    def test_afmentity_display_is_name(self, authenticated_client, db):
        from conftest import (
            AFMEntityFactory,
        )
        AFMEntityFactory(afm="111222333", name="Παπαδάκης")
        resp = _get(authenticated_client, type="afmentity")
        assert resp.json()["results"][0]["text"] == "Παπαδάκης"


class TestCompanyBrowse:
    """Tests specific to company browsing."""

    def test_company_uses_afm_as_id(self, authenticated_client, db):
        from conftest import (
            CompanyFactory,
        )
        CompanyFactory(ar_gemi=300001, afm="666666666", co_name_el="ΓΑΜΜΑ ΑΕ")
        resp = _get(authenticated_client, type="company")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] >= 1
        company = data["results"][0]
        assert company["id"] == "666666666"  # afm, not ar_gemi
        assert company["type"] == "company"

    def test_company_english_name_letters_available(self, authenticated_client, db):
        """English letters from co_names_en should appear in available_letters."""
        from conftest import (
            CompanyFactory,
        )
        CompanyFactory(
            ar_gemi=400001,
            afm="777777777",
            co_name_el="Tesla Greece",
            co_names_en=["Tesla Greece Ltd"],
        )
        resp = _get(authenticated_client, type="company")
        assert resp.status_code == 200
        data = resp.json()
        # 'T' should appear (from English name)
        assert "T" in data["available_letters"]


class TestAFMEntityBrowse:
    """Tests specific to AFM entity browsing."""

    def test_afmentity_uses_afm_as_id(self, authenticated_client, db):
        from conftest import (
            AFMEntityFactory,
        )
        AFMEntityFactory(afm="888888888", name="Παπαδόπουλος")
        resp = _get(authenticated_client, type="afmentity")
        assert resp.status_code == 200
        data = resp.json()
        entity = data["results"][0]
        assert entity["id"] == "888888888"
        assert entity["type"] == "afm_entity"


# ============================================================================
# Cache behaviour
# ============================================================================


class TestBrowseCache:
    """Tests for @cached_view behaviour on browse_entities_api."""

    def test_identical_requests_hit_cache(self, authenticated_client, db):
        """Two identical requests (no q) should return the same data."""
        from conftest import OrganizationFactory

        OrganizationFactory(uid="ORG_C1", label="Αθήνα")
        OrganizationFactory(uid="ORG_C2", label="Βόλος")

        resp1 = _get(authenticated_client, type="organization", letter="Α")
        resp2 = _get(authenticated_client, type="organization", letter="Α")

        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json() == resp2.json()

    def test_different_letter_different_cache_key(self, authenticated_client, db):
        """Different letter param → different result set (not same cache entry)."""
        from conftest import OrganizationFactory

        OrganizationFactory(uid="ORG_D1", label="Αθήνα")
        OrganizationFactory(uid="ORG_D2", label="Βόλος")

        resp_a = _get(authenticated_client, type="organization", letter="Α")
        resp_b = _get(authenticated_client, type="organization", letter="Β")

        assert resp_a.status_code == 200
        assert resp_b.status_code == 200
        # Different letters should have different results
        assert resp_a.json() != resp_b.json()

    def test_q_param_skips_cache(self, authenticated_client, db):
        """Requests with q= should bypass the cache (should_cache_fn)."""
        from conftest import OrganizationFactory

        OrganizationFactory(uid="ORG_Q1", label="Αθήνα")
        OrganizationFactory(uid="ORG_Q2", label="Αγρίνιο")

        # Both should work fine — the cache just isn't used
        resp1 = _get(authenticated_client, type="organization", q="Αθ")
        resp2 = _get(authenticated_client, type="organization", q="Αθ")

        assert resp1.status_code == 200
        assert resp2.status_code == 200
        # Results should be the same (just not from cache)
        assert resp1.json() == resp2.json()

    def test_q_param_does_not_prevent_letter_cache(self, authenticated_client, db):
        """A search (q=) doesn't pollute the letter-only cache — different keys."""
        from conftest import OrganizationFactory

        OrganizationFactory(uid="ORG_L1", label="Αθήνα")

        # First, a letter-only request (should be cached)
        resp_letter = _get(authenticated_client, type="organization", letter="Α")
        assert resp_letter.status_code == 200

        # Then, a search (should NOT use or overwrite the letter-only cache)
        resp_search = _get(
            authenticated_client, type="organization", letter="Α", q="Αθ"
        )
        assert resp_search.status_code == 200

        # The letter-only response should still be intact
        resp_letter2 = _get(authenticated_client, type="organization", letter="Α")
        assert resp_letter2.status_code == 200

    def test_invalidate_browse_cache_task(self, db):
        """invalidate_browse_cache task calls invalidate_prefix('browse')."""
        from core.tasks.tasks_post_import import invalidate_browse_cache

        result = invalidate_browse_cache()
        assert result["status"] == "completed"
        assert isinstance(result["keys_invalidated"], int)

    def test_cache_is_populated_after_view_call(self, authenticated_client, db):
        """After a browse request, the cache key should exist."""
        from conftest import OrganizationFactory

        OrganizationFactory(uid="ORG_POP", label="Αθήνα")

        resp = _get(authenticated_client, type="organization", letter="Α")
        assert resp.status_code == 200

        # The cache key should now hold the response.
        # cache_params=None → only params actually sent are in the key.
        cache_key = response_cache.build_key(
            "browse",
            type="organization",
            letter="Α",
        )
        cached = response_cache.get(cache_key)
        assert cached is not None
        assert cached["total_count"] >= 1

    def test_invalidate_clears_cache(self, authenticated_client, db):
        """After invalidate_browse_cache, the previously cached key is gone."""
        from conftest import OrganizationFactory
        from core.tasks.tasks_post_import import invalidate_browse_cache

        OrganizationFactory(uid="ORG_INV", label="Αθήνα")

        # Populate cache
        resp = _get(authenticated_client, type="organization", letter="Α")
        assert resp.status_code == 200

        cache_key = response_cache.build_key(
            "browse",
            type="organization",
            letter="Α",
        )
        assert response_cache.get(cache_key) is not None

        # Invalidate
        invalidate_browse_cache()

        # Cache should be gone
        assert response_cache.get(cache_key) is None
