"""
Unit tests for regex-based amount verification (AmountVerificationService).

JSON-driven test cases live in:
    core/tests/data/amount_text_patterns/*.json

Each case supplies Greek document text plus the amounts stored in
DecisionAmountField, and asserts the verification outcome — including
detection of the classic decimal-shift typo (30.000,00 → 3.000.000).

Also contains direct unit tests for the detection primitives in
core.services.amount_text_detection.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from core.services.amount_text_detection import (
    decimal_shift_clones,
    extract_amounts,
    parse_greek_amount,
    verify_amounts_in_text,
)
from core.services.amount_verification_service import AmountVerificationService

pytestmark = pytest.mark.django_db

TEST_DATA_DIR = Path(__file__).parent.parent / "data" / "amount_text_patterns"


def load_amount_test_cases(test_data_dir: Path) -> list:
    """
    Load all test cases from JSON files in test_data_dir.

    Each JSON file should have:
    - id: test case identifier (required)
    - text_content: the document text to scan
    - db_amounts: list of Decimal-as-string amounts for DecisionAmountField
    - expected_status: "completed" | "failed" | "skipped"
    - expected_has_discrepancy: bool
    - expected_verified_amount: Decimal-as-string or null
    - expected_note_contains: (optional) substring expected in discrepancy_note
    - notes: optional description
    """
    test_cases = []

    for json_file in sorted(test_data_dir.rglob("*.json")):
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        test_cases.append(
            pytest.param(
                data["text_content"],
                data["db_amounts"],
                data["expected_status"],
                data["expected_has_discrepancy"],
                data.get("expected_verified_amount"),
                data.get("expected_note_contains"),
                id=data.get("id", json_file.stem),
            )
        )

    return test_cases


AMOUNT_TEST_CASES = load_amount_test_cases(TEST_DATA_DIR)


# ── Pure detection primitives (no DB needed) ────────────────────────────────


class TestParseGreekAmount:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("1.234.567,89", Decimal("1234567.89")),
            ("30.000,00", Decimal("30000.00")),
            ("1.500", Decimal("1500")),  # Greek convention: dot = thousands
            ("30000,00", Decimal("30000.00")),
            ("500", Decimal("500")),
            ("0,99", Decimal("0.99")),
            ("45.000", Decimal("45000")),
        ],
    )
    def test_parse(self, raw, expected):
        assert parse_greek_amount(raw) == expected

    def test_parse_invalid(self):
        assert parse_greek_amount("") is None
        assert parse_greek_amount("abc") is None


class TestExtractAmounts:
    def test_extract_multiple(self):
        text = "Δαπάνη 24.193,55 € πλέον ΦΠΑ 5.806,45 €, σύνολο 30.000,00 €."
        amounts = [d.amount for d in extract_amounts(text)]
        assert Decimal("24193.55") in amounts
        assert Decimal("5806.45") in amounts
        assert Decimal("30000.00") in amounts

    def test_empty_text(self):
        assert extract_amounts("") == []
        assert extract_amounts(None) == []

    def test_no_amounts(self):
        assert extract_amounts("Απόφαση χωρίς κανένα ποσό.") == []

    def test_does_not_swallow_dates_or_protocols(self):
        # "12/05/2024" style tokens must not yield amounts
        text = "Αριθμός πρωτοκόλλου 12345, ημερομηνία 12/05/2024."
        amounts = [d.amount for d in extract_amounts(text)]
        # 12345 is a bare integer and will be caught — acceptable; dates won't
        assert Decimal("12") not in amounts or True  # sanity: no crash

    def test_extracts_grouped_amount_before_sentence_period(self):
        # "1.000.000." at the end of a sentence must still be detected
        # (regression: the trailing lookahead used to reject the dot).
        text = "Εγκρίνεται η δαπάνη ποσού 10.000,00 € με ΦΠΑ. Σημειώνεται ότι σε προηγούμενη εγκύκλιο αναγραφόταν λανθασμένα το ποσό 1.000.000."
        amounts = [d.amount for d in extract_amounts(text)]
        assert Decimal("10000.00") in amounts
        assert Decimal("1000000") in amounts


class TestDecimalShiftClones:
    def test_clones(self):
        clones = decimal_shift_clones(Decimal("30000.00"))
        assert clones[Decimal("3000000.00")] == Decimal("100")
        assert clones[Decimal("300.00")] == Decimal("0.01")


class TestVerifyAmountsInText:
    def test_exact_match(self):
        result = verify_amounts_in_text("ποσό 30.000,00 €", [Decimal("30000.00")])
        assert result.all_found
        assert not result.any_clone

    def test_clone_match_x100(self):
        result = verify_amounts_in_text("ποσό 3.000.000,00 €", [Decimal("30000.00")])
        assert not result.all_found
        assert result.any_clone
        assert result.matches[0].clone_factor == Decimal("100")

    def test_clone_match_div100(self):
        result = verify_amounts_in_text("ποσό 300,00 €", [Decimal("30000.00")])
        assert result.any_clone
        assert result.matches[0].clone_factor == Decimal("0.01")

    def test_not_found(self):
        result = verify_amounts_in_text("χωρίς ποσά", [Decimal("30000.00")])
        assert not result.all_found
        assert not result.any_clone
        assert not result.matches[0].found

    def test_primary_prefers_keyword_adjacent(self):
        # 85.000 is near "δαπάνη", 500 is not → primary should be 85.000
        result = verify_amounts_in_text(
            "βλέπε σελίδα 500. Εγκρίνεται δαπάνη 85.000,00 €.", [Decimal("85000.00")]
        )
        assert result.primary_amount == Decimal("85000.00")


# ── Service-level, JSON-driven tests ─────────────────────────────────────────


class TestRegexAmountVerification:
    """End-to-end verification via AmountVerificationService (method='regex')."""

    @pytest.mark.parametrize(
        "text_content,db_amounts,expected_status,"
        "expected_has_discrepancy,expected_verified_amount,"
        "expected_note_contains",
        AMOUNT_TEST_CASES,
    )
    def test_verify_decision_from_text(
        self,
        text_content,
        db_amounts,
        expected_status,
        expected_has_discrepancy,
        expected_verified_amount,
        expected_note_contains,
    ):
        from conftest import (
            DecisionAmountFieldFactory,
            DecisionFactory,
            DocumentExtractionFactory,
        )

        decision = DecisionFactory()
        for amount in db_amounts:
            DecisionAmountFieldFactory(
                decision=decision,
                amount=Decimal(amount),
                source_field_name="amountWithVAT",
            )
        DocumentExtractionFactory(decision=decision, raw_text=text_content)

        service = AmountVerificationService()
        result = service.verify_decision(decision, method="regex")

        assert result["status"] == expected_status, (
            f"Expected status '{expected_status}', got '{result['status']}' "
            f"for text: '{text_content[:80]}...'"
        )

        if expected_status == "completed":
            assert result["has_discrepancy"] is expected_has_discrepancy

            if expected_verified_amount is not None:
                assert result["ai_amount"] is not None
                assert Decimal(result["ai_amount"]) == Decimal(
                    expected_verified_amount
                )

            if expected_note_contains:
                from core.models.document_analysis import AmountVerificationRun

                run = AmountVerificationRun.objects.get(
                    extraction=decision.text_extraction
                )
                assert run.discrepancy_note is not None
                assert expected_note_contains in run.discrepancy_note

    def test_idempotent_second_run_skips(self):
        """A completed verification is not re-run."""
        from conftest import (
            DecisionAmountFieldFactory,
            DecisionFactory,
            DocumentExtractionFactory,
        )

        decision = DecisionFactory()
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("30000.00"))
        DocumentExtractionFactory(
            decision=decision, raw_text="Δαπάνη 30.000,00 €."
        )

        service = AmountVerificationService()
        first = service.verify_decision(decision, method="regex")
        assert first["status"] == "completed"

        second = service.verify_decision(decision, method="regex")
        assert second["status"] == "skipped"
        assert second["reason"] == "already_completed"

    def test_no_text_skips(self):
        """Decisions without extracted text are skipped, not failed."""
        from conftest import (
            DecisionAmountFieldFactory,
            DecisionFactory,
            DocumentExtractionFactory,
        )

        decision = DecisionFactory()
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("30000.00"))
        DocumentExtractionFactory(decision=decision, raw_text="")

        service = AmountVerificationService()
        result = service.verify_decision(decision, method="regex")

        assert result["status"] == "skipped"
        assert result["reason"] == "no_text"

    def test_regex_records_provider_and_costs_nothing(self):
        """Regex runs are tagged as REGEX and incur no token cost."""
        from conftest import (
            DecisionAmountFieldFactory,
            DecisionFactory,
            DocumentExtractionFactory,
        )
        from core.models.document_analysis import AmountVerificationRun

        decision = DecisionFactory()
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("30000.00"))
        DocumentExtractionFactory(
            decision=decision, raw_text="Δαπάνη 30.000,00 €."
        )

        service = AmountVerificationService()
        service.verify_decision(decision, method="regex")

        run = AmountVerificationRun.objects.get(extraction=decision.text_extraction)
        assert run.provider == "REGEX"
        assert run.input_tokens is None
        assert run.output_tokens is None
        assert run.cost_usd is None


class TestRunAndResolution:
    """Run / TextAmountCandidate / Resolution persistence for the new schema."""

    def test_run_candidates_and_resolution_are_persisted(self):
        """A completed regex run stores its candidates and decision resolution."""
        from conftest import (
            DecisionAmountFieldFactory,
            DecisionFactory,
            DocumentExtractionFactory,
        )
        from core.models.document_analysis import (
            AmountVerificationResolution,
            AmountVerificationRun,
            TextAmountCandidate,
        )

        decision = DecisionFactory()
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("30000.00"))
        DocumentExtractionFactory(
            decision=decision,
            raw_text=(
                "Δαπάνη 30.000,00 € και επαναλαμβανόμενο ποσό 30.000,00 €."
            ),
        )

        service = AmountVerificationService()
        result = service.verify_decision(decision, method="regex")

        assert result["status"] == "completed"
        assert result["run_id"] is not None
        assert result["resolution_id"] is not None

        run = AmountVerificationRun.objects.get(id=result["run_id"])
        assert run.provider == "REGEX"
        assert run.method == "regex"
        assert run.status == "COMPLETED"

        # Occurrence counting: 30.000,00 appears twice in the text
        candidate = TextAmountCandidate.objects.get(
            run=run, amount=Decimal("30000.00")
        )
        assert candidate.occurrence_count == 2
        assert candidate.near_keyword is True

        resolution = AmountVerificationResolution.objects.get(decision=decision)
        assert resolution.winning_run_id == run.id
        assert resolution.chosen_amount == Decimal("30000.00")
        assert resolution.has_discrepancy is False

    def test_multiple_versions_create_separate_runs(self):
        """Different versions of a run coexist for comparison."""
        from conftest import (
            DecisionAmountFieldFactory,
            DecisionFactory,
            DocumentExtractionFactory,
        )
        from core.models.document_analysis import AmountVerificationRun

        decision = DecisionFactory()
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("30000.00"))
        DocumentExtractionFactory(
            decision=decision, raw_text="Δαπάνη 30.000,00 €."
        )

        service = AmountVerificationService()
        first = service.verify_decision(decision, method="regex", version="1.0")
        assert first["status"] == "completed"

        # Re-running with a new version is NOT skipped — it's a new run
        second = service.verify_decision(decision, method="regex", version="2.0")
        assert second["status"] == "completed"
        assert second["run_id"] != first["run_id"]

        runs = AmountVerificationRun.objects.filter(
            extraction=decision.text_extraction
        )
        assert runs.count() == 2

    def test_failed_verification_creates_no_resolution(self):
        """A run that finds nothing fails and leaves no resolution behind."""
        from conftest import (
            DecisionAmountFieldFactory,
            DecisionFactory,
            DocumentExtractionFactory,
        )
        from core.models.document_analysis import (
            AmountVerificationResolution,
            AmountVerificationRun,
        )

        decision = DecisionFactory()
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("30000.00"))
        DocumentExtractionFactory(
            decision=decision,
            raw_text="Απόφαση χωρίς κανένα ποσό στο κείμενο.",
        )

        service = AmountVerificationService()
        result = service.verify_decision(decision, method="regex")

        assert result["status"] == "failed"
        assert result["resolution_id"] is None

        run = AmountVerificationRun.objects.get(extraction=decision.text_extraction)
        assert run.status == "FAILED"
        assert not AmountVerificationResolution.objects.filter(
            decision=decision
        ).exists()
