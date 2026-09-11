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
from core.services.non_monetary_value_guard import (
    DISCREPANCY_REASON_AFM,
    DISCREPANCY_REASON_KAE,
    DISCREPANCY_REASON_NON_MONETARY,
    KIND_AFM,
    KIND_KAE,
    NonMonetaryValue,
    collect_non_monetary_values,
)
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
        # ── Get all amount fields (with amounts > 0) ───────────────
        fields = list(
            decision.amount_fields
            .filter(amount__isnull=False, amount__gt=0)
            .only("id", "amount", "source_field_name", "parent_key_path")
        )
        if not fields:
            return {"status": "skipped", "reason": "no_db_amounts"}

        db_amounts = [f.amount for f in fields]

        # ── Non-monetary-value-as-amount guard (DB-only) ───────────
        # If a recorded amount is really an AFM (counterpart VAT number) or a
        # KAE (budget classification code), the text may still contain that
        # value formatted as an amount — do NOT "correct" the field to it.
        # Flag it and leave verified_amount untouched (the discrepancy is
        # recorded by AmountVerificationService in the resolution note).
        #
        # This detector needs no document text, so it runs BEFORE any
        # download/extraction: a value we will refuse to write must never
        # cost a document read.
        anomaly_by_field = {
            anomaly.field_id: anomaly
            for anomaly in collect_non_monetary_values(
                decision, amount_fields=fields
            )
        }
        if anomaly_by_field:
            logger.warning(
                f"AmountCorrection: decision {decision.id} ({decision.ada}) "
                f"has {len(anomaly_by_field)} field(s) whose amount is a "
                f"non-monetary value (AFM/KAE) — refusing to write it into "
                f"verified_amount"
            )
            # Mark the row(s) invalid so they are excluded from every monetary
            # aggregation and surface in the feedback pool.  We still write NO
            # monetary value — the real amount is unknown.
            self._flag_invalid_amounts(
                fields, anomaly_by_field, dry_run=dry_run
            )

        # Every recorded amount is a non-monetary value → there is nothing
        # left to verify against the text, so skip the document read entirely.
        if anomaly_by_field and len(anomaly_by_field) == len(fields):
            return self._non_monetary_result(anomaly_by_field, db_amounts)

        # ── Get the document text ──────────────────────────────────
        # If no completed extraction exists, read the document on the spot
        # (download + extract) so we can still attempt correction.
        text = self._get_text(decision)
        if not text and read_if_missing:
            extraction = self._ensure_text_extraction(decision)
            text = extraction.raw_text if extraction else None
        if not text:
            return {"status": "skipped", "reason": "no_text"}

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
        flagged: list[dict] = []
        fields_to_update: list[DecisionAmountField] = []

        for i, match in enumerate(grouped_result.matches):
            field = fields[i]
            anomaly = anomaly_by_field.get(field.id)
            if anomaly is not None:
                # The field's amount is a non-monetary value (AFM/KAE) — never
                # treat it as correctable, even when the text "confirms" it.
                flagged.append({
                    "field_id": field.id,
                    "source_field": field.source_field_name,
                    "db_amount": str(field.amount),
                    "matched_value": anomaly.matched_value,
                    "discrepancy_reason": anomaly.reason,
                    "matched_in_text": match.found_exact,
                })
                continue

            if match.found_exact:
                continue  # This field is already correct

            if match.clone_factor in (CLONE_FACTOR_100, CLONE_FACTOR_001):
                # This field has a decimal-shift typo — correct it
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
        if not corrections and not anomaly_by_field:
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
            if anomaly_by_field:
                return self._non_monetary_result(anomaly_by_field, db_amounts)
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
            "flagged": flagged,
            "corrections": corrections,
        }

    # ------------------------------------------------------------------
    # Non-monetary-value marker (AFM/KAE recorded as an amount)
    # ------------------------------------------------------------------

    def flag_non_monetary_values(
        self,
        decision: Decision,
        *,
        dry_run: bool = False,
    ) -> list[NonMonetaryValue]:
        """
        Detect and mark amount fields whose value is really a non-monetary
        AFM/KAE, **without reading the document**.

        This is the "treatment" half of the guard: it writes only the
        invalid-amount marker (``invalid_amount_reason`` / ``_value`` /
        ``_flagged_at``), never ``verified_amount`` — the real amount is
        unknown, and storing a monetary figure would be a lie.

        DB-only and idempotent: re-running rewrites the same reason/value and
        refreshes the timestamp, so it is safe to repeat.

        Args:
            decision: The Decision to inspect.
            dry_run: When True, detect but write nothing.

        Returns:
            The detected ``NonMonetaryValue`` anomalies (empty if none).
        """
        fields = list(
            decision.amount_fields
            .filter(amount__isnull=False, amount__gt=0)
            .only("id", "amount", "source_field_name", "parent_key_path")
        )
        if not fields:
            return []

        anomalies = collect_non_monetary_values(decision, amount_fields=fields)
        if not anomalies:
            return []

        anomaly_by_field = {a.field_id: a for a in anomalies}
        self._flag_invalid_amounts(fields, anomaly_by_field, dry_run=dry_run)
        return anomalies

    @staticmethod
    def clear_non_monetary_markers(
        decision: Decision,
        *,
        kind: str | None = None,
        dry_run: bool = False,
    ) -> int:
        """
        Remove the invalid-amount marker from a decision's amount fields.

        Rollback path.  The marker never touches ``verified_amount``, so
        clearing only NULLs the three ``invalid_amount_*`` columns.  Restrict
        to one kind (``KIND_AFM`` / ``KIND_KAE``) via the stored reason.

        Returns:
            The number of fields that were (or would be) cleared.
        """
        qs = decision.amount_fields.filter(invalid_amount_reason__isnull=False)
        if kind == KIND_AFM:
            qs = qs.filter(invalid_amount_reason=DISCREPANCY_REASON_AFM)
        elif kind == KIND_KAE:
            qs = qs.filter(invalid_amount_reason=DISCREPANCY_REASON_KAE)

        count = qs.count()
        if dry_run or not count:
            return count

        qs.update(
            invalid_amount_reason=None,
            invalid_amount_value=None,
            invalid_amount_flagged_at=None,
        )
        return count

    @staticmethod
    def _flag_invalid_amounts(
        fields: list[DecisionAmountField],
        anomaly_by_field: dict,
        *,
        dry_run: bool = False,
    ) -> list[DecisionAmountField]:
        """
        Persist the non-monetary-value marker on the affected amount fields.

        We never write a monetary value (the real amount is unknown) — we only
        record *why* the amount is unusable plus the value it matched.  The
        facet layer (``core.services.decision_facets``) then excludes these
        rows from every monetary aggregation.

        Honours ``dry_run``: when dry-running nothing is written, which is what
        makes ``dry_run`` meaningful for this guard.

        Returns the list of fields that were persisted.
        """
        if dry_run:
            return []
        now = timezone.now()
        to_flag = []
        for field in fields:
            anomaly = anomaly_by_field.get(field.id)
            if anomaly is None:
                continue
            field.invalid_amount_reason = anomaly.reason
            field.invalid_amount_value = anomaly.matched_value
            field.invalid_amount_flagged_at = now
            to_flag.append(field)

        if to_flag:
            DecisionAmountField.objects.bulk_update(
                to_flag,
                [
                    "invalid_amount_reason",
                    "invalid_amount_value",
                    "invalid_amount_flagged_at",
                ],
            )
        return to_flag

    @staticmethod
    def _non_monetary_result(
        anomaly_by_field: dict,
        db_amounts: list,
    ) -> dict[str, Any]:
        """
        Build the result dict for a decision whose amount field(s) hold a
        non-monetary value (AFM/KAE).

        These fields are reported as *flagged*, never as corrected: the
        guard deliberately refuses to write such a value into
        ``verified_amount``.
        """
        reasons = {a.reason for a in anomaly_by_field.values()}
        # Mixed AFM + KAE (or future kinds) → generic status
        if reasons == {DISCREPANCY_REASON_AFM}:
            status = DISCREPANCY_REASON_AFM
        elif reasons == {DISCREPANCY_REASON_KAE}:
            status = DISCREPANCY_REASON_KAE
        else:
            status = DISCREPANCY_REASON_NON_MONETARY
        return {
            "status": status,
            "discrepancy_reason": (
                next(iter(reasons)) if len(reasons) == 1 else None
            ),
            "db_amounts": [str(a) for a in db_amounts],
            "flagged_field_ids": sorted(anomaly_by_field),
            "afm_flagged_field_ids": sorted(
                fid
                for fid, a in anomaly_by_field.items()
                if a.kind == KIND_AFM
            ),
            "matched_values": {
                str(fid): a.matched_value
                for fid, a in anomaly_by_field.items()
            },
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
        imported_since=None,
        imported_until=None,
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
            imported_since: Optional date/datetime — only decisions *imported*
                (``Decision.created_at``) on/after this point. This scopes the
                post-import run to newly imported decisions instead of the
                entire historical backlog.
            imported_until: Optional date/datetime upper bound for created_at.

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

        if imported_since is not None:
            candidates = candidates.filter(created_at__gte=imported_since)
        if imported_until is not None:
            candidates = candidates.filter(created_at__lt=imported_until)

        candidates = candidates.order_by("-calc_total")

        # Apply the limit BEFORE counting.  ``candidates.count()`` on the
        # un-sliced queryset executes the whole join + GROUP BY + HAVING as
        # ``SELECT COUNT(*) FROM (…)`` — the pattern behind the 16h runaway
        # query and its lock pileup (see
        # ``docs/lessons_learnt/runaway_query_lock_pileup.md``).
        #
        # Materialise the (already limited) candidate set once and derive the
        # count from it: the heavy aggregate runs a single time instead of
        # twice, and is never executed over the entire table.
        if limit:
            candidates = candidates[:limit]
        decisions = list(candidates)
        total_candidates = len(decisions)
        logger.info(
            f"AmountCorrection: {total_candidates} decisions above "
            f"€{threshold:,.2f} threshold"
        )

        corrected = 0
        consistent = 0
        afm_as_amount = 0
        kae_as_amount = 0
        non_monetary_value_as_amount = 0
        skipped = 0
        no_text = 0
        errors = 0
        results: list[dict[str, Any]] = []

        for decision in decisions:
            try:
                result = self.correct_decision(
                    decision, dry_run=dry_run, read_if_missing=read_if_missing
                )
                status = result["status"]
                if status in ("corrected", "would_correct"):
                    corrected += 1
                elif status == DISCREPANCY_REASON_AFM:
                    afm_as_amount += 1
                elif status == DISCREPANCY_REASON_KAE:
                    kae_as_amount += 1
                elif status == DISCREPANCY_REASON_NON_MONETARY:
                    non_monetary_value_as_amount += 1
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
                    "flagged": result.get("flagged", []),
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
            "afm_as_amount": afm_as_amount,
            "kae_as_amount": kae_as_amount,
            "non_monetary_value_as_amount": non_monetary_value_as_amount,
            "no_text": no_text,
            "skipped": skipped,
            "errors": errors,
            "dry_run": dry_run,
            "read_if_missing": read_if_missing,
            "results": results,
        }
        # Log the COUNTS only — ``results`` holds one row per decision and
        # bloats the log line (up to `limit` entries).  The full list is still
        # returned to the caller (admin job / task) for the UI.
        logger.info(
            f"AmountCorrection batch complete: {total_candidates} candidate(s), "
            f"{corrected} corrected, {afm_as_amount} afm_as_amount, "
            f"{kae_as_amount} kae_as_amount, "
            f"{non_monetary_value_as_amount} non_monetary_value_as_amount, "
            f"{consistent} consistent, {no_text} no_text, {skipped} skipped, "
            f"{errors} errors (dry_run={dry_run})"
        )
        return summary

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def frontend_url(decision: Decision) -> str:
        """Return the frontend page URL for a decision."""
        from core.services.frontend_url import decision_frontend_url

        return decision_frontend_url(decision)

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
