"""
Diavgeia Feedback Service

Reports decisions whose metadata amounts were corrected (wrong amounts
detected in the document text — see ``AmountCorrectionService``) back to the
Diavgeia admins via the public feedback endpoint:

    POST https://diavgeia.gov.gr/luminapi/api/feedback/new
    {"documentId": "<ADA>", "reporterEmail": "...",
     "feedBackErrors": ["FE_1"], "reporter": null}

The ``documentId`` is the decision's ADA.  On success the API returns a
message containing a reference number, which we store on a
``DiavgeiaFeedbackReport`` row (one per decision — no ``Decision`` bloat)
along with the raw response, and flip ``reported`` / ``reported_at``.

Usage:
    svc = DiavgeiaFeedbackService()
    result = svc.report_decision(decision)          # single decision
    summary = svc.report_pending(limit=100)         # batch over unreported
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import quote

import requests
from django.conf import settings
from django.db.models import Exists, OuterRef
from django.utils import timezone
from loguru import logger


class DiavgeiaFeedbackService:
    """
    Report wrong-amount decisions to the Diavgeia feedback API.
    """

    def __init__(
        self,
        reporter_email: str | None = None,
        feedback_errors: list[str] | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
    ):
        self.reporter_email = reporter_email or getattr(
            settings, "DIAVGEIA_FEEDBACK_REPORTER_EMAIL", "voulkon93@gmail.com"
        )
        self.feedback_errors = feedback_errors or getattr(
            settings, "DIAVGEIA_FEEDBACK_ERRORS", ["FE_1"]
        )
        self.base_url = base_url or getattr(
            settings,
            "DIAVGEIA_FEEDBACK_URL",
            "https://diavgeia.gov.gr/luminapi/api/feedback/new",
        )
        self.timeout = timeout or getattr(settings, "DIAVGEIA_FEEDBACK_TIMEOUT", 30)

    # ------------------------------------------------------------------
    # Candidate query
    # ------------------------------------------------------------------

    def pending_decisions(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ):
        """
        Decisions that have at least one corrected (verified) amount and have
        NOT yet been reported to Diavgeia.  These are the candidates for the
        feedback control panel.

        "Not reported" means either no ``DiavgeiaFeedbackReport`` row exists,
        or one exists with ``reported=False``.
        """
        from core.models.decisions import Decision
        from core.models.diavgeia_feedback_report import DiavgeiaFeedbackReport
        from core.models.entities import DecisionAmountField

        has_corrected = Exists(
            DecisionAmountField.objects.filter(
                decision=OuterRef("pk"), verified_amount__isnull=False
            )
        )
        already_reported = Exists(
            DiavgeiaFeedbackReport.objects.filter(
                decision=OuterRef("pk"), reported=True
            )
        )
        qs = (
            Decision.objects
            .filter(has_corrected)
            .exclude(already_reported)
            .order_by("-issue_date")
        )
        if start_date:
            qs = qs.filter(issue_date_day__gte=start_date)
        if end_date:
            qs = qs.filter(issue_date_day__lte=end_date)
        return qs

    # ------------------------------------------------------------------
    # Single-decision reporting
    # ------------------------------------------------------------------

    def report_decision(
        self,
        decision,
        *,
        dry_run: bool = False,
        reporter_email: str | None = None,
        feedback_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Report a single decision to the Diavgeia feedback API.

        Args:
            decision: The Decision to report.
            dry_run: If True, build the payload but do NOT send it.
            reporter_email: Override the reporter email (defaults to settings).
            feedback_errors: Override the feedBackErrors codes.

        Returns:
            Dict with status ("reported" / "would_report" /
            "already_reported" / "error"), reference (if any), and response.
        """
        from core.models.decisions import Decision
        from core.models.diavgeia_feedback_report import DiavgeiaFeedbackReport

        if not isinstance(decision, Decision) or not decision.ada:
            return {"status": "error", "reason": "invalid_decision"}

        email = reporter_email or self.reporter_email
        errors = feedback_errors or self.feedback_errors

        report = getattr(decision, "diavgeia_feedback_report", None)
        if report and report.reported:
            return {
                "status": "already_reported",
                "reference": report.reference or "",
                "response": report.response or "",
                "reported_at": report.reported_at,
            }

        payload = {
            "documentId": decision.ada,
            "reporterEmail": email,
            "feedBackErrors": errors,
            "reporter": None,
        }

        if dry_run:
            return {
                "status": "would_report",
                "payload": payload,
                "decision_id": decision.id,
                "ada": decision.ada,
            }

        # ── Send the request ──────────────────────────────────────────
        try:
            # NB: headers are encoded as latin-1 by http.client, so the ADA
            # (which may contain Greek letters, e.g. "62ΧΘ469069-3ΨΨ") MUST be
            # percent-encoded in the Referer — exactly like the browser does
            # (https://diavgeia.gov.gr/decision/view/62%CE%A7%CE%98469069-3%CE%A8%CE%A8).
            # The JSON body is UTF-8, so documentId stays raw.
            referer = f"https://diavgeia.gov.gr/decision/view/{quote(decision.ada)}"
            resp = requests.post(
                self.base_url,
                json=payload,
                timeout=self.timeout,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/json;charset=utf-8",
                    "Origin": "https://diavgeia.gov.gr",
                    "Referer": referer,
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; "
                        "rv:153.0) Gecko/20100101 Firefox/153.0"
                    ),
                },
            )
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError:
                data = {"raw": resp.text}
        except requests.RequestException as exc:
            logger.warning(
                f"DiavgeiaFeedback: report failed for {decision.ada}: {exc}"
            )
            return {
                "status": "error",
                "reason": str(exc)[:255],
                "decision_id": decision.id,
                "ada": decision.ada,
            }

        ok = data.get("ok", False) or data.get("status", "") == "(OK)OK"
        reference = self._extract_reference(data.get("msg", ""))

        # ── Get or create the report row ──────────────────────────────
        report, _ = DiavgeiaFeedbackReport.objects.get_or_create(
            decision=decision
        )

        if not ok:
            logger.warning(
                f"DiavgeiaFeedback: API returned not-ok for {decision.ada}: {data}"
            )
            report.mark_failed(response=self._json_text(data), reporter_email=email)
            return {
                "status": "error",
                "reason": data.get("msg", "api_not_ok")[:255],
                "response": self._json_text(data),
                "decision_id": decision.id,
                "ada": decision.ada,
            }

        # ── Persist the report state ─────────────────────────────────
        report.mark_reported(
            reference=reference,
            response=self._json_text(data),
            reporter_email=email,
            feedback_errors=errors,
        )

        logger.info(
            f"DiavgeiaFeedback: reported {decision.ada} "
            f"(reference={reference or 'n/a'})"
        )
        return {
            "status": "reported",
            "reference": reference,
            "response": self._json_text(data),
            "decision_id": decision.id,
            "ada": decision.ada,
        }

    # ------------------------------------------------------------------
    # Batch reporting
    # ------------------------------------------------------------------

    def report_pending(
        self,
        *,
        limit: int | None = None,
        dry_run: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
        reporter_email: str | None = None,
        feedback_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Report all pending (unreported, corrected) decisions.

        Args:
            limit: Optional cap on how many decisions to process.
            dry_run: If True, only report what WOULD be sent.
            start_date / end_date: Optional issue-date bounds.
            reporter_email / feedback_errors: Overrides for the payload.

        Returns:
            Summary dict with counts and per-decision results.
        """
        candidates = self.pending_decisions(
            start_date=start_date, end_date=end_date
        )
        total = candidates.count()
        if limit:
            candidates = candidates[:limit]

        reported = 0
        already = 0
        errors = 0
        results: list[dict[str, Any]] = []
        for decision in candidates:
            try:
                result = self.report_decision(
                    decision,
                    dry_run=dry_run,
                    reporter_email=reporter_email,
                    feedback_errors=feedback_errors,
                )
                status = result["status"]
                if status == "reported":
                    reported += 1
                elif status == "already_reported":
                    already += 1
                else:
                    errors += 1
                results.append(result)
            except Exception as exc:
                logger.error(
                    f"DiavgeiaFeedback failed for decision {decision.id}: {exc}",
                    exc_info=True,
                )
                errors += 1
                results.append({
                    "status": "error",
                    "reason": str(exc)[:255],
                    "decision_id": decision.id,
                    "ada": decision.ada,
                })

        summary = {
            "total_candidates": total,
            "reported": reported,
            "already_reported": already,
            "errors": errors,
            "dry_run": dry_run,
            "results": results,
        }
        logger.info(f"DiavgeiaFeedback batch complete: {summary}")
        return summary

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def frontend_url(decision) -> str:
        """Return the frontend page URL for a decision."""
        from django.conf import settings

        base = (
            settings.FRONTEND_DOMAINS_clean[0]
            if getattr(settings, "FRONTEND_DOMAINS_clean", None)
            else "http://localhost:3000"
        )
        return f"{base}/decision/{decision.id}"

    @staticmethod
    def _extract_reference(msg: str) -> str:
        """
        Pull the reference number out of the API message.

        The API returns something like:
          "Η επισήμανση καταχωρήθηκε με αριθμό αναφοράς: 6a78b06a4ab4cce30ab3fd6b. ..."
        """
        if not msg:
            return ""
        match = re.search(
            r"αριθμ[όο] αναφορ[άα]ς\s*:\s*([0-9a-fA-F-]{8,})", msg
        )
        if match:
            return match.group(1)
        # Fallback: any long hex token in the message
        match = re.search(r"\b([0-9a-fA-F]{16,})\b", msg)
        return match.group(1) if match else ""

    @staticmethod
    def _json_text(data: Any) -> str:
        """Render the API response as a compact string for storage."""
        import json

        try:
            return json.dumps(data, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(data)


# Singleton instance for easy importing
feedback_service = DiavgeiaFeedbackService()
