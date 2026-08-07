"""
Amount Correction Service

Uses the cents-based detector (``grouped_amount_detection``) to find and
correct monetary amount typos in decisions — at the ``DecisionAmountField``
level, NOT by bloating the Decision model.

The classic Diavgeia typo: dropping the decimal comma when typing
30.000,00 → 3.000.000 (×100 shift).  This service reads the actual
document text, detects what amounts are written there, and — when an
individual ``DecisionAmountField.amount`` disagrees with the text — stores
the corrected value in ``DecisionAmountField.verified_amount``.

If a decision has no extracted text yet, the service reads the document
first (download + extract) before attempting correction — pass
``read_if_missing=False`` to skip that and only process already-extracted
decisions.

All downstream consumers use ``effective_amount_sum()`` (which sums
``COALESCE(verified_amount, amount)``) so corrected values automatically
override the erroneous metadata amounts everywhere — no model bloat
needed.

Usage:
    svc = AmountCorrectionService()

    # Correct a single decision (reads the document first if needed):
    result = svc.correct_decision(decision)

    # Batch-correct high-value decisions:
    summary = svc.correct_high_value_decisions(
        threshold=Decimal("50000"),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
    )
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.db.models import Exists, OuterRef
from django.utils import timezone
from loguru import logger

from core.models.decisions import Decision
from core.models.document_analysis import DocumentExtraction, ProcessingStatus
from core.models.entities import DecisionAmountField
from core.services.grouped_amount_detection import (
    verify_amounts_against_grouped,
)

# Default threshold: decisions with total ≥ €100,000 are candidates.
DEFAULT_CORRECTION_THRESHOLD = Decimal("100000")

# We only correct when the text amount is a clean ×100 or ÷100 multiple
# of the DB amount — the classic comma-shift typo.
CLONE_FACTOR_100 = Decimal("100")
CLONE_FACTOR_001 = Decimal("0.01")


class AmountCorrectionService:
    """
    Detect and correct monetary amount typos using cents-based text analysis.

    Corrects individual ``DecisionAmountField`` rows — no Decision-model bloat.
    """

    def __init__(self, threshold: Decimal | None = None):
        self.threshold = threshold or DEFAULT_CORRECTION_THRESHOLD

    # ------------------------------------------------------------------
    # Single-decision correction  (field-level)
    # ------------------------------------------------------------------

    def correct_decision(
        self,
        decision: Decision,
        *,
        dry_run: bool = False,
        read_if_missing: bool = True,
    ) -> dict[str, Any]:
        """
        Run cents-based detection and correct individual amount fields.

        For each ``DecisionAmountField`` whose amount is NOT found verbatim
        in the text but HAS a ×100/÷100 clone, set ``verified_amount`` to
        the text-detected value.

        Args:
            decision: The Decision to check.
            dry_run: If True, report without saving.
            read_if_missing: If True (default) and the decision has no
                completed text extraction yet, read the document first
                (download + extract) before attempting correction.

        Returns:
            Dict with status, per-field corrections, and details.
        """
        # ── Get the document text ──────────────────────────────────
        # If no completed extraction exists, read the document on the spot
        # (download + extract) so we can still attempt correction.
        text = self._get_text(decision)
        if not text and read_if_missing:
            extraction = self._ensure_text_extraction(decision)
            text = extraction.raw_text if extraction else None
        if not text:
            return {"status": "skipped", "reason": "no_text"}

        # ── Get all amount fields (with amounts > 0) ───────────────
        fields = list(
            decision.amount_fields
            .filter(amount__isnull=False, amount__gt=0)
            .only("id", "amount", "source_field_name")
        )
        if not fields:
            return {"status": "skipped", "reason": "no_db_amounts"}

        db_amounts = [f.amount for f in fields]

        # ── Run cents-based detection ──────────────────────────────
        grouped_result = verify_amounts_against_grouped(text, db_amounts)

        if not grouped_result.grouped_amounts:
            return {
                "status": "no_text_amounts_found",
                "db_amounts": [str(a) for a in db_amounts],
            }

        # ── Map matches back to specific DecisionAmountField rows ──
        # Each GroupedMatchResult corresponds 1:1 with db_amounts
        corrections: list[dict] = []
        fields_to_update: list[DecisionAmountField] = []

        for i, match in enumerate(grouped_result.matches):
            if match.found_exact:
                continue  # This field is already correct

            if match.clone_factor in (CLONE_FACTOR_100, CLONE_FACTOR_001):
                # This field has a decimal-shift typo — correct it
                field = fields[i]
                corrected_value = match.matched_text_amount
                corrections.append({
                    "field_id": field.id,
                    "source_field": field.source_field_name,
                    "db_amount": str(field.amount),
                    "corrected_to": str(corrected_value),
                    "clone_factor": str(match.clone_factor),
                })
                if not dry_run:
                    field.verified_amount = corrected_value
                    field.amount_verified_at = timezone.now()
                    fields_to_update.append(field)

        # ── Group correction: total-level re-scaling ──────────────────
        # When NO individual amount matched but the SUM has a ×100/÷100
        # clone in the text, every field was uniformly mis-typed.  Re-scale
        # each field proportionally so the corrected total equals the text
        # amount.  The last field absorbs any rounding remainder.
        if not corrections:
            db_total = sum(db_amounts)
            if db_total > 0:
                text_total = self._find_total_clone(
                    db_total, grouped_result.grouped_amounts
                )
                if text_total is not None:
                    scale_factor = text_total / db_total

                    # Sanity check: only apply a group correction when the
                    # implied scale factor is genuinely ~×100 or ~÷100.
                    # The last field absorbs the rounding remainder, so the
                    # effective factor may deviate slightly — accept ratios
                    # in [99, 101] (i.e. ~1% tolerance around ×100).
                    implied_ratio = (
                        db_total / text_total
                        if scale_factor < 1
                        else text_total / db_total
                    )
                    if not (Decimal("99") <= implied_ratio <= Decimal("101")):
                        logger.warning(
                            f"AmountCorrection: decision {decision.id} "
                            f"({decision.ada}) group clone rejected — implied "
                            f"ratio {implied_ratio:.4f} outside [99, 101]"
                        )
                        text_total = None

                if text_total is not None:
                    scale_factor = text_total / db_total
                    running = Decimal("0")
                    now = timezone.now()

                    for j, field in enumerate(fields):
                        is_last = j == len(fields) - 1
                        if is_last:
                            # Absorb rounding remainder
                            corrected_value = text_total - running
                        else:
                            corrected_value = (
                                field.amount * scale_factor
                            ).quantize(Decimal("0.01"))
                            running += corrected_value

                        corrections.append({
                            "field_id": field.id,
                            "source_field": field.source_field_name,
                            "db_amount": str(field.amount),
                            "corrected_to": str(corrected_value),
                            "clone_factor": (
                                CLONE_FACTOR_001 if scale_factor < 1 else CLONE_FACTOR_100
                            ),
                            "group_correction": True,
                        })
                        if not dry_run:
                            field.verified_amount = corrected_value
                            field.amount_verified_at = now
                            fields_to_update.append(field)

        if not corrections:
            if grouped_result.all_found:
                return {
                    "status": "consistent",
                    "db_amounts": [str(a) for a in db_amounts],
                }
            return {
                "status": "no_correctable_fields",
                "db_amounts": [str(a) for a in db_amounts],
                "text_amounts": [
                    str(g.amount) for g in grouped_result.grouped_amounts
                ],
            }

        # ── Persist ────────────────────────────────────────────────
        if not dry_run and fields_to_update:
            DecisionAmountField.objects.bulk_update(
                fields_to_update, ["verified_amount", "amount_verified_at"]
            )

            logger.info(
                f"AmountCorrection: decision {decision.id} ({decision.ada}) "
                f"corrected {len(fields_to_update)} field(s): "
                + ", ".join(
                    f"{c['source_field']}: {c['db_amount']} → {c['corrected_to']}"
                    for c in corrections
                )
            )

        return {
            "status": "corrected" if not dry_run else "would_correct",
            "decision_id": decision.id,
            "ada": decision.ada,
            "fields_corrected": len(corrections),
            "group_correction": any(c.get("group_correction") for c in corrections),
            "corrections": corrections,
        }

    @staticmethod
    def _find_total_clone(
        db_total: Decimal,
        grouped_amounts: list,
    ) -> Decimal | None:
        """
        Check if the *sum* of all DB amounts has a clean ×100 or ÷100
        clone among the cents-bearing amounts found in the text.

        Returns the text amount if found, else None.
        """
        if db_total <= 0 or not grouped_amounts:
            return None

        text_values = {g.amount for g in grouped_amounts}
        tolerance = Decimal("0.01")

        # Check ÷100 (text = db / 100 — the classic comma-drop)
        db_div_100 = (db_total / 100).quantize(Decimal("0.01"))
        if any(abs(v - db_div_100) <= tolerance for v in text_values):
            return db_div_100

        # Check ×100 (text = db * 100 — reverse typo)
        db_mul_100 = (db_total * 100).quantize(Decimal("0.01"))
        if any(abs(v - db_mul_100) <= tolerance for v in text_values):
            return db_mul_100

        return None

    # ------------------------------------------------------------------
    # Batch correction
    # ------------------------------------------------------------------

    def correct_high_value_decisions(
        self,
        threshold: Decimal | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int | None = None,
        dry_run: bool = False,
        read_if_missing: bool = True,
    ) -> dict[str, Any]:
        """
        Find all decisions whose computed total exceeds *threshold* and
        run cents-based correction on each.

        Skips decisions where ALL amount fields already have
        ``verified_amount`` set (fully corrected).

        Args:
            threshold: Minimum DB-computed total.
            start_date: Optional issue-date lower bound.
            end_date: Optional issue-date upper bound.
            limit: Optional cap on how many decisions to process.
            dry_run: If True, only report what would be corrected.
            read_if_missing: If True (default), read the document first
                (download + extract) for any candidate decision that has
                no completed text extraction yet.

        Returns:
            Summary dict with counts.
        """
        threshold = threshold or self.threshold

        from core.services.decision_facets import amount_sum_excluding_kae

        # ── Candidates: decisions above threshold that still have ──
        #     at least one uncorrected amount field
        has_uncorrected_field = Exists(
            DecisionAmountField.objects.filter(
                decision=OuterRef("pk"),
                amount__gt=0,
                verified_amount__isnull=True,
            )
        )

        candidates = (
            Decision.objects
            .annotate(calc_total=amount_sum_excluding_kae())
            .filter(calc_total__gte=threshold)
            .filter(has_uncorrected_field)
        )

        if start_date:
            from django.utils import timezone as dj_timezone
            start_dt = dj_timezone.make_aware(
                datetime.combine(start_date, datetime.min.time())
            )
            candidates = candidates.filter(issue_date_day__gte=start_dt)

        if end_date:
            from django.utils import timezone as dj_timezone
            end_dt = dj_timezone.make_aware(
                datetime.combine(end_date, datetime.max.time())
            )
            candidates = candidates.filter(issue_date_day__lte=end_dt)

        candidates = candidates.order_by("-calc_total")

        total_candidates = candidates.count()
        logger.info(
            f"AmountCorrection: {total_candidates} decisions above "
            f"€{threshold:,.2f} threshold"
        )

        if limit:
            candidates = candidates[:limit]

        corrected = 0
        consistent = 0
        skipped = 0
        no_text = 0
        errors = 0
        results: list[dict[str, Any]] = []

        for decision in candidates:
            try:
                result = self.correct_decision(
                    decision, dry_run=dry_run, read_if_missing=read_if_missing
                )
                status = result["status"]
                if status in ("corrected", "would_correct"):
                    corrected += 1
                elif status == "consistent":
                    consistent += 1
                elif status == "no_text_amounts_found":
                    no_text += 1
                else:
                    skipped += 1
                results.append({
                    "decision_id": decision.id,
                    "ada": decision.ada,
                    "subject": decision.subject,
                    "status": status,
                    "frontend_url": self.frontend_url(decision),
                    "corrections": result.get("corrections", []),
                    "group_correction": result.get("group_correction", False),
                    "reason": result.get("reason", ""),
                })
            except Exception as exc:
                logger.error(
                    f"AmountCorrection failed for decision {decision.id}: {exc}",
                    exc_info=True,
                )
                errors += 1
                results.append({
                    "decision_id": decision.id,
                    "ada": decision.ada,
                    "subject": decision.subject,
                    "status": "error",
                    "frontend_url": self.frontend_url(decision),
                    "corrections": [],
                    "group_correction": False,
                    "reason": str(exc),
                })

        summary = {
            "total_candidates": total_candidates,
            "corrected": corrected,
            "consistent": consistent,
            "no_text": no_text,
            "skipped": skipped,
            "errors": errors,
            "dry_run": dry_run,
            "read_if_missing": read_if_missing,
            "results": results,
        }
        logger.info(f"AmountCorrection batch complete: {summary}")
        return summary

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def frontend_url(decision: Decision) -> str:
        """Return the frontend page URL for a decision."""
        from django.conf import settings

        base = (
            settings.FRONTEND_DOMAINS_clean[0]
            if getattr(settings, "FRONTEND_DOMAINS_clean", None)
            else "http://localhost:3000"
        )
        return f"{base}/decision/{decision.id}"

    @staticmethod
    def _get_text(decision: Decision) -> str | None:
        """Get the extracted document text for a decision."""
        extraction = getattr(decision, "text_extraction", None)
        if (
            extraction
            and extraction.extraction_status == ProcessingStatus.COMPLETED
            and extraction.raw_text
        ):
            return extraction.raw_text
        return None

    @staticmethod
    def _ensure_text_extraction(
        decision: Decision,
    ) -> DocumentExtraction | None:
        """
        Get or trigger text extraction for a decision.

        If the decision already has a completed extraction with text, return
        it.  Otherwise read the document synchronously (download + extract,
        via ``extract_decision_text``) and return the new extraction — or the
        previous (incomplete) extraction if reading failed.
        """
        extraction = getattr(decision, "text_extraction", None)
        if (
            extraction
            and extraction.extraction_status == ProcessingStatus.COMPLETED
            and extraction.raw_text
        ):
            return extraction

        # Trigger extraction synchronously (same pattern as
        # AmountVerificationService._ensure_text_extraction)
        try:
            from core.tasks.tasks_decision_ai import extract_decision_text

            result = extract_decision_text(decision.id)
            if result.get("status") in ("extracted", "already_extracted"):
                decision.refresh_from_db()
                return getattr(decision, "text_extraction", None)
        except Exception as exc:
            logger.warning(
                f"AmountCorrection: text extraction failed for "
                f"decision {decision.id}: {exc}"
            )

        return extraction


# Singleton instance for easy importing
correction_service = AmountCorrectionService()
