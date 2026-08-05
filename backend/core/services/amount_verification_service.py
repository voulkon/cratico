"""
Amount Verification Service

Post-import service that verifies monetary amounts in high-value decisions
by reading the actual document text.  Designed to catch data-entry errors
where the person typing the amount into Diavgeia misplaces the decimal
separator (e.g. a decision worth €30,000.00 ends up recorded as €3,000,000).

Architecture
------------
Amount verification is a *text process* (``process="amount"``).  Each run is
anchored to a *DocumentExtraction* (the exact text it was verified against)
and stored as a ``TextProcessRun``, keyed by (extraction, process, method,
provider, model, version) — so the regex heuristic and any number of AI
models can coexist and be compared for the same document.  The raw amounts
found in the text are persisted as ``TextSpan`` rows (label="amount") by the
``amount`` text process; the decision-level verdict lives in
``TextProcessResolution``.

Resolution policy ("exact match wins")
---------------------------------------
For each ``DecisionAmountField`` amount ``D``, the regex method applies:

1. ``D`` appears verbatim in the text  →  ``D`` is CONFIRMED (winner).
   A non-round number appearing in the document is effectively impossible by
   coincidence, so an exact match is trusted even if other amounts are present.
2. else a ×100/÷100 clone of ``D`` is found  →  ``D`` is SHIFTED → discrepancy.
3. else  →  ``D`` is MISSING → discrepancy.

If *every* ``D`` is confirmed, the decision is consistent (no discrepancy) and
the verified amount is the calculated total.  If any field is shifted or
missing, a discrepancy is flagged and the text's primary amount is reported.
"""

from collections import Counter
from decimal import Decimal
from typing import Any

from core.models.decisions import Decision
from core.models.document_analysis import (
    DocumentExtraction,
    ProcessingStatus,
    TextProcessResolution,
    TextProcessRun,
    TextProcessStatus,
    TextSpan,
)
from core.services.amount_text_detection import (
    DetectedAmount,
    verify_amounts_in_text,
)
from core.services.financial_calculation_service import financial_service
from core.services.text_process_service import TextProcessService
from core.services.text_processes.base import TextSpanData
from loguru import logger

PROCESS_SLUG = "amount"


# ── Prompt templates ────────────────────────────────────────────────────────
AMOUNT_VERIFICATION_SYSTEM_PROMPT = """\
You are a financial auditor reviewing Greek government decisions (Διαύγεια).
Your ONLY task is to find the primary monetary amount in the document text.

Rules:
1. Look for amounts near keywords like "ποσό", "amount", "δαπάνη", "expense",
   "προϋπολογισμός", "budget", "αξία", "value", "συνολική", "total", "ΦΠΑ", "VAT".
2. If you find an amount WITH VAT (με ΦΠΑ), that's the primary amount.
3. Return ONLY the number as a plain decimal (e.g. "30000.00").  Do NOT include
   currency symbols, thousand separators, or any other text.
4. If the amount appears with a comma as decimal separator (e.g. "30.000,00"),
   interpret it in European format: the comma is the decimal point.
5. If you cannot determine the amount with confidence, return "UNKNOWN".
6. Do NOT guess — only return amounts that are explicitly stated in the text."""

AMOUNT_VERIFICATION_PROMPT_TEMPLATE = """\
Extract the primary monetary amount from this Greek government decision.
Return ONLY the number (e.g. "30000.00") or "UNKNOWN".

Document text:
{{ text }}"""


# ── Threshold ───────────────────────────────────────────────────────────────
# Decisions whose calculated total exceeds this amount (in EUR) are verified.
DEFAULT_HIGH_VALUE_THRESHOLD = Decimal("1000000.00")  # €1,000,000


class AmountVerificationService:
    """
    Amount verification for high-value decisions (regex-first, AI optional).

    Usage:
        svc = AmountVerificationService()
        result = svc.verify_decision(decision)                  # regex
        result = svc.verify_decision(decision, method="ai")    # LLM
        # or batch:
        results = svc.verify_high_value_decisions()
    """

    def __init__(self, threshold: Decimal | None = None):
        self.threshold = threshold or DEFAULT_HIGH_VALUE_THRESHOLD

    # ------------------------------------------------------------------
    # Batch entry point (called by post-import task)
    # ------------------------------------------------------------------

    def verify_high_value_decisions(
        self,
        method: str = "regex",
        provider: str = "OPENROUTER",
        model: str = "qwen/qwen3.7-flash",
        limit: int | None = None,
    ) -> dict[str, Any]:
        """
        Find all decisions whose calculated total exceeds the threshold
        and run amount verification on each.

        Args:
            method: "regex" (default, free) or "ai" (LLM-based).
            provider: AI provider (only used when method="ai").
            model: Model name (only used when method="ai").
            limit: Optional cap on how many decisions to verify (for cost control).

        Returns:
            Summary dict with counts.
        """
        from django.db.models import Sum

        # Decisions with a calculated total > threshold, excluding already-verified.
        # A decision is "verified" once its resolution points at a COMPLETED run.
        # NOTE: sums ALL amount fields (linked + unlinked) to stay consistent
        # with verify_decision(), which uses include_unlinked=True.
        from core.services.decision_facets import amount_sum_excluding_kae

        candidates = (
            Decision.objects.annotate(calc_total=amount_sum_excluding_kae())
            .filter(calc_total__gte=self.threshold)
            .exclude(
                text_process_resolutions__process=PROCESS_SLUG,
                text_process_resolutions__winning_run__status=(
                    TextProcessStatus.COMPLETED
                ),
            )
            .order_by("-calc_total")
        )

        total_candidates = candidates.count()
        logger.info(
            f"Amount verification: {total_candidates} decisions above "
            f"€{self.threshold:,.2f} threshold"
        )

        if limit:
            candidates = candidates[:limit]

        verified = 0
        skipped = 0
        failed = 0
        discrepancies = 0

        for decision in candidates:
            try:
                result = self.verify_decision(
                    decision, method=method, provider=provider, model=model
                )
                if result["status"] == "completed":
                    verified += 1
                    if result.get("has_discrepancy"):
                        discrepancies += 1
                elif result["status"] == "skipped":
                    skipped += 1
                else:
                    failed += 1
            except Exception as exc:
                logger.error(
                    f"Amount verification failed for decision {decision.id}: {exc}",
                    exc_info=True,
                )
                failed += 1

        summary = {
            "total_candidates": total_candidates,
            "verified": verified,
            "skipped": skipped,
            "failed": failed,
            "discrepancies": discrepancies,
        }
        logger.info(f"Amount verification batch complete: {summary}")
        return summary

    # ------------------------------------------------------------------
    # Single-decision verification
    # ------------------------------------------------------------------

    def verify_decision(
        self,
        decision: Decision,
        method: str = "regex",
        provider: str = "OPENROUTER",
        model: str = "qwen/qwen3.7-flash",
        version: str = "1.0",
    ) -> dict[str, Any]:
        """
        Verify the amount of a single decision against its document text.

        Delegates span detection to the ``amount`` text process (which
        persists a ``TextProcessRun`` + ``TextSpan`` rows), then computes the
        resolution (exact-match-wins / clone detection) and upserts the
        decision-level ``TextProcessResolution``.

        Args:
            decision: The Decision instance.
            method: "regex" (default, heuristics) or "ai" (LLM).
            provider: AI provider (only used when method="ai").
            model: Model name (only used when method="ai").
            version: Version tag for the run, so results can evolve.

        Returns:
            Dict with status, amounts, and discrepancy info.
        """
        # --- Step 1: Get the extracted text ---
        extraction = self._ensure_text_extraction(decision)
        if not extraction or not extraction.raw_text:
            logger.warning(
                f"Decision {decision.id}: no text available for verification"
            )
            return {
                "status": "skipped",
                "reason": "no_text",
            }

        # --- Step 2: Compute the accurate amount ---
        calculated_amount = financial_service.get_decision_total_amount(
            decision, include_unlinked=True
        )
        raw_amount = decision.amount

        # --- Step 3: Detect the amount in the text (regex or AI) ---
        # The AI path calls the LLM here and returns a single amount; the
        # regex path delegates span detection to the amount text process.
        if method == "ai":
            run_provider = provider
            run_model = model
            ai_result = self._call_ai_for_amount(
                text=extraction.raw_text,
                provider=provider,
                model=model,
            )
        else:
            ai_result = self._detect_amounts_with_regex(
                decision=decision,
                text=extraction.raw_text,
                calculated_amount=calculated_amount,
            )
            run_provider = "REGEX"
            run_model = "greek-amount-v1"

        spans = self._candidates_to_spans(ai_result.get("candidates", []))

        # --- Step 4: Get-or-create the generic run, persist spans ---
        run, created = TextProcessRun.objects.get_or_create(
            extraction=extraction,
            process=PROCESS_SLUG,
            method=method,
            provider=run_provider,
            model=run_model,
            version=version,
            defaults={"status": TextProcessStatus.PENDING},
        )
        if not created and run.status == TextProcessStatus.COMPLETED:
            logger.debug(f"Decision {decision.id}: already verified, skipping")
            return {
                "status": "skipped",
                "reason": "already_completed",
                "run_id": run.id,
            }

        # Persist run-level audit data + spans via the process service
        run.meta = {
            "raw_amount": str(raw_amount) if raw_amount is not None else None,
            "calculated_amount": str(calculated_amount)
            if calculated_amount is not None
            else None,
            "raw_response": ai_result.get("raw_response", ""),
            "ai_verified_amount": str(ai_result.get("amount"))
            if ai_result.get("amount") is not None
            else None,
        }
        run.input_tokens = ai_result.get("input_tokens")
        run.output_tokens = ai_result.get("output_tokens")
        run.cost_usd = ai_result.get("cost_usd")

        TextProcessService()._save_spans(run, spans)

        # --- Step 5: Status + discrepancy ---
        verified_amount = ai_result.get("amount")
        if verified_amount is not None:
            if method == "ai":
                has_discrepancy = self._has_significant_discrepancy(
                    text_amount=verified_amount,
                    calculated_amount=calculated_amount,
                    raw_amount=raw_amount,
                )
            else:
                has_discrepancy = ai_result.get("has_discrepancy", False)

            run.status = TextProcessStatus.COMPLETED
            run.error_message = None
            discrepancy_note = self._build_discrepancy_note(
                text_amount=verified_amount,
                calculated_amount=calculated_amount,
                raw_amount=raw_amount,
            )
            run.meta["has_discrepancy"] = has_discrepancy
            run.meta["discrepancy_note"] = discrepancy_note

            logger.info(
                f"Decision {decision.id} ({decision.ada}): "
                f"verified={verified_amount}, "
                f"calc={calculated_amount}, "
                f"raw={raw_amount}, "
                f"discrepancy={has_discrepancy}"
            )
        else:
            run.status = TextProcessStatus.FAILED
            run.error_message = ai_result.get("error") or (
                "Could not determine amount from text"
            )
            has_discrepancy = False
            discrepancy_note = None
            logger.warning(
                f"Decision {decision.id}: could not determine amount from text"
            )

        run.save()

        # --- Step 6: Upsert the decision-level resolution (completed only) ---
        resolution_id = None
        if run.status == TextProcessStatus.COMPLETED:
            chosen_span = (
                TextSpan.objects.filter(
                    run=run, value__amount=str(verified_amount)
                ).first()
            )
            resolution, _ = TextProcessResolution.objects.update_or_create(
                decision=decision,
                process=PROCESS_SLUG,
                defaults={
                    "winning_run": run,
                    "chosen_span": chosen_span,
                    "value": {"amount": str(verified_amount)},
                    "has_discrepancy": has_discrepancy,
                    "note": discrepancy_note,
                },
            )
            resolution_id = resolution.id

        return {
            "status": (
                "completed"
                if run.status == TextProcessStatus.COMPLETED
                else "failed"
            ),
            "run_id": run.id,
            "resolution_id": resolution_id,
            "ai_amount": str(verified_amount) if verified_amount else None,
            "calculated_amount": str(calculated_amount),
            "raw_amount": str(raw_amount) if raw_amount else None,
            "has_discrepancy": has_discrepancy,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_text_extraction(self, decision: Decision) -> DocumentExtraction | None:
        """Get or trigger text extraction for a decision."""
        extraction = getattr(decision, "text_extraction", None)

        if extraction and extraction.extraction_status == ProcessingStatus.COMPLETED:
            if extraction.raw_text:
                return extraction

        # Trigger extraction synchronously for verification
        try:
            from core.tasks.tasks_decision_ai import extract_decision_text

            result = extract_decision_text(decision.id)
            if result.get("status") in ("extracted", "already_extracted"):
                decision.refresh_from_db()
                return getattr(decision, "text_extraction", None)
        except Exception as exc:
            logger.warning(
                f"Decision {decision.id}: text extraction failed: {exc}"
            )

        return extraction

    @staticmethod
    def _candidates_to_spans(candidates: list[DetectedAmount]) -> list[TextSpanData]:
        """
        Convert ``DetectedAmount`` results into ``TextSpanData`` rows.

        Dedupes by amount *value* (not by position): repeated occurrences of
        the same amount collapse into one span pointing at the first
        occurrence, with ``occurrence_count`` set — matching the original
        ``TextAmountCandidate`` semantics (one row per unique amount).
        """
        counter = Counter(c.amount for c in candidates)
        first: dict[Decimal, DetectedAmount] = {}
        for c in candidates:
            first.setdefault(c.amount, c)

        return [
            TextSpanData(
                label="amount",
                start=first[amount].position,
                end=first[amount].position + len(first[amount].raw),
                text_snippet=first[amount].raw,
                value={
                    "amount": str(amount),
                    "near_keyword": first[amount].near_keyword,
                },
                occurrence_count=counter[amount],
            )
            for amount in counter
        ]

    def _detect_amounts_with_regex(
        self,
        decision: Decision,
        text: str,
        calculated_amount: Decimal | None,
    ) -> dict[str, Any]:
        """
        Regex/heuristic amount detection — no AI involved.

        Implements the "exact match wins" policy:

        - Every DB amount found verbatim in the text → decision is consistent;
          the verified amount is the calculated total, no discrepancy.
        - Some DB amount found only as a ×100/÷100 clone → decimal-shift
          discrepancy; the verified amount is the text's primary amount.
        - Otherwise → the verified amount is the text's primary amount (or
          None if nothing was found) and a discrepancy is flagged.

        Returns a dict shaped like the AI result so the caller can treat both
        methods uniformly, plus the raw detected amounts as ``candidates``.
        """
        db_amounts = [
            f.amount
            for f in decision.amount_fields.all()
            if f.amount is not None and f.amount > 0
        ]

        if not db_amounts:
            return {
                "raw_response": "",
                "amount": None,
                "candidates": [],
                "input_tokens": None,
                "output_tokens": None,
                "cost_usd": None,
                "success": False,
                "error": "no_db_amounts",
            }

        result = verify_amounts_in_text(text, db_amounts)

        # Build an audit trail for the raw response field
        audit_lines = [
            f"DB amount: {m.db_amount} → "
            + (
                "FOUND"
                if m.found_exact
                else (
                    f"CLONE {m.clone_matched} (×{m.clone_factor})"
                    if m.clone_matched is not None
                    else "NOT FOUND"
                )
            )
            for m in result.matches
        ]
        raw_response = (
            f"Detected {len(result.detected_amounts)} amounts in text: "
            f"{[str(d.amount) for d in result.detected_amounts]}\n"
            + "\n".join(audit_lines)
        )

        if result.all_found:
            # Every DB amount confirmed verbatim → trust the DB total.
            verified_amount = calculated_amount
            has_discrepancy = False
            success = True
        elif result.any_clone:
            # Text confirms a shifted value → decimal-shift discrepancy.
            verified_amount = result.primary_amount
            has_discrepancy = True
            success = True
        else:
            # Genuine mismatch (or nothing found) → flag it, report what we can.
            verified_amount = result.primary_amount
            has_discrepancy = True
            success = verified_amount is not None

        return {
            "raw_response": raw_response,
            "amount": verified_amount,
            "candidates": result.detected_amounts,
            "input_tokens": None,
            "output_tokens": None,
            "cost_usd": None,
            "success": success,
            "has_discrepancy": has_discrepancy,
        }

    def _call_ai_for_amount(
        self,
        text: str,
        provider: str = "OPENROUTER",
        model: str = "qwen/qwen3.7-flash",
    ) -> dict[str, Any]:
        """
        Call the AI to extract the amount from document text.

        Truncates very long texts to control cost — the financial amount is
        usually near the beginning of Greek government decisions.
        """
        from core.ai_services.factory import get_provider

        # Truncate to control token usage (amount is usually in first ~15k chars)
        max_chars = 15000
        if len(text) > max_chars:
            text = text[:max_chars]
            logger.debug(f"Truncated text to {max_chars} chars for amount verification")

        # Render prompt
        prompt_text = AMOUNT_VERIFICATION_PROMPT_TEMPLATE.replace("{{ text }}", text)

        llm = get_provider(provider, model)
        result = llm.invoke(
            text=prompt_text,
            prompt=AMOUNT_VERIFICATION_SYSTEM_PROMPT,
            temperature=0.0,  # deterministic — we want factual extraction
            max_tokens=50,  # only need a number
        )

        raw_response = (result.get("text") or "").strip()
        parsed = self._parse_amount(raw_response)
        candidates = (
            [
                DetectedAmount(
                    amount=parsed,
                    raw=raw_response.strip()[:50],
                    position=0,
                    near_keyword=True,
                )
            ]
            if parsed is not None
            else []
        )

        return {
            "raw_response": raw_response,
            "amount": parsed,
            "candidates": candidates,
            "input_tokens": result.get("input_tokens"),
            "output_tokens": result.get("output_tokens"),
            "cost_usd": result.get("actual_cost_usd"),
            "success": result.get("success", False),
        }

    def _parse_amount(self, raw: str) -> Decimal | None:
        """
        Parse the AI response into a Decimal amount.

        Handles:
        - Plain numbers: "30000.00"
        - European format: "30.000,00" → 30000.00
        - UNKNOWN → None
        """
        if not raw or raw.upper() == "UNKNOWN":
            return None

        # Strip any currency symbols, whitespace, quotes
        cleaned = raw.strip().strip('"').strip("'").replace("€", "").replace("EUR", "").replace("$", "")
        cleaned = cleaned.strip()

        try:
            # Detect European format: periods as thousand separators, comma as decimal
            if "," in cleaned and "." in cleaned:
                # e.g. "30.000,00" or "30,000.00"
                if cleaned.rfind(",") > cleaned.rfind("."):
                    # Comma is decimal: "30.000,00"
                    cleaned = cleaned.replace(".", "").replace(",", ".")
                else:
                    # Period is decimal: "30,000.00"
                    cleaned = cleaned.replace(",", "")
            elif "," in cleaned and "." not in cleaned:
                # Only commas: could be "30000,00" (decimal) or "30,000" (thousands)
                # Heuristic: if comma followed by exactly 2 digits at end, it's decimal
                if len(cleaned.split(",")[-1]) == 2 and cleaned.rfind(",") > len(cleaned) - 4:
                    cleaned = cleaned.replace(",", ".")
                else:
                    cleaned = cleaned.replace(",", "")
            # else: plain number like "30000.00" or "30000"

            return Decimal(cleaned)
        except Exception:
            logger.warning(f"Could not parse AI amount response: {raw!r}")
            return None

    def _has_significant_discrepancy(
        self,
        text_amount: Decimal,
        calculated_amount: Decimal | None,
        raw_amount: Decimal | None,
        tolerance: Decimal = Decimal("0.05"),  # 5% tolerance
    ) -> bool:
        """
        Determine if the text-detected amount differs significantly from the DB.

        A discrepancy is flagged only when the text amount differs by more than
        *tolerance* (5%) from BOTH the calculated and raw amounts.  If the text
        agrees with either DB value, the decision's own data is consistent with
        the document and no discrepancy is flagged.
        """
        agrees_with_calc = False
        agrees_with_raw = False

        if calculated_amount and calculated_amount > 0:
            ratio = abs(text_amount - calculated_amount) / calculated_amount
            agrees_with_calc = ratio <= tolerance

        if raw_amount and raw_amount > 0:
            ratio = abs(text_amount - raw_amount) / raw_amount
            agrees_with_raw = ratio <= tolerance

        # No usable DB reference → cannot judge, don't flag
        if not (calculated_amount and calculated_amount > 0) and not (
            raw_amount and raw_amount > 0
        ):
            return False

        return not (agrees_with_calc or agrees_with_raw)

    def _build_discrepancy_note(
        self,
        text_amount: Decimal,
        calculated_amount: Decimal | None,
        raw_amount: Decimal | None,
    ) -> str | None:
        """Build a human-readable discrepancy note."""
        parts = [f"Text found: €{text_amount:,.2f}"]
        if calculated_amount is not None:
            parts.append(f"Calculated (DecisionAmountField): €{calculated_amount:,.2f}")
        if raw_amount is not None:
            parts.append(f"Raw (Diavgeia): €{raw_amount:,.2f}")

        # Check for common decimal-shift patterns
        if calculated_amount and calculated_amount > 0:
            ratio = text_amount / calculated_amount
            if 0.009 <= ratio <= 0.011:
                parts.append("[WARN] Text amount is ~100× smaller — possible decimal shift")
            elif 90 <= ratio <= 110 and ratio != 1:
                parts.append("[WARN] Text amount is ~100× larger — possible decimal shift")
            elif 0.09 <= ratio <= 0.11:
                parts.append("[WARN] Text amount is ~10× smaller — possible decimal shift")
            elif 9 <= ratio <= 11 and ratio != 1:
                parts.append("[WARN] Text amount is ~10× larger — possible decimal shift")

        return " | ".join(parts)