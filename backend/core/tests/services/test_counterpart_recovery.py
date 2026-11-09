"""
Counterpart recovery regression tests.

The canonical case is decision ``6ΧΩΜ469ΗΣΥ-ΒΗ4``: Diavgeia recorded the
issuing organization's own VAT number (``090064864``) as the counterpart,
while the document names the real contractor ``899972873``.  Recovery must
repoint the SAME relationship row, preserve the awardAmount link, archive the
old state in ``CounterpartRecoveryAttempt``, hide the self-counterpart warning,
and never recreate the self row on re-import.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from core.models.ai_interaction_log import AIInteractionLog
from core.models.counterpart_recovery import (
    CounterpartRecoveryAttempt,
    RecoveryStatus,
)
from core.models.entities import AFMEntity, DecisionEntityRelationship
from core.services.counterpart_recovery_service import CounterpartRecoveryService
from core.services.financial_calculation_service import FinancialCalculationService
from core.services.non_monetary_value_guard import collect_self_counterparts
from conftest import (
    AFMEntityFactory,
    DecisionAmountFieldFactory,
    DecisionEntityRelationshipFactory,
    DecisionFactory,
    DocumentExtractionFactory,
    OrganizationFactory,
)

pytestmark = pytest.mark.django_db

FIXTURE = Path(__file__).parent.parent / "data" / "decisions" / "6ΧΩΜ469ΗΣΥ-ΒΗ4.json"

SELF_AFM = "090064864"
REAL_AFM = "899972873"

OCR_TEXT = (
    "ΕΛΛΗΝΙΚΗ ΔΗΜΟΚΡΑΤΙΑ — ΙΦΕΤ Μ.Α.Ε.\n"
    "Ο προμηθευτής της υπηρεσίας, με ΑΦΜ 899 972 873, "
    "θα παράσχει συμβουλευτικές υπηρεσίες ISO.\n"
    "Η συνολική αξία της ανάθεσης ανέρχεται σε 30.000,00 ευρώ.\n"
    "Στοιχεία αναδόχου: ΑΦΜ 899 972 873, ΔΟΥ Αθηνών.\n"
)


def _seed_decision(*, with_target_entity: bool = True):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    org = OrganizationFactory(
        vat_number=SELF_AFM,
        label="ΙΝΣΤΙΤΟΥΤΟ ΦΑΡΜΑΚΕΥΤΙΚΗΣ ΕΡΕΥΝΑΣ ΚΑΙ ΤΕΧΝΟΛΟΓΙΑΣ Μ.Α.Ε.",
    )
    decision = DecisionFactory(
        ada=payload["ada"],
        organization=org,
        subject=payload["subject"],
        extra_field_values_json=payload["extraFieldValues"],
    )

    self_entity = AFMEntityFactory(
        afm=SELF_AFM,
        name="ΙΝΣΤΙΤΟΥΤΟ ΦΑΡΜΑΚΕΥΤΙΚΗΣ ΕΡΕΥΝΑΣ ΚΑΙ ΤΕΧΝΟΛΟΓΙΑΣ Μ.Α.Ε.",
    )
    relationship = DecisionEntityRelationshipFactory(
        decision=decision,
        entity=self_entity,
        role="person",
        parent_key_path="person[0]",
        source_field_name="person",
        raw_context={"afm": SELF_AFM, "afmType": "EL"},
        confidence_score=1.0,
    )
    amount = DecisionAmountFieldFactory(
        decision=decision,
        parent_key_path="",
        source_field_name="awardAmount",
        amount=Decimal("30000.00"),
        associated_relationship=relationship,
    )

    if with_target_entity:
        # Known entity + multiple appearances boosts the regex score enough to
        # auto-apply without the AI.
        AFMEntityFactory(
            afm=REAL_AFM,
            name="ΠΡΑΓΜΑΤΙΚΟΣ ΑΝΑΔΟΧΟΣ Α.Ε.",
            total_appearances=3,
        )

    extraction = DocumentExtractionFactory(
        decision=decision,
        raw_text=OCR_TEXT,
        extraction_provider="TESSERACT",
        is_scanned_document=True,
        character_count=len(OCR_TEXT),
        ocr_applied=True,
        ocr_confidence=0.91,
        ocr_metadata={"provider": "TESSERACT", "dpi": 300, "lang": "ell+eng"},
    )

    return decision, relationship, amount, extraction


class TestCounterpartRecovery:
    def test_recovers_in_place(self):
        decision, relationship, amount, extraction = _seed_decision()

        result = CounterpartRecoveryService().recover_decision(
            decision, force=True, apply=True, allow_ai=False
        )

        assert result["status"] == "recovered"
        relationship.refresh_from_db()
        amount.refresh_from_db()

        assert relationship.entity.afm == REAL_AFM
        assert relationship.is_inferred is True
        assert relationship.metadata_source == "OCR_AFM"
        assert relationship.source_extraction_id == extraction.id
        assert relationship.role == "person"
        assert relationship.parent_key_path == "person[0]"

        # The awardAmount row is untouched and still linked to the same row.
        assert amount.associated_relationship_id == relationship.id
        assert amount.amount == Decimal("30000.00")

        # No duplicate relationship row.
        assert (
            DecisionEntityRelationship.objects.filter(decision=decision).count()
            == 1
        )

        attempt = CounterpartRecoveryAttempt.objects.get(decision=decision)
        assert attempt.status == RecoveryStatus.APPLIED
        assert attempt.original_afm == SELF_AFM
        assert attempt.original_entity_name
        assert attempt.chosen_afm == REAL_AFM
        assert attempt.new_relationship_id == relationship.id
        assert attempt.span_text

        # The warning is suppressed once recovery is applied.
        assert collect_self_counterparts(decision) == set()

        new_entity = AFMEntity.objects.get(afm=REAL_AFM)
        old_entity = AFMEntity.objects.get(afm=SELF_AFM)
        financial = FinancialCalculationService()
        assert financial.get_entity_total_received(new_entity) == Decimal("30000.00")
        assert financial.get_entity_total_received(old_entity) == Decimal("0.00")

    def test_rerun_is_idempotent(self):
        decision, relationship, _, _ = _seed_decision()
        service = CounterpartRecoveryService()

        first = service.recover_decision(
            decision, force=True, apply=True, allow_ai=False
        )
        assert first["status"] == "recovered"

        second = service.recover_decision(
            decision, force=True, apply=True, allow_ai=False
        )
        assert second["status"] == "already_recovered"
        assert (
            DecisionEntityRelationship.objects.filter(decision=decision).count()
            == 1
        )

    def test_reimport_does_not_recreate_self_relationship(self):
        decision, _, _, _ = _seed_decision()
        CounterpartRecoveryService().recover_decision(
            decision, force=True, apply=True, allow_ai=False
        )

        from core.services.entity_amount_extraction_service import (
            EntityAmountExtractionService,
        )

        service = EntityAmountExtractionService()
        service._save_entities(
            decision,
            [
                {
                    "afm": SELF_AFM,
                    "name": "SELF",
                    "role": "person",
                    "parent_key_path": "person[0]",
                    "raw_context": {"afm": SELF_AFM, "afmType": "EL"},
                }
            ],
        )

        afms = set(
            DecisionEntityRelationship.objects.filter(decision=decision).values_list(
                "entity__afm", flat=True
            )
        )
        assert SELF_AFM not in afms
        assert REAL_AFM in afms

    def test_merges_into_existing_target_relationship(self):
        decision, self_rel, amount, _ = _seed_decision()
        target = AFMEntity.objects.get(afm=REAL_AFM)
        existing = DecisionEntityRelationship.objects.create(
            decision=decision,
            entity=target,
            role="person",
            parent_key_path="person[0]",
        )

        result = CounterpartRecoveryService().recover_decision(
            decision, force=True, apply=True, allow_ai=False
        )

        assert result["status"] == "recovered"
        amount.refresh_from_db()
        assert amount.associated_relationship_id == existing.id
        assert not DecisionEntityRelationship.objects.filter(
            pk=self_rel.pk
        ).exists()
        existing.refresh_from_db()
        assert existing.is_inferred is True

        attempt = CounterpartRecoveryAttempt.objects.get(decision=decision)
        assert attempt.original_afm == SELF_AFM
        assert attempt.original_role == "person"

    def test_same_inputs_are_skipped(self):
        decision, _, _, _ = _seed_decision(with_target_entity=False)
        extraction = decision.text_extraction
        extraction.raw_text = (
            "ΑΦΜ 899972873 και ΑΦΜ 167375970 εμφανίζονται στο έγγραφο. "
            "Η αξία της ανάθεσης είναι 30.000,00 ευρώ."
        )
        extraction.save(update_fields=["raw_text"])

        service = CounterpartRecoveryService()
        first = service.recover_decision(
            decision, force=True, apply=True, allow_ai=False
        )
        assert first["status"] == "needs_review"
        attempts_after_first = CounterpartRecoveryAttempt.objects.filter(
            decision=decision
        ).count()

        # Same text/provider/flags: nothing new to learn, no new attempt.
        second = service.recover_decision(
            decision, force=False, apply=True, allow_ai=False
        )
        assert second["status"] == "skipped"
        assert second["reason"] == "same_inputs"
        assert (
            CounterpartRecoveryAttempt.objects.filter(
                decision=decision
            ).count()
            == attempts_after_first
        )

        # --force explicitly opts into a retry.
        third = service.recover_decision(
            decision, force=True, apply=True, allow_ai=False
        )
        assert third["status"] == "needs_review"

    def test_changed_text_or_provider_retries(self):
        decision, relationship, _, extraction = _seed_decision(
            with_target_entity=False
        )
        extraction.raw_text = (
            "ΑΦΜ 899972873 και ΑΦΜ 167375970 εμφανίζονται στο έγγραφο. "
            "Η αξία της ανάθεσης είναι 30.000,00 ευρώ."
        )
        extraction.save(update_fields=["raw_text"])

        service = CounterpartRecoveryService()
        first = service.recover_decision(
            decision, force=True, apply=True, allow_ai=False
        )
        assert first["status"] == "needs_review"

        # A new OCR provider run (same text, different provider metadata) is a
        # different input and must be eligible again.
        extraction.ocr_metadata = {
            "provider": "TESSERACT_V2",
            "dpi": 300,
            "lang": "ell+eng",
        }
        extraction.save(update_fields=["ocr_metadata"])
        second = service.recover_decision(
            decision, force=False, apply=True, allow_ai=False
        )
        assert second["status"] != "skipped"

        # Changed text is also a new signature.
        extraction.raw_text = (
            "Ο ανάδοχος με ΑΦΜ 899972873 είναι ο μοναδικός αντισυμβαλλόμενος. "
            "Η αξία της ανάθεσης είναι 30.000,00 ευρώ."
        )
        extraction.save(update_fields=["raw_text"])
        AFMEntityFactory(
            afm=REAL_AFM, name="ΠΡΑΓΜΑΤΙΚΟΣ ΑΝΑΔΟΧΟΣ", total_appearances=3
        )
        third = service.recover_decision(
            decision, force=False, apply=True, allow_ai=False
        )
        assert third["status"] == "recovered"
        relationship.refresh_from_db()
        assert relationship.entity.afm == REAL_AFM

    def test_ai_fallback_validates_and_logs_system_cost(self, monkeypatch):
        from django.conf import settings

        monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "test-key")
        decision, relationship, _, _ = _seed_decision(with_target_entity=False)
        # Two equally-scored candidates make the regex decision ambiguous.
        extraction = decision.text_extraction
        extraction.raw_text = (
            "ΑΦΜ 899972873 και ΑΦΜ 167375970 εμφανίζονται στο έγγραφο. "
            "Η αξία της ανάθεσης είναι 30.000,00 ευρώ."
        )
        extraction.save(update_fields=["raw_text"])

        class _FakeProvider:
            def invoke(self, **kwargs):
                return {
                    "success": True,
                    "text": json.dumps(
                        {
                            "counterpart_afm": REAL_AFM,
                            "role": "person",
                            "confidence": 0.93,
                            "evidence": "ΑΦΜ 899972873",
                        }
                    ),
                    "input_tokens": 120,
                    "output_tokens": 40,
                    "actual_cost_usd": Decimal("0.000123"),
                }

        monkeypatch.setattr(
            "core.services.ai_counterpart_resolver.get_provider",
            lambda *a, **k: _FakeProvider(),
        )

        result = CounterpartRecoveryService().recover_decision(
            decision, force=True, apply=True, allow_ai=True
        )

        assert result["status"] == "recovered"
        assert result["method"] == "AI_TEXT"
        relationship.refresh_from_db()
        assert relationship.entity.afm == REAL_AFM
        assert relationship.metadata_source == "AI_TEXT"

        log = AIInteractionLog.objects.get(trigger="counterpart_recovery")
        assert log.billed_to == "SYSTEM"
        assert log.input_tokens == 120
        assert log.output_tokens == 40

        attempt = CounterpartRecoveryAttempt.objects.get(decision=decision)
        assert attempt.original_afm == SELF_AFM
        assert attempt.confidence <= 0.90

    def test_invalid_ai_answer_changes_nothing(self, monkeypatch):
        from django.conf import settings

        monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "test-key")
        decision, relationship, _, _ = _seed_decision(with_target_entity=False)
        extraction = decision.text_extraction
        extraction.raw_text = (
            "ΑΦΜ 899972873 και ΑΦΜ 167375970 εμφανίζονται στο έγγραφο. "
            "Η αξία της ανάθεσης είναι 30.000,00 ευρώ."
        )
        extraction.save(update_fields=["raw_text"])

        class _FakeProvider:
            def invoke(self, **kwargs):
                return {
                    "success": True,
                    "text": json.dumps(
                        {
                            "counterpart_afm": "123456789",  # not in the text
                            "confidence": 0.99,
                            "evidence": "invented",
                        }
                    ),
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "actual_cost_usd": Decimal("0.00001"),
                }

        monkeypatch.setattr(
            "core.services.ai_counterpart_resolver.get_provider",
            lambda *a, **k: _FakeProvider(),
        )

        result = CounterpartRecoveryService().recover_decision(
            decision, force=True, apply=True, allow_ai=True
        )

        assert result["status"] == "needs_review"
        relationship.refresh_from_db()
        assert relationship.entity.afm == SELF_AFM
        assert relationship.is_inferred is False
        assert CounterpartRecoveryAttempt.objects.get(
            decision=decision
        ).status == RecoveryStatus.NEEDS_REVIEW
