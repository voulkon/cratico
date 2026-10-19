"""
Phases for the ``bad-amounts`` E2E spec: seed the canonical wrong-amount
cases from ``docs/en/DATA_QUALITY.md`` and drive them through the real
correction pipeline, so the decision detail page shows exactly the state the
detector framework produces.

The five display semantics the spec pins (see DecisionDetailPage):

- **decimal shift** (i=0) — the recorded amount is wrong and we recovered the
  real one: ``verified_amount`` is written, the hero shows the corrected
  value with the corrected badge.
- **AFM / KAE as amount** (i=1, i=2) — the recorded value is not money at all
  and the real amount is unknown: the invalid-amount marker is written, the
  hero states it explicitly (with the raw recorded value).
- **self-as-counterpart** (i=3) — decision-level: the amount is confirmed by
  the document (well-formed €22,000), only the counterpart is unknown (it
  equals the issuing org's own VAT number).  No amount marker is written; the
  detail API exposes ``has_self_counterpart`` and the page shows the amount
  with a counterpart warning.
- **amount absent from the text** (i=4) — the recorded €997,379,264 appears
  nowhere in the document (which says €25,000); we cannot recover it, so the
  row is marked ``amount_not_in_text`` and is not presented as trusted money.
  This decision is *also* self-as-counterpart, proving the two verdicts are
  independent.

Teardown removes the run-scoped decisions + organizations (amount fields,
relationships and extractions cascade).  ``AFMEntity`` rows are global
(get_or_create'd) and intentionally survive, exactly like real entities.
"""

from decimal import Decimal

from api.e2e_fixtures import shared

# Canonical values from docs/en/DATA_QUALITY.md §1.2 / §5.
AFM = "099370337"  # VIOLAK INTERNATIONAL
KAE = "70.6273.001"  # digits 706273001
SELF_AFM = "090064864"  # ΙΦΕΤ Μ.Α.Ε. — org == counterpart
#: ADA ΨΘΚΧ46ΝΚΟΤ-6ΤΞ: org VAT == donationGiver AFM; €997,379,264 is not in the text.
UNCONFIRMED_ORG_VAT = "090283815"
UNCONFIRMED_RECORDED_AMOUNT = Decimal("997379264.00")

CASE_SUBJECTS = [
    "E2E bad amounts — decimal shift (corrected)",
    "E2E bad amounts — AFM recorded as amount",
    "E2E bad amounts — KAE recorded as amount",
    "E2E bad amounts — self as counterpart",
    "E2E bad amounts — amount absent from the document",
]


def _seed_extraction(decision, raw_text):
    """Seed a completed document extraction (no network) — see search.py."""
    from core.models.document_analysis import DocumentExtraction

    DocumentExtraction.objects.get_or_create(
        decision=decision,
        defaults={
            "raw_text": raw_text,
            "extraction_status": "COMPLETED",
            "extraction_provider": "PYMUPDF",
            "page_count": 1,
            "character_count": len(raw_text),
            "is_scanned_document": False,
            "processing_time_ms": 100,
        },
    )


def _seed_efv(decision, efv):
    """Attach Diavgeia metadata and run the real extraction service."""
    from core.services.entity_amount_extraction_service import (
        EntityAmountExtractionService,
    )

    decision.extra_field_values_json = efv
    decision.save(update_fields=["extra_field_values_json"])
    return EntityAmountExtractionService().extract_from_decision(decision)


def setup(run_id):
    """Create one decision per case and drive it to its display state."""
    from core.models.entities import DecisionAmountField
    from core.services.amount_correction_service import AmountCorrectionService

    created = []

    # ── Case 0: decimal shift → verified_amount (corrected) ────────────
    org = shared.make_organization(run_id, i=0)
    decision = shared.make_decision(run_id, org, i=0, subject=CASE_SUBJECTS[0])
    _seed_extraction(
        decision, "Εγκρίνεται δαπάνη ποσού 30.000,00 € προς τον προμηθευτή."
    )
    DecisionAmountField.objects.get_or_create(
        decision=decision,
        parent_key_path="amountWithVAT",
        source_field_name="amountWithVAT",
        defaults={
            "amount": Decimal("3000000.00"),
            "currency": "EUR",
            "structure_type": "with_vat",
            "raw_context": {
                "amount": 3000000.0,
                "currency": "EUR",
            },
        },
    )
    result = AmountCorrectionService(threshold=Decimal("0")).correct_decision(decision)
    assert result["status"] == "corrected", result
    created.append(decision.ada)

    # ── Case 1: AFM-as-amount → invalid_amount marker ──────────────────
    org = shared.make_organization(run_id, i=1)
    decision = shared.make_decision(run_id, org, i=1, subject=CASE_SUBJECTS[1])
    _seed_efv(
        decision,
        {
            "sponsor": [
                {
                    "sponsorAFMName": {
                        "afm": AFM,
                        "afmType": "EL",
                        "name": "VIOLAK INTERNATIONAL ΝΟΣΟΚΟΜΕΙΑΚΟΥ "
                        "ΕΞΟΠΛΙΣΜΟΥ ΑΝΩΝΥΜΗ ΕΜΠΟΡΙΚΗ ΕΤΑΙΡΕΙΑ",
                    },
                    "expenseAmount": {"amount": 9.9370337e7, "currency": "EUR"},
                    "kae": "1311",
                }
            ]
        },
    )
    anomalies = AmountCorrectionService().flag_non_monetary_values(decision)
    assert anomalies and anomalies[0].reason == "afm_as_amount", anomalies
    created.append(decision.ada)

    # ── Case 2: KAE-as-amount → invalid_amount marker ──────────────────
    org = shared.make_organization(run_id, i=2)
    decision = shared.make_decision(run_id, org, i=2, subject=CASE_SUBJECTS[2])
    _seed_efv(
        decision,
        {
            "sponsor": [
                {
                    "sponsorAFMName": {"afm": "090000045", "afmType": "EL"},
                    "expenseAmount": {
                        "amount": 7.06273001e8,
                        "currency": "EUR",
                        "kae": KAE,
                    },
                }
            ]
        },
    )
    anomalies = AmountCorrectionService().flag_non_monetary_values(decision)
    assert anomalies and anomalies[0].reason == "kae_as_amount", anomalies
    created.append(decision.ada)

    # ── Case 3: self-as-counterpart → amounts stay believed ────────────
    org = shared.make_organization(run_id, i=3, vat_number=SELF_AFM)
    decision = shared.make_decision(run_id, org, i=3, subject=CASE_SUBJECTS[3])
    _seed_efv(
        decision,
        {
            "person": [
                {
                    "afm": SELF_AFM,
                    "name": "E2E SELF COUNTERPART ENTITY ΜΟΝΟΠΡΟΣΩΠΗ Ι.Ε.",
                    "afmType": "EL",
                }
            ],
            "awardAmount": {"amount": 22000.0, "currency": "EUR"},
        },
    )
    from core.services.non_monetary_value_guard import collect_self_counterparts

    assert collect_self_counterparts(decision) == {SELF_AFM}
    assert not decision.amount_fields.filter(
        invalid_amount_reason__isnull=False
    ).exists()
    _seed_extraction(decision, "Εγκρίνεται δαπάνη ποσού 22.000,00 € για υπηρεσίες.")
    created.append(decision.ada)

    # ── Case 4: recorded amount absent from the text → unconfirmed ─────
    # Real payload shape for ΨΘΚΧ46ΝΚΟΤ-6ΤΞ: the API records 9.97379264E8 but
    # the document only contains 25.000,00 € (and 3.000,00 €).  The
    # donationGiver AFM equals the org's own VAT, so the decision is also
    # self-as-counterpart — the two signals must remain independent.
    org = shared.make_organization(run_id, i=4, vat_number=UNCONFIRMED_ORG_VAT)
    decision = shared.make_decision(run_id, org, i=4, subject=CASE_SUBJECTS[4])
    _seed_extraction(
        decision,
        "Α. Επιχορήγηση του φορέα με το ποσό των είκοσι πέντε χιλιάδων "
        "ευρώ (25.000,00 €). Γ. Για ποσά επιχορηγήσεων άνω των 3.000,00€ "
        "ισχύουν οι σχετικές διατάξεις.",
    )
    _seed_efv(
        decision,
        {
            "donationType": "Επιχορήγηση",
            "amountWithVAT": {
                "amount": 9.97379264e8,
                "currency": "EUR",
            },
            "kae": "2310802897",
            "donationGiver": {
                "afm": UNCONFIRMED_ORG_VAT,
                "afmType": "EL",
                "name": "ΥΠΟΥΡΓΕΙΟ ΠΟΛΙΤΙΣΜΟΥ",
            },
            "donationReceiver": [
                {
                    "afm": "997379286",
                    "afmType": "EL",
                    "name": "ΘΕΑΤΡΟ ΠΡΟΒΑ ΠΟΛΙΤΙΣΤΙΚΗ Α.Μ.Κ.Ε.",
                }
            ],
        },
    )
    result = AmountCorrectionService(threshold=Decimal("0")).correct_decision(decision)
    assert result["status"] == "amount_not_in_text", result
    assert decision.amount_fields.get().amount == UNCONFIRMED_RECORDED_AMOUNT
    assert decision.amount_fields.filter(
        invalid_amount_reason="amount_not_in_text"
    ).exists()
    created.append(decision.ada)

    return f"seeded {len(created)} bad-amount decisions: {', '.join(created)}"


def teardown(run_id):
    return shared.teardown_run_data(run_id)
