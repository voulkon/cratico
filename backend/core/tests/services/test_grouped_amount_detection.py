"""
Unit tests for cents-based monetary amount detection.
"""

from decimal import Decimal

import pytest
from core.services.grouped_amount_detection import (
    extract_grouped_amounts,
    parse_grouped_amount,
    verify_amounts_against_grouped,
)


class TestParseGroupedAmount:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            # Greek format (comma = decimal)
            ("1.234.567,89", Decimal("1234567.89")),
            ("30.000,00", Decimal("30000.00")),
            ("30000,00", Decimal("30000.00")),
            ("100.000,50", Decimal("100000.50")),
            ("500,00", Decimal("500.00")),
            # English format (dot = decimal)
            ("1,234,567.89", Decimal("1234567.89")),
            ("30,000.00", Decimal("30000.00")),
        ],
    )
    def test_parse(self, raw, expected):
        assert parse_grouped_amount(raw) == expected

    def test_parse_invalid(self):
        assert parse_grouped_amount("") is None
        assert parse_grouped_amount("abc") is None


class TestExtractCentsAmounts:
    def test_extracts_all_with_cents(self):
        text = "Δαπάνη 24.193,55 € πλέον ΦΠΑ 5.806,45 €, σύνολο 30.000,00 €."
        result = extract_grouped_amounts(text)
        amounts = [g.amount for g in result]
        assert Decimal("24193.55") in amounts
        assert Decimal("5806.45") in amounts
        assert Decimal("30000.00") in amounts
        assert len(result) == 3

    def test_extracts_bare_with_cents(self):
        """Numbers without thousands grouping but WITH cents are detected."""
        text = "Ποσό 30000,00 ευρώ."
        result = extract_grouped_amounts(text)
        assert len(result) == 1
        assert result[0].amount == Decimal("30000.00")

    def test_extracts_round_amount_with_cents(self):
        """Round amounts with ,00 are detected — official docs always include cents."""
        text = "Εγκρίνεται δαπάνη 1.000,00 €."
        result = extract_grouped_amounts(text)
        assert len(result) == 1
        assert result[0].amount == Decimal("1000.00")

    def test_rejects_bare_integers(self):
        """Numbers without cents are NOT monetary amounts in this detector."""
        assert extract_grouped_amounts("Ποσό 500 ευρώ.") == []
        assert extract_grouped_amounts("Ποσό 30000.") == []

    def test_rejects_grouped_without_cents(self):
        """1.500 (no ,00) is ambiguous — could be 1500 or 1.5 — skipped."""
        assert extract_grouped_amounts("ποσό 1.500") == []

    def test_does_not_match_dates(self):
        text = "Αριθμός πρωτοκόλλου 12345, ημερομηνία 12/05/2024."
        result = extract_grouped_amounts(text)
        assert result == []

    def test_does_not_match_sentence_end_number_without_cents(self):
        """1.000.000. without ,00 is not matched."""
        text = "το ποσό 1.000.000."
        result = extract_grouped_amounts(text)
        assert result == []

    def test_matches_sentence_end_with_cents(self):
        text = "το ποσό 1.000.000,00."
        result = extract_grouped_amounts(text)
        assert len(result) == 1
        assert result[0].amount == Decimal("1000000.00")

    def test_keyword_proximity(self):
        text = "βλέπε σελίδα 1.500,00. Εγκρίνεται δαπάνη 85.000,00 €."
        result = extract_grouped_amounts(text)
        # "85.000,00" is near "δαπάνη"
        big = [g for g in result if g.near_keyword]
        assert len(big) == 1
        assert big[0].amount == Decimal("85000.00")


class TestVerifyAgainstGrouped:
    def test_exact_match(self):
        result = verify_amounts_against_grouped(
            "ποσό 30.000,00 €", [Decimal("30000.00")]
        )
        assert result.all_found
        assert not result.any_clone

    def test_clone_match_x100(self):
        result = verify_amounts_against_grouped(
            "ποσό 3.000.000,00 €", [Decimal("30000.00")]
        )
        assert not result.all_found
        assert result.any_clone
        assert result.matches[0].clone_factor == Decimal("100")

    def test_not_found(self):
        result = verify_amounts_against_grouped(
            "χωρίς ποσά", [Decimal("30000.00")]
        )
        assert not result.all_found
        assert not result.any_clone

    def test_bare_amounts_ignored(self):
        """Numbers without cents are ignored — only ,00 amounts count."""
        result = verify_amounts_against_grouped(
            "πληρωμή 500 ευρώ για υπηρεσίες", [Decimal("500")]
        )
        # 500 has no cents → not detected
        assert not result.all_found
        assert not result.any_clone

    def test_primary_prefers_keyword_adjacent(self):
        result = verify_amounts_against_grouped(
            "βλέπε σελίδα 1.500,00. Εγκρίνεται δαπάνη 85.000,00 €.",
            [Decimal("85000.00")],
        )
        assert result.primary_grouped_amount == Decimal("85000.00")
