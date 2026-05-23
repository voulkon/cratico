# import pytest
# from gemi.src.client import GemiDataClient
# import os
# # Skip all tests in this module if no API key is available
# pytestmark = pytest.mark.skipif(
#     not os.getenv("GEMI_API_KEY"),
#     reason="GEMI_API_KEY environment variable not set"
# )

# @pytest.fixture
# def client(api_credentials):
#     """Create a real client instance with API key."""
#     return GemiDataClient(api_key=api_credentials["api_key"])

# def test_reference_data_retrieval(client):
#     """Test retrieving reference data from the API."""
#     # Test getting prefectures
#     prefectures = client.reference.get_prefectures()
#     assert len(prefectures) > 0
#     assert hasattr(prefectures[0], "id")
#     assert hasattr(prefectures[0], "name")

#     # Test getting local offices
#     local_offices = client.reference.get_local_offices()
#     assert len(local_offices) > 0

# def test_company_search(client):
#     """Test searching for companies."""
#     # Use a known company name or a common term that will return results
#     # You might need to adjust this based on your API's data
#     search_results = client.companies.search_companies(name="ALPHA")
#     assert len(search_results) > 0

#     # Check response structure
#     company = search_results[0]
#     assert hasattr(company, "gemh_number")
#     assert hasattr(company, "name")

# def test_company_detail(client):
#     """Test retrieving company details."""
#     # First search for a company to get its GEMH number
#     search_results = client.companies.search_companies(name="ALPHA")

#     if len(search_results) == 0:
#         pytest.skip("No companies found to test company details")

#     # Use the first result's GEMH number to fetch details
#     gemh_number = search_results[0].gemh_number
#     company_detail = client.companies.get_company(gemh_number)

#     # Verify we got detailed information
#     assert company_detail.gemh_number == gemh_number
#     assert hasattr(company_detail, "name")
#     # Check for some detailed fields that should be present
#     assert hasattr(company_detail, "status")
