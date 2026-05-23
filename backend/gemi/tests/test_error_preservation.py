# """Test to demonstrate improved error message preservation."""

# import pytest
# from unittest.mock import MagicMock
# from gemi.src.base_client import BaseAPIClient
# from gemi.src.exceptions import GemiNotFoundError, GemiAuthenticationError


# def test_api_error_message_preservation():
#     """Test that actual API error messages are preserved in custom exceptions."""
#     client = BaseAPIClient("dummy-key", "https://example.com")

#     # Mock a 404 response with detailed API error message
#     mock_response = MagicMock()
#     mock_response.status_code = 404
#     mock_response.json.return_value = {
#         "message": "Company with GEMI number '999999999' does not exist in our database",
#         "error_code": "COMPANY_NOT_FOUND",
#         "suggestion": "Please verify the GEMI number and try again"
#     }
#     mock_response.headers = {"Content-Type": "application/json"}

#     with pytest.raises(GemiNotFoundError) as exc_info:
#         client._handle_response_errors(mock_response)

#     error = exc_info.value

#     # Check that we preserve the original API message
#     assert "Company with GEMI number '999999999' does not exist" in str(error)
#     assert error.status_code == 404
#     assert error.response_data["error_code"] == "COMPANY_NOT_FOUND"
#     assert error.response_data["suggestion"] == "Please verify the GEMI number"

#     # Full error details are accessible
#     details = error.get_api_error_details()
#     assert details["status_code"] == 404
#     assert "COMPANY_NOT_FOUND" in str(details["response_data"])


# def test_api_error_with_simple_string_response():
#     """Test handling when API returns a simple string error."""
#     client = BaseAPIClient("dummy-key", "https://example.com")

#     mock_response = MagicMock()
#     mock_response.status_code = 403
#     mock_response.json.return_value = "Your API key expired 2 days ago, please renew"
#     mock_response.reason = "Forbidden"

#     with pytest.raises(GemiAuthenticationError) as exc_info:
#         client._handle_response_errors(mock_response)

#     error = exc_info.value

#     # Check that we include the actual API message
#     assert "Your API key expired 2 days ago" in str(error)
#     assert error.response_data == "Your API key expired 2 days ago, please renew"


# def test_fallback_to_http_reason():
#     """Test fallback when API doesn't provide structured error."""
#     client = BaseAPIClient("dummy-key", "https://example.com")

#     mock_response = MagicMock()
#     mock_response.status_code = 403
#     mock_response.json.side_effect = ValueError("Not JSON")  # Simulate non-JSON response
#     mock_response.reason = "Forbidden"

#     with pytest.raises(GemiAuthenticationError) as exc_info:
#         client._handle_response_errors(mock_response)

#     error = exc_info.value

#     # Should fall back to HTTP reason
#     assert "Forbidden" in str(error)
#     assert error.status_code == 403
