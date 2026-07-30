"""
Tests for the regex-strip preprocessor.
"""

from core.services.preprocessors.regex_strip import regex_strip


class TestRegexStripPreprocessor:
    """Unit tests for the regex-strip preprocessor."""

    # ── Default patterns ────────────────────────────────────────────

    def test_strips_diavgeia_header(self):
        text = "ΔΙΑΒΓΕΙΑ - Κάποιο κείμενο απόφασης"
        result = regex_strip(text)
        assert "ΔΙΑΒΓΕΙΑ" not in result
        assert "Κάποιο κείμενο απόφασης" in result

    def test_strips_diavgeia_with_em_dash(self):
        text = "ΔΙΑΒΓΕΙΑ — Περιεχόμενο εγγράφου"
        result = regex_strip(text)
        assert "ΔΙΑΒΓΕΙΑ" not in result
        assert "Περιεχόμενο εγγράφου" in result

    def test_strips_protocol_number(self):
        text = "Αριθμός Πρωτοκόλλου: 12345/2024  Σώμα κειμένου"
        result = regex_strip(text)
        assert "Αριθμός Πρωτοκόλλου" not in result
        assert "Σώμα κειμένου" in result

    def test_strips_issue_date(self):
        text = "Ημερομηνία έκδοσης: 15/01/2024  Κύριο περιεχόμενο"
        result = regex_strip(text)
        assert "Ημερομηνία έκδοσης" not in result
        assert "Κύριο περιεχόμενο" in result

    # ── Custom patterns ─────────────────────────────────────────────

    def test_custom_patterns(self):
        text = "SECRET-123: classified content here"
        result = regex_strip(text, params={"patterns": [r"SECRET-\d+:"]})
        assert "SECRET-123" not in result
        assert "classified content here" in result.strip()

    # ── Edge cases ──────────────────────────────────────────────────

    def test_empty_text(self):
        assert regex_strip("") == ""

    def test_none_params_uses_defaults(self):
        """``params=None`` does not crash; defaults are used."""
        text = "ΔΙΑΒΓΕΙΑ - απόφαση"
        result = regex_strip(text, params=None)
        assert "ΔΙΑΒΓΕΙΑ" not in result

    def test_empty_params_uses_defaults(self):
        text = "ΔΙΑΒΓΕΙΑ - απόφαση"
        result = regex_strip(text, params={})
        assert "ΔΙΑΒΓΕΙΑ" not in result

    def test_no_matches_returns_original(self):
        text = "Κανονικό κείμενο χωρίς πρότυπα"
        result = regex_strip(text)
        # Default patterns shouldn't match plain Greek text
        assert result.strip() == text.strip()

    def test_result_is_stripped(self):
        """The result should have leading/trailing whitespace stripped."""
        text = "ΔΙΑΒΓΕΙΑ -   some text with spaces   "
        result = regex_strip(text, params={"patterns": [r"ΔΙΑΒΓΕΙΑ\s*-\s*"]})
        assert result == "some text with spaces"
