"""Regression tests for SanitizedJSONParser.

Credentials and tokens must arrive exactly as the client sent them; HTML
sanitization is only appropriate for free-text/content fields.
"""

import io
import json

from api.parsers import SanitizedJSONParser


def _parse(payload):
    parser = SanitizedJSONParser()
    stream = io.BytesIO(json.dumps(payload).encode("utf-8"))
    return parser.parse(stream)


def test_password_is_not_sanitized():
    payload = {"email": "a@b.com", "password": 'p&ss<w"d>'}
    assert _parse(payload)["password"] == 'p&ss<w"d>'


def test_sensitive_fields_are_not_sanitized():
    payload = {
        "token": "a&b",
        "new_password": "a&b",
        "old_password": "a&b",
        "api_key": "a&b",
        "secret": "a&b",
        "otp": "a&b",
    }
    assert _parse(payload) == payload


def test_content_fields_are_still_sanitized():
    result = _parse({"title": "Tom & Jerry", "nested": {"body": "a&b"}})
    assert result["title"] == "Tom &amp; Jerry"
    assert result["nested"]["body"] == "a&amp;b"


def test_non_string_values_pass_through():
    payload = {"count": 3, "enabled": True, "missing": None}
    assert _parse(payload) == payload
