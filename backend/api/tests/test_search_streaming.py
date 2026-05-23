"""
Unit tests for SSE streaming search endpoints
Tests get_entities_fast(), get_documents_slow(), and search_stream_api()
"""

from unittest.mock import MagicMock, patch

from api.views.search.entity_search import (
    autocomplete_suggestions_api,
    search_stream_api,
)
from api.views.search.entity_search_utils import (
    get_administrative_terms_autocomplete,
    get_documents_slow,
    get_entities_fast,
)
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

User = get_user_model()


class TestGetEntitiesFast(TestCase):
    """Test the get_entities_fast function"""

    def setUp(self):
        """Set up test fixtures"""
        self.test_query = "ΔΗΜΟΣ"

    @patch("api.views.search.entity_search.SearchService")
    def test_get_entities_fast_basic(self, mock_search_service):
        """Test basic entity search with all types"""
        # Mock the search service
        mock_service = MagicMock()
        mock_search_service.return_value = mock_service

        # Mock organization results
        mock_org = MagicMock()
        mock_org.uid = "org-123"
        mock_org.label = "ΔΗΜΟΣ ΑΘΗΝΑΙΩΝ"
        mock_org.category = "Municipality"
        mock_org.latin_name = "Athens Municipality"
        mock_org.vat_number = "090025537"
        mock_org.status = "active"
        mock_org.website = "https://www.cityofathens.gr"
        mock_org.supervisor_org_name = "Ministry of Interior"

        mock_service.search_organizations.return_value = [mock_org]
        mock_service.search_signers.return_value = []
        mock_service.search_units.return_value = []
        mock_service.search_companies.return_value = []
        mock_service.search_company_persons.return_value = []

        # Call the function
        results = get_entities_fast(
            self.test_query,
            entity_types=[
                "organization",
                "signer",
                "unit",
                "company",
                "company_person",
            ],
            limit=5,
        )

        # Assertions
        self.assertEqual(results["query"], self.test_query)
        self.assertEqual(results["type"], "entities")
        self.assertEqual(results["total_count"], 1)
        self.assertIn("organizations", results["results"])
        self.assertEqual(len(results["results"]["organizations"]), 1)

        # Check organization data structure
        org_result = results["results"]["organizations"][0]
        self.assertEqual(org_result["id"], "org-123")
        self.assertEqual(org_result["type"], "organization")
        self.assertIn("ΔΗΜΟΣ ΑΘΗΝΑΙΩΝ", org_result["title"])
        self.assertIn("details", org_result)

    @patch("api.views.search.entity_search.SearchService")
    def test_get_entities_fast_empty_query(self, mock_search_service):
        """Test with empty query"""
        results = get_entities_fast("", limit=5)

        self.assertEqual(results["query"], "")
        self.assertEqual(results["total_count"], 0)
        self.assertEqual(results["results"], {})

    @patch("api.views.search.entity_search.SearchService")
    def test_get_entities_fast_filtered_types(self, mock_search_service):
        """Test with specific entity types only"""
        mock_service = MagicMock()
        mock_search_service.return_value = mock_service

        mock_service.search_organizations.return_value = []

        # Call with only organizations
        results = get_entities_fast(
            self.test_query, entity_types=["organization"], limit=5
        )

        # Should only have organizations key
        self.assertIn("organizations", results["results"])
        self.assertNotIn("signers", results["results"])
        self.assertNotIn("units", results["results"])

    @patch("api.views.search.entity_search.SearchService")
    def test_get_entities_fast_with_limit(self, mock_search_service):
        """Test that limit parameter is passed correctly"""
        mock_service = MagicMock()
        mock_search_service.return_value = mock_service
        mock_service.search_organizations.return_value = []

        get_entities_fast(self.test_query, entity_types=["organization"], limit=10)

        # Verify limit was passed to search
        mock_service.search_organizations.assert_called_once_with(self.test_query, 10)


class TestGetDocumentsSlow(TestCase):
    """Test the get_documents_slow function"""

    @patch("api.views.search.entity_search.SearchService")
    def test_get_documents_slow_basic(self, mock_search_service):
        """Test basic document search"""
        mock_service = MagicMock()
        mock_search_service.return_value = mock_service

        # Mock document results
        mock_extraction = MagicMock()
        mock_extraction.id = 123
        mock_extraction.extraction_provider = "tesseract"
        mock_extraction.is_scanned_document = True

        mock_decision = MagicMock()
        mock_decision.id = 456
        mock_decision.subject = "Test Decision Subject"
        mock_decision.ada = "ABC123"
        mock_decision.issue_date = None
        mock_decision.amount = None
        mock_decision.currency = None
        mock_decision.status = "published"
        mock_decision.protocol_number = "P-2024-001"
        mock_decision.organization.label = "Test Organization"
        mock_decision.organization.uid = "org-test"
        mock_decision.get_decision_type_label.return_value = "Contract"

        mock_extraction.decision = mock_decision

        mock_service.search_documents.return_value = {
            "results": [
                {"extraction": mock_extraction, "text_excerpt": "Test excerpt..."}
            ],
            "count": 1,
        }

        # Call the function
        results = get_documents_slow("δημοσια συμβαση", limit=5)

        # Assertions
        self.assertEqual(results["type"], "documents")
        self.assertEqual(results["total_count"], 1)
        self.assertIn("documents", results["results"])
        self.assertEqual(len(results["results"]["documents"]), 1)

        # Check document structure
        doc_result = results["results"]["documents"][0]
        self.assertEqual(doc_result["id"], 123)
        self.assertEqual(doc_result["type"], "document")
        self.assertEqual(doc_result["details"]["decision_id"], 456)

    @patch("api.views.search.entity_search.SearchService")
    def test_get_documents_slow_empty_query(self, mock_search_service):
        """Test with empty query"""
        results = get_documents_slow("", limit=5)

        self.assertEqual(results["query"], "")
        self.assertEqual(results["total_count"], 0)
        self.assertEqual(results["results"], {})

    @patch("api.views.search.entity_search.SearchService")
    def test_get_documents_slow_handles_errors(self, mock_search_service):
        """Test error handling when OpenSearch fails"""
        mock_service = MagicMock()
        mock_search_service.return_value = mock_service
        mock_service.search_documents.side_effect = Exception(
            "OpenSearch connection failed"
        )

        # Should not raise, just return empty results with error
        results = get_documents_slow("test query", limit=5)

        self.assertEqual(results["total_count"], 0)
        self.assertEqual(results["results"]["documents"], [])
        self.assertIn("error", results)


class TestSearchStreamAPI(TestCase):
    """Test the SSE streaming search API endpoint"""

    def setUp(self):
        """Set up test fixtures"""
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )

    @patch("api.views.search.entity_search.get_entities_fast")
    @patch("api.views.search.entity_search.get_documents_slow")
    def test_search_stream_api_basic(self, mock_get_docs, mock_get_entities):
        """Test basic SSE stream endpoint"""
        # Mock entity results
        mock_get_entities.return_value = {
            "query": "ΔΗΜΟΣ",
            "results": {"organizations": []},
            "total_count": 0,
            "type": "entities",
        }

        # Mock document results
        mock_get_docs.return_value = {
            "query": "ΔΗΜΟΣ",
            "results": {"documents": []},
            "total_count": 0,
            "type": "documents",
        }

        # Create request
        request = self.factory.get("/api/search/stream/", {"q": "ΔΗΜΟΣ", "limit": "5"})
        request.user = self.user

        # Call the view
        response = search_stream_api(request)

        # Check response
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/event-stream")
        self.assertEqual(response["Cache-Control"], "no-cache")

        # Consume the streaming response
        content = b"".join(response.streaming_content).decode("utf-8")

        # Should contain entity data
        self.assertIn("entities", content)
        # Should contain document data
        self.assertIn("documents", content)
        # Should contain done signal
        self.assertIn("done", content)

    @patch("api.views.search.entity_search.get_entities_fast")
    def test_search_stream_api_without_documents(self, mock_get_entities):
        """Test SSE stream without document search"""
        mock_get_entities.return_value = {
            "query": "ΔΗΜΟΣ",
            "results": {"organizations": []},
            "total_count": 0,
            "type": "entities",
        }

        # Create request with include_documents=false
        request = self.factory.get(
            "/api/search/stream/",
            {"q": "ΔΗΜΟΣ", "limit": "5", "include_documents": "false"},
        )
        request.user = self.user

        response = search_stream_api(request)
        content = b"".join(response.streaming_content).decode("utf-8")

        # Should NOT contain documents
        self.assertNotIn('"type": "documents"', content)
        # Should still contain entities and done
        self.assertIn("entities", content)
        self.assertIn("done", content)


class TestAutocompleteAPI(TestCase):
    """Test the autocomplete suggestions API"""

    def setUp(self):
        """Set up test fixtures"""
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )

    def test_autocomplete_basic(self):
        """Test basic autocomplete functionality"""
        request = self.factory.get("/api/search/autocomplete/", {"q": "ΔΗΜ"})
        request.user = self.user

        response = autocomplete_suggestions_api(request)

        self.assertEqual(response.status_code, 200)
        data = response.data

        # Should return matching suggestions
        self.assertIn("suggestions", data)
        self.assertTrue(len(data["suggestions"]) > 0)

        # Check that all suggestions start with ΔΗΜ
        for suggestion in data["suggestions"]:
            self.assertTrue(suggestion["text"].startswith("ΔΗΜ"))

    def test_autocomplete_empty_query(self):
        """Test autocomplete with empty query returns all terms"""
        request = self.factory.get("/api/search/autocomplete/")
        request.user = self.user

        response = autocomplete_suggestions_api(request)

        self.assertEqual(response.status_code, 200)
        data = response.data

        # Should return all administrative terms
        self.assertEqual(
            len(data["suggestions"]), len(get_administrative_terms_autocomplete())
        )

    def test_autocomplete_with_category(self):
        """Test autocomplete with category filter"""
        request = self.factory.get(
            "/api/search/autocomplete/", {"q": "", "category": "organization"}
        )
        request.user = self.user

        response = autocomplete_suggestions_api(request)
        data = response.data

        # Should only return organization suggestions
        for suggestion in data["suggestions"]:
            self.assertEqual(suggestion["category"], "organization")

    def test_autocomplete_no_match(self):
        """Test autocomplete with query that matches nothing"""
        request = self.factory.get("/api/search/autocomplete/", {"q": "ZZZZZ"})
        request.user = self.user

        response = autocomplete_suggestions_api(request)
        data = response.data

        # Should return empty suggestions
        self.assertEqual(len(data["suggestions"]), 0)

    def test_autocomplete_case_insensitive(self):
        """Test that autocomplete is case insensitive"""
        # Test lowercase
        request = self.factory.get("/api/search/autocomplete/", {"q": "δημο"})
        request.user = self.user

        response = autocomplete_suggestions_api(request)
        data = response.data

        # Should match ΔΗΜΟΣ even with lowercase query
        self.assertTrue(any("ΔΗΜΟΣ" in s["text"] for s in data["suggestions"]))


class TestSearchPerformance(TestCase):
    """Performance-related tests for search functions"""

    @patch("api.views.search.entity_search.SearchService")
    def test_entities_faster_than_documents(self, mock_search_service):
        """
        Test that entity search is called first and completes before document search
        This is a conceptual test - in real SSE, entities arrive first
        """
        mock_service = MagicMock()
        mock_search_service.return_value = mock_service
        mock_service.search_organizations.return_value = []
        mock_service.search_signers.return_value = []
        mock_service.search_units.return_value = []
        mock_service.search_companies.return_value = []
        mock_service.search_company_persons.return_value = []

        # Call entity search
        entity_results = get_entities_fast("test", limit=5)

        # Verify it returns results structure
        self.assertIsNotNone(entity_results)
        self.assertEqual(entity_results["type"], "entities")

        # This demonstrates entities can be processed independently of documents
        # In the SSE stream, these arrive first
