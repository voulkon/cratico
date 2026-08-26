"""
Tests for Greek Tax Number (ΑΦΜ) detection.

Covers:
- The core checksum algorithm (``is_valid_afm`` / ``normalize_afm``).
- The ``AfmProcess`` detection over realistic decision text.
- Registration + persistence through the generic ``TextProcessService``.
"""

import pytest

from core.services.text_processes.afm import (
    AfmProcess,
    is_valid_afm,
    normalize_afm,
)

pytestmark = pytest.mark.django_db

# Real-world AFMs — all pass the checksum.
VALID_AFMS = ["167375970", "800186770", "998875925"]


def _compute_check(first8: str) -> str:
    """Compute the check digit for the first 8 digits of an AFM."""
    weights = (256, 128, 64, 32, 16, 8, 4, 2)
    total = sum(int(d) * w for d, w in zip(first8, weights))
    return str((total % 11) % 10)


# ── Core checksum mechanism ─────────────────────────────────────────────────


class TestAfmChecksum:
    def test_valid_afms_pass(self):
        for afm in VALID_AFMS:
            assert is_valid_afm(afm), afm

    def test_wrong_check_digit_rejected(self):
        assert not is_valid_afm("167375971")  # flip check digit 0 → 1
        assert not is_valid_afm("800186771")
        assert not is_valid_afm("998875926")

    def test_wrong_length_rejected(self):
        assert not is_valid_afm("16737597")    # 8 digits
        assert not is_valid_afm("1673759700")  # 10 digits
        assert not is_valid_afm("")

    def test_non_numeric_rejected(self):
        assert not is_valid_afm("16737A970")
        assert not is_valid_afm("16737597 ")  # trailing space still 8 digits after strip
        assert not is_valid_afm(None)

    def test_all_zeros_rejected(self):
        # 000000000 passes the arithmetic but is not a real AFM.
        assert not is_valid_afm("000000000")

    def test_int_input(self):
        assert is_valid_afm(167375970)

    def test_el_prefix(self):
        assert is_valid_afm("EL167375970")
        assert is_valid_afm("el167375970")

    def test_formatting_characters(self):
        assert is_valid_afm("167 375 970")
        assert is_valid_afm("167-375-970")
        assert is_valid_afm("167.375.970")

    def test_normalize_afm(self):
        assert normalize_afm(" EL167375970 ") == "167375970"
        assert normalize_afm(167375970) == "167375970"
        assert normalize_afm("12-345-6789") == "123456789"
        assert normalize_afm("abc") is None
        assert normalize_afm(None) is None

    def test_generated_afms_round_trip(self):
        for first8 in ["12345678", "11111111", "99999999", "09000004", "08000004"]:
            afm = first8 + _compute_check(first8)
            assert is_valid_afm(afm), afm

    def test_single_digit_mutation_detected(self):
        """Mutating any single digit must break the checksum."""
        base = "167375970"
        for i in range(9):
            mutated = list(base)
            mutated[i] = str((int(mutated[i]) + 1) % 10)
            assert not is_valid_afm("".join(mutated)), f"pos {i} not detected"


# ── Detection over decision text ────────────────────────────────────────────


class TestAfmProcess:
    def test_detects_afm_near_keyword(self):
        text = (
            "ΥΚΟΥΛΙΘΡΑ ΝΙΚΟΛΑΟΣ, Συνεργείο Αυτοκινήτων,\n"
            "με έδρα την Ατσική Λήμνου, Τ.Κ.81401, τηλ. 6982077835, "
            "ΑΦΜ 167375970"
        )
        result = AfmProcess().detect(text)
        assert result.success
        assert len(result.spans) == 1
        span = result.spans[0]
        assert span.label == "afm"
        assert span.value["afm"] == "167375970"
        assert span.value["near_keyword"] is True
        assert text[span.start : span.end] == "167375970"

    def test_detects_afm_in_sentence(self):
        text = (
            "ΑΦΟΙ ΜΑΡΗ ΤΟΥ ΧΡΗΣΤΟΥ ΟΕ με ΑΦΜ 800186770 και ΔΟΥ ΜΥΤΙΛΗΝΗΣ, την\n"
            "προμήθεια των κατωτέρω αγαθών:"
        )
        result = AfmProcess().detect(text)
        assert [s.value["afm"] for s in result.spans] == ["800186770"]

    def test_detects_afm_across_newline(self):
        text = (
            "Αναθέτουμε απευθείας στον ΖΑΪΝΤΟΥΔΗΣ ΚΑΙ ΣΙΑ Ο.Ε. με ΑΦΜ "
            "998875925 και ΔΟΥ ΙΩΝΙΑΣ ΘΕΣΣΑΛΟΝΙΚΗΣ\n"
            ", την προμήθεια των κατωτέρω αγαθώ"
        )
        result = AfmProcess().detect(text)
        assert [s.value["afm"] for s in result.spans] == ["998875925"]

    def test_no_false_positive_on_phone_number(self):
        # 10-digit phone number must not produce a 9-digit candidate.
        result = AfmProcess().detect("τηλ. 6982077835")
        assert result.spans == []

    def test_invalid_checksum_number_not_detected(self):
        # 9 digits but fails the checksum → no span.
        result = AfmProcess().detect("ΑΦΜ 167375971")
        assert result.spans == []

    def test_valid_afm_without_keyword_still_detected(self):
        # Checksum is the core signal; the keyword is only a bonus.
        result = AfmProcess().detect("Αριθμός 090000045")
        # Only assert if it passes checksum; 090000045 → verify explicitly.
        assert is_valid_afm("090000045")
        spans = [s for s in result.spans if s.value["afm"] == "090000045"]
        assert len(spans) == 1
        assert spans[0].value["near_keyword"] is False

    def test_require_keyword_filters(self):
        # Pad the second number far enough away that the "ΑΦΜ" keyword falls
        # outside the default proximity window.
        text = "ΑΦΜ 167375970 " + ("πληροφορίες " * 10) + "090000045"
        assert is_valid_afm("090000045")

        all_spans = AfmProcess().detect(text).spans
        assert {s.value["afm"] for s in all_spans} == {"167375970", "090000045"}
        assert all_spans[1].value["near_keyword"] is False

        strict = AfmProcess().detect(text, require_keyword=True).spans
        assert [s.value["afm"] for s in strict] == ["167375970"]

    def test_empty_text(self):
        result = AfmProcess().detect("")
        assert result.success
        assert result.spans == []


# ── Annotation mechanism (generic service) ──────────────────────────────────


class TestAfmAnnotation:
    def test_registered_in_registry(self):
        from core.services.text_process_service import get_available_processes

        slugs = {p["slug"] for p in get_available_processes()}
        assert "afm" in slugs

    def test_run_process_persists_span(self):
        from conftest import DecisionFactory, DocumentExtractionFactory
        from core.models.document_analysis import TextSpan

        decision = DecisionFactory()
        extraction = DocumentExtractionFactory(
            decision=decision,
            raw_text="... ΑΦΜ 167375970 ...",
        )

        from core.services.text_process_service import TextProcessService

        run = TextProcessService().run_process(extraction, "afm")
        assert run.status == "COMPLETED"
        assert run.process == "afm"
        assert run.provider == "REGEX"

        spans = TextSpan.objects.filter(run=run)
        assert spans.count() == 1
        span = spans.first()
        assert span.label == "afm"
        assert span.value["afm"] == "167375970"
        assert span.value["near_keyword"] is True
        assert extraction.raw_text[span.start : span.end] == "167375970"
