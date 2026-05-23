# import pytest
# from unittest.mock import patch, MagicMock
# from gemi.src.base_client import BaseAPIClient
# import requests

# def test_get_success(monkeypatch):
#     client = BaseAPIClient("dummy-key", "https://example.com")

#     mock_response = MagicMock()
#     mock_response.json.return_value = {"foo": "bar"}
#     mock_response.raise_for_status.return_value = None

#     with patch.object(client.session, "get", return_value=mock_response) as mock_get:
#         result = client.get("test-endpoint", params={"a": 1})
#         mock_get.assert_called_once()
#         assert result == {"foo": "bar"}

# def test_get_http_error(monkeypatch):
#     """Test handling of HTTP errors in the get method."""
#     client = BaseAPIClient("dummy-key", "https://example.com")

#     # Create a mock response that raises an exception when raise_for_status is called
#     mock_response = MagicMock()
#     mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("404 Client Error")

#     with patch.object(client.session, "get", return_value=mock_response):
#         with pytest.raises(requests.exceptions.HTTPError):
#             client.get("test-endpoint")

# def test_correct_url_formation(monkeypatch):
#     """Test that URLs are correctly formed with and without leading slashes."""
#     client = BaseAPIClient("dummy-key", "https://example.com")

#     mock_response = MagicMock()
#     mock_response.json.return_value = {}

#     with patch.object(client.session, "get", return_value=mock_response) as mock_get:
#         client.get("endpoint")  # no leading slash
#         mock_get.assert_called_with(
#             "https://example.com/endpoint",
#             params=None,
#             timeout=30
#         )

#         client.get("/endpoint")  # with leading slash
#         mock_get.assert_called_with(
#             "https://example.com/endpoint",
#             params=None,
#             timeout=30
#         )
