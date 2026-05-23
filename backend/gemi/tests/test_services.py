# import pytest
# from unittest.mock import MagicMock
# from gemi.src.services import CompaniesService, ReferenceDataService

# @pytest.fixture
# def mock_base_client():
#     class DummyClient:
#         def get(self, endpoint, params=None):
#             return {
#                 "results":
#                 [
#                     {"gemhNumber": "123", "name": "Test", "afm": "999", "status": "ACTIVE"}
#                     ]
#                 }
#     return DummyClient()

# @pytest.fixture
# def mock_reference_data():
#     """Generate mock reference data arrays for testing."""
#     return [
#         {"id": 1, "name": "Item 1"},
#         {"id": 2, "name": "Item 2"}
#     ]

# def test_search_companies(
#     mock_base_client,
#     dummy_ar_gemi,
#     dummy_afm,
#     dummy_company_name,
#     ):
#     service = CompaniesService(mock_base_client)
#     results = service.search_companies(name=dummy_company_name)
#     assert len(results) == 1
#     assert results[0].name == "Test"

# def test_get_company(
#     mock_base_client,
#     dummy_ar_gemi,
#     dummy_afm,
#     dummy_company_name,
#     ):
#     # Simulate a single company detail dict
#     mock_base_client.get = lambda endpoint: {
#         "gemhNumber": dummy_ar_gemi,
#         "name": dummy_company_name,
#         "afm": dummy_afm,
#         "status": "ACTIVE",
#         "distinctiveTitle": None,
#         "gemiOffice": None, "registrationDate": None,
#         "publicityDocuments": [], "organDecisions": []
#     }
#     service = CompaniesService(mock_base_client)
#     company = service.get_company("123")
#     assert company.gemh_number == "123"
#     assert company.name == "Test"

# def test_get_local_offices(mock_base_client, mock_reference_data):
#     """Test retrieving local offices."""
#     mock_base_client.get = lambda endpoint: mock_reference_data
#     service = ReferenceDataService(mock_base_client)

#     offices = service.get_local_offices()
#     assert len(offices) == 2
#     assert offices[0].id == 1
#     assert offices[0].name == "Item 1"

# def test_get_prefectures(mock_base_client, mock_reference_data):
#     """Test retrieving prefectures."""
#     mock_base_client.get = lambda endpoint: mock_reference_data
#     service = ReferenceDataService(mock_base_client)

#     prefectures = service.get_prefectures()
#     assert len(prefectures) == 2
#     assert prefectures[1].id == 2
#     assert prefectures[1].name == "Item 2"

# # Add similar tests for other reference data methods
# def test_get_legal_forms(mock_base_client, mock_reference_data):
#     """Test retrieving legal forms."""
#     mock_base_client.get = lambda endpoint: mock_reference_data
#     service = ReferenceDataService(mock_base_client)

#     forms = service.get_legal_forms()
#     assert len(forms) == 2
#     assert forms[0].id == 1
