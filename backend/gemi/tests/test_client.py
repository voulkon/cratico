# import pytest
# from unittest.mock import patch, MagicMock
# from gemi.src.client import GemiDataClient
# from gemi.src.services import CompaniesService, ReferenceDataService

# def test_client_initialization():
#     """Test that the client initializes properly with services."""
#     client = GemiDataClient(api_key="test-key")

#     # Check that the client has initialized the services correctly
#     assert isinstance(client.companies, CompaniesService)
#     assert isinstance(client.reference, ReferenceDataService)

#     # Check that the base client has the API key set
#     assert client._base_client.api_key == "test-key"

#     # Check default URL is set
#     assert "opendata-api.businessportal.gr" in client._base_client.base_url

# def test_client_custom_url():
#     """Test that the client accepts a custom base URL."""
#     custom_url = "https://custom-api.example.com"
#     client = GemiDataClient(api_key="test-key", base_url=custom_url)
#     assert client._base_client.base_url == custom_url
