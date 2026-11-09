"""
AI text-only counterpart resolver (last resort).

Regex AFM spans + checksum + org exclusion + role keywords decide first.  Only
when that is inconclusive does this resolver ask an OpenRouter model for a
strict JSON answer:

    {"counterpart_afm": "899972873", "role": "person", "confidence": 0.92,
     "evidence": "..."}

Hard validation after parsing:

* the AFM must pass the Greek checksum;
* it must be in the set of AFMs actually detected in the document text
  (so a hallucinated number can never be applied);
* it must not be the issuing org's VAT or the recorded self AFM.

Every call is billed to ``SYSTEM`` with ``trigger="counterpart_recovery"``.
"""

from __future__ import annotations

import json
import os
import re
from decimal import Decimal

from core.ai_services.factory import get_provider
from core.services.cost_ledger_service import CostLedgerService
from core.services.non_monetary_value_guard import collect_org_afm
from core.services.text_processes.afm import is_valid_afm, normalize_afm
from django.conf import settings
from loguru import logger

# Default must be a text model that reliably emits JSON.
DEFAULT_MODEL = os.environ.get(
    "COUNTERPART_RECOVERY_AI_MODEL", "qwen/qwen3.7-flash"
)

# The model never sees the whole document.  It only sees context windows around
# the AFM spans already detected by the annotation process, so a 50-page scan
# stays cheap and a relevant AFM on page 49 is never lost to a head truncation.
CONTEXT_RADIUS = int(
    os.environ.get("COUNTERPART_RECOVERY_AI_CONTEXT_RADIUS", "600")
)
MAX_CONTEXT_WINDOWS = int(
    os.environ.get("COUNTERPART_RECOVERY_AI_MAX_WINDOWS", "12")
)
MAX_CONTEXT_CHARS = int(
    os.environ.get("COUNTERPART_RECOVERY_AI_MAX_CONTEXT_CHARS", "8000")
)
MAX_CONFIDENCE = 0.90

SYSTEM_PROMPT = """You extract the real counterpart VAT number (ΑΦΜ) from a Greek \
public-sector decision. Respond with a single JSON object and nothing else.

Fields:
- "counterpart_afm": a 9-digit Greek ΑΦΜ string, or null when unsure.
- "role": the Diavgeia role if obvious (e.g. "person", "sponsorAFMName"), else null.
- "confidence": number between 0 and 1.
- "evidence": a short verbatim quote from the text.

Rules:
- NEVER return the issuing organization's own VAT number.
- NEVER invent a number; it MUST appear verbatim in the supplied text.
- If multiple candidates are equally plausible, or you are unsure, return
  {"counterpart_afm": null, "confidence": 0, "evidence": ""}.
"""


class AICounterpartResolver:
    """Strict-JSON counterpart resolver over document text."""

    def __init__(self, model: str | None = None):
        self.model = model or DEFAULT_MODEL

    def resolve(
        self,
        *,
        decision,
        text: str,
        detected_afms: set[str],
        recorded_afm: str | None = None,
        candidates: list[dict] | None = None,
    ) -> dict:
        """
        Ask the model for a counterpart AFM and validate the answer.

        Returns a dict with at least:
            status: "ok" | "no_candidate" | "invalid" | "error"
            afm, confidence, evidence, raw_response, provider, model,
            input_tokens, output_tokens, cost_usd, error
        """
        org_afm = collect_org_afm(decision)
        recorded = normalize_afm(recorded_afm)

        user_text = self._build_user_text(
            decision, text, org_afm, recorded, candidates or []
        )

        result = {
            "status": "error",
            "afm": None,
            "confidence": None,
            "evidence": None,
            "raw_response": None,
            "provider": "OPENROUTER",
            "model": self.model,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": Decimal("0"),
            "error": None,
        }

        # Never call the provider (or write an AIInteractionLog) when the
        # deployment has no SYSTEM key.  The caller degrades to NEEDS_REVIEW.
        if not getattr(settings, "OPENROUTER_API_KEY", ""):
            result["status"] = "not_configured"
            result["error"] = "OPENROUTER_API_KEY is not configured"
            return result

        try:
            provider = get_provider("OPENROUTER", self.model)
            response = provider.invoke(
                text=user_text,
                prompt=SYSTEM_PROMPT,
                temperature=0.0,
                max_tokens=400,
            )
        except Exception as exc:
            result["error"] = str(exc)
            logger.error(
                f"AI counterpart resolver failed for decision {decision.id}: {exc}"
            )
            self._log(decision, result, status="FAILED")
            return result

        result["input_tokens"] = response.get("input_tokens", 0) or 0
        result["output_tokens"] = response.get("output_tokens", 0) or 0
        result["cost_usd"] = (
            response.get("actual_cost_usd")
            or response.get("estimated_cost_usd")
            or Decimal("0")
        )

        if not response.get("success"):
            result["error"] = response.get("error") or "provider error"
            self._log(decision, result, status="FAILED")
            return result

        raw = response.get("text") or ""
        result["raw_response"] = raw
        parsed = self._parse_json(raw)
        if parsed is None:
            result["status"] = "invalid"
            result["error"] = "response was not a JSON object"
            self._log(decision, result, status="FAILED")
            return result

        afm = normalize_afm(parsed.get("counterpart_afm"))
        if not afm:
            result["status"] = "no_candidate"
            self._log(decision, result, status="SUCCESS")
            return result

        if (
            not is_valid_afm(afm)
            or afm == org_afm
            or afm == recorded
            or afm not in detected_afms
        ):
            result["status"] = "invalid"
            result["error"] = (
                f"rejected AI AFM {afm}: checksum/org/recorded/text-presence check failed"
            )
            self._log(decision, result, status="SUCCESS")
            return result

        try:
            confidence = float(parsed.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0

        result.update(
            status="ok",
            afm=afm,
            confidence=min(max(confidence, 0.0), MAX_CONFIDENCE),
            evidence=(parsed.get("evidence") or "")[:2000] or None,
        )
        self._log(decision, result, status="SUCCESS")
        return result

    # ------------------------------------------------------------------

    @staticmethod
    def _build_user_text(
        decision, text: str, org_afm: str | None, recorded: str | None,
        candidates: list[dict],
    ) -> str:
        subject = (getattr(decision, "subject", "") or "")[:1000]
        org_name = ""
        org = getattr(decision, "organization", None)
        if org is not None:
            org_name = getattr(org, "label", "") or ""

        candidate_lines = "\n".join(
            f"- {c.get('afm')} (score {c.get('score')}, signals: "
            f"{', '.join(c.get('signals') or []) or 'none'})"
            for c in candidates[:10]
        )

        # Only send the context around annotated AFM spans — never the whole
        # document.  Merge overlapping windows and cap the total size.
        windows: list[tuple[int, int]] = []
        for candidate in candidates[:MAX_CONTEXT_WINDOWS]:
            start = candidate.get("span_start")
            end = candidate.get("span_end")
            if start is None or end is None:
                continue
            window_start = max(0, int(start) - CONTEXT_RADIUS)
            window_end = min(len(text), int(end) + CONTEXT_RADIUS)
            if windows and window_start <= windows[-1][1]:
                windows[-1] = (
                    windows[-1][0],
                    max(windows[-1][1], window_end),
                )
            else:
                windows.append((window_start, window_end))

        snippets: list[str] = []
        consumed = 0
        for window_start, window_end in windows:
            snippet = text[window_start:window_end].strip()
            if not snippet:
                continue
            remaining = MAX_CONTEXT_CHARS - consumed
            if remaining <= 0:
                break
            snippet = snippet[:remaining]
            snippets.append(f"[chars {window_start}-{window_end}]\n{snippet}")
            consumed += len(snippet)

        if not snippets:
            # Defensive fallback (candidates without offsets): a small head is
            # still bounded, unlike the old full-document truncation.
            snippets.append(text[:2000])

        context = "\n\n".join(snippets)

        return (
            f"Subject: {subject}\n"
            f"Issuing organization: {org_name} (VAT {org_afm or 'unknown'})\n"
            f"Recorded counterpart AFM (likely wrong): {recorded or 'none'}\n"
            f"Candidate AFMs found in the text:\n{candidate_lines or '- none'}\n\n"
            f"Relevant context windows:\n{context}"
        )

    @staticmethod
    def _parse_json(raw: str) -> dict | None:
        cleaned = raw.strip()
        # Strip ```json fences that models like to add.
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            value = json.loads(cleaned)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if not match:
                return None
            try:
                value = json.loads(match.group(0))
                return value if isinstance(value, dict) else None
            except json.JSONDecodeError:
                return None

    @staticmethod
    def _log(decision, result: dict, *, status: str) -> None:
        try:
            CostLedgerService.log_interaction(
                user=None,
                billed_to="SYSTEM",
                trigger="counterpart_recovery",
                trigger_ref=f"decision:{decision.id}",
                provider=result.get("provider") or "OPENROUTER",
                model_name=result.get("model") or "",
                input_tokens=result.get("input_tokens") or 0,
                output_tokens=result.get("output_tokens") or 0,
                cost_usd=result.get("cost_usd") or 0,
                status=status,
                error_message=(result.get("error") or None),
            )
        except Exception as exc:  # never let accounting break recovery
            logger.warning(
                f"Failed to log AI counterpart cost for decision {decision.id}: {exc}"
            )
