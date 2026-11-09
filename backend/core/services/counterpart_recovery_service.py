"""
Counterpart recovery service.

The problem: Diavgeia has no validation, and some decisions record the issuing
organization's own VAT number (ΑΦΜ) as the counterpart.  The amount itself is
usually fine — only the relationship is wrong — so amount verification cannot
repair it.  The real counterpart has to be read from the actual document.

Pipeline per decision:

1. Ensure usable text (native, else forced OCR).
2. Correct/validate amounts on the *same* text (best effort).
3. Run the ``afm`` text process and score every checksum-valid, non-org AFM
   with keyword/role/entity/occurrence/proximity signals.
4. Auto-apply one clear winner (≥ 0.85 and no close runner-up) when the apply
   flag is on; otherwise ask the AI resolver; otherwise record NEEDS_REVIEW.
5. Apply atomically by repointing the **same** ``DecisionEntityRelationship``
   row (or merging into an existing target row) and snapshotting the replaced
   state into ``CounterpartRecoveryAttempt``.

The live relationship row always represents the current counterpart, so every
existing stats/rankings/projection query keeps working with no ``is_active``
filter.  Attempt rows are append-only and are the only history.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from decimal import Decimal
from typing import Any

from core.models.counterpart_recovery import (
    CounterpartRecoveryAttempt,
    RecoveryMethod,
    RecoveryStatus,
)
from core.models.decisions import Decision
from core.models.document_analysis import DocumentExtraction, ProcessingStatus
from core.models.entities import (
    AFMEntity,
    DecisionAmountField,
    DecisionEntityRelationship,
    EntityType,
    MetadataSource,
)
from core.services.feature_flag_service import feature_flags
from core.services.non_monetary_value_guard import (
    collect_org_afm,
    collect_recovered_original_afms,
    collect_self_counterparts,
)
from core.services.text_process_service import TextProcessService
from core.services.text_processes.afm import (
    AfmProcess,
    is_valid_afm,
    normalize_afm,
)
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone
from loguru import logger

# Minimum text length before we consider an extraction usable for recovery.
MIN_USABLE_TEXT_CHARS = 50

# Auto-apply requires this score and at least this gap to the runner-up.
AUTO_APPLY_SCORE = 0.85
AUTO_APPLY_GAP = 0.10

DEFAULT_CANDIDATE_LIMIT = 200

# Bump when the recovery decision logic changes materially; a new version makes
# previously skipped inputs eligible for a retry even though the text is the
# same.
RECOVERY_SIGNATURE_VERSION = 2


class CounterpartRecoveryService:
    """Detect and repair self-as-counterpart decisions from document text."""

    # ------------------------------------------------------------------
    # Candidate selection
    # ------------------------------------------------------------------

    def get_candidates(
        self,
        *,
        imported_since: datetime | None = None,
        imported_until: datetime | None = None,
        limit: int = DEFAULT_CANDIDATE_LIMIT,
        ada: str | None = None,
    ) -> list[Decision]:
        """
        Return decisions that still have a self-as-counterpart relationship.

        The limit is applied **before** the queryset is materialised — never
        ``.count()`` an unsliced annotated queryset (the 16h runaway query).

        ``collect_self_counterparts`` is evaluated per decision because it is
        org-VAT-dependent; applied recovery attempts are already subtracted
        there, so recovered decisions do not come back.
        """
        qs = (
            Decision.objects.select_related("organization")
            .prefetch_related("entity_relationships__entity")
            .filter(
                organization__isnull=False,
                entity_relationships__isnull=False,
            )
        )

        if ada:
            qs = qs.filter(ada__iexact=ada)
        else:
            if imported_since is not None:
                qs = qs.filter(created_at__gte=imported_since)
            if imported_until is not None:
                qs = qs.filter(created_at__lt=imported_until)

        qs = qs.distinct().order_by("id")
        if limit:
            qs = qs[:limit]

        return [d for d in qs if collect_self_counterparts(d)]

    # ------------------------------------------------------------------
    # Single decision
    # ------------------------------------------------------------------

    def recover_decision(
        self,
        decision: Decision,
        *,
        apply: bool | None = None,
        allow_ocr: bool = True,
        allow_ai: bool | None = None,
        dry_run: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        Attempt to recover *decision*'s counterpart.

        Args:
            apply: Override ``COUNTERPART_RECOVERY_APPLY_ENABLED``.
            allow_ocr: Allow the forced OCR fallback.
            allow_ai: Override ``COUNTERPART_RECOVERY_AI_ENABLED``.
            dry_run: Score and report without writing anything.
            force: Bypass the master ``COUNTERPART_RECOVERY_ENABLED`` flag.
        """
        if not force and not feature_flags.is_enabled("COUNTERPART_RECOVERY_ENABLED"):
            return {"status": "skipped", "reason": "feature_flag_disabled"}

        if apply is None:
            apply = feature_flags.is_enabled("COUNTERPART_RECOVERY_APPLY_ENABLED")
        if allow_ai is None:
            allow_ai = feature_flags.is_enabled("COUNTERPART_RECOVERY_AI_ENABLED")

        org_afm = collect_org_afm(decision)
        if not org_afm:
            return {"status": "skipped", "reason": "no_org_afm"}

        self_afms = collect_self_counterparts(decision)
        if not self_afms:
            applied = self._latest_applied(decision)
            if applied is not None:
                return {
                    "status": "already_recovered",
                    "attempt_id": applied.id,
                    "chosen_afm": applied.chosen_afm,
                }
            return {"status": "skipped", "reason": "no_self_counterpart"}

        self_rel = self._primary_self_relationship(decision, self_afms)
        if self_rel is None:
            return {"status": "skipped", "reason": "no_relationship_row"}

        # ── Idempotency: same inputs → don't repeat OCR/AI/scoring ────
        # A prior non-applied attempt with the exact same source signature
        # means nothing has changed (text, provider, OCR metadata, flags,
        # model).  A changed OCR provider/text or `--force` makes it eligible
        # again.  APPLIED attempts are handled by the already_recovered path.
        current_extraction = getattr(decision, "text_extraction", None)
        pre_signature = self._source_signature(
            decision,
            org_afm,
            self_afms,
            current_extraction,
            allow_ocr=allow_ocr,
            allow_ai=allow_ai,
            apply=apply,
        )
        if not force:
            prior = self._prior_same_input_attempt(decision, pre_signature)
            if prior is not None:
                return {
                    "status": "skipped",
                    "reason": "same_inputs",
                    "attempt_id": prior.id,
                }

        # ── Ensure text ────────────────────────────────────────────────
        extraction, text = self._ensure_text(
            decision, org_afm, allow_ocr=allow_ocr
        )

        source_signature = self._source_signature(
            decision,
            org_afm,
            self_afms,
            extraction,
            allow_ocr=allow_ocr,
            allow_ai=allow_ai,
            apply=apply,
        )
        if not force and source_signature != pre_signature:
            prior = self._prior_same_input_attempt(
                decision, source_signature
            )
            if prior is not None:
                return {
                    "status": "skipped",
                    "reason": "same_inputs",
                    "attempt_id": prior.id,
                }

        if not text or not self._has_usable_text(text, org_afm):
            if dry_run:
                return {"status": "no_usable_text", "dry_run": True}
            attempt = self._create_attempt(
                decision,
                extraction,
                self_rel,
                method=RecoveryMethod.REGEX_OCR,
                status=RecoveryStatus.NEEDS_REVIEW,
                error_message="No usable text (OCR unavailable or unreadable).",
                evidence={"reason": "no_usable_text"},
                run_signature=source_signature,
            )
            return {"status": "needs_review", "reason": "no_usable_text", "attempt_id": attempt.id}

        # ── Correct amounts on the same text (best effort) ────────────
        try:
            from core.services.amount_correction_service import (
                AmountCorrectionService,
            )

            AmountCorrectionService().correct_decision(
                decision, read_if_missing=False
            )
        except Exception as exc:
            logger.warning(
                f"Counterpart recovery: amount correction failed for "
                f"{decision.ada}: {exc}"
            )

        # ── Detect + score AFM candidates ─────────────────────────────
        spans = self._run_afm_process(decision, extraction, org_afm)
        entities = {
            e.afm: e
            for e in AFMEntity.objects.filter(
                afm__in={s.value.get("afm") for s in spans if s.value.get("afm")}
            )
        }
        candidates = self._score_candidates(
            spans, text, org_afm, self_afms, entities
        )

        chosen: dict | None = None
        method = RecoveryMethod.REGEX_OCR
        ai_result: dict | None = None
        ambiguous = False

        if candidates:
            top = candidates[0]
            runner = candidates[1] if len(candidates) > 1 else None
            if top["score"] >= AUTO_APPLY_SCORE and (
                runner is None or top["score"] - runner["score"] >= AUTO_APPLY_GAP
            ):
                chosen = top
            else:
                ambiguous = True

        if chosen is None and allow_ai:
            # No annotated AFM → nothing the AI could validly return (we
            # require the answer to appear in the text), so don't spend a call.
            detected_in_text = {
                s.value.get("afm")
                for s in spans
                if s.value.get("afm") and s.value.get("afm") != org_afm
            }
            if detected_in_text:
                ai_result = self._resolve_with_ai(
                    decision, text, org_afm, self_rel, spans, candidates
                )
            if ai_result and ai_result.get("status") == "ok":
                chosen = {
                    "afm": ai_result["afm"],
                    "score": ai_result["confidence"],
                    "signals": ["ai_text_resolver"],
                }
                method = RecoveryMethod.AI_TEXT

        if dry_run:
            return {
                "status": "would_apply" if chosen else "needs_review",
                "dry_run": True,
                "chosen_afm": chosen["afm"] if chosen else None,
                "confidence": chosen["score"] if chosen else None,
                "method": method.value,
                "candidates": candidates[:10],
                "ambiguous": ambiguous,
                "ai": bool(ai_result),
            }

        if chosen is None:
            status = (
                RecoveryStatus.NEEDS_REVIEW
                if candidates
                else RecoveryStatus.NO_CANDIDATE
            )
            attempt = self._create_attempt(
                decision,
                extraction,
                self_rel,
                method=(
                    RecoveryMethod.AI_TEXT
                    if self._ai_attempted(ai_result)
                    else RecoveryMethod.REGEX_OCR
                ),
                status=status,
                confidence=(candidates[0]["score"] if candidates else None),
                candidate_afms=candidates,
                evidence={
                    "ambiguous": ambiguous,
                    "ai": ai_result,
                },
                ocr_provider=(extraction.ocr_metadata or {}).get("provider")
                if extraction
                else None,
                ocr_confidence=extraction.ocr_confidence if extraction else None,
                run_signature=source_signature,
                **(self._ai_attempt_fields(ai_result)),
            )
            return {
                "status": "needs_review" if candidates else "no_candidate",
                "attempt_id": attempt.id,
                "candidates": candidates[:10],
            }

        if not apply:
            attempt = self._create_attempt(
                decision,
                extraction,
                self_rel,
                method=method,
                status=RecoveryStatus.NEEDS_REVIEW,
                chosen_afm=chosen["afm"],
                confidence=chosen["score"],
                candidate_afms=candidates,
                evidence={"report_only": True, "ai": ai_result},
                run_signature=source_signature,
                **(self._ai_attempt_fields(ai_result)),
            )
            return {
                "status": "needs_review",
                "reason": "apply_disabled",
                "attempt_id": attempt.id,
                "chosen_afm": chosen["afm"],
                "confidence": chosen["score"],
            }

        try:
            attempt = self._apply(
                decision=decision,
                self_rel=self_rel,
                chosen=chosen,
                candidates=candidates,
                extraction=extraction,
                spans=spans,
                method=method,
                ai_result=ai_result,
                text=text,
                source_signature=source_signature,
            )
        except Exception as exc:
            logger.exception(
                f"Counterpart recovery failed for decision {decision.id} "
                f"({decision.ada}): {exc}"
            )
            failed = self._create_attempt(
                decision,
                extraction,
                self_rel,
                method=method,
                status=RecoveryStatus.FAILED,
                chosen_afm=chosen["afm"],
                confidence=chosen["score"],
                candidate_afms=candidates,
                error_message=str(exc)[:2000],
                run_signature=source_signature,
            )
            return {
                "status": "failed",
                "attempt_id": failed.id,
                "error": str(exc),
            }

        return {
            "status": "recovered",
            "attempt_id": attempt.id,
            "chosen_afm": chosen["afm"],
            "confidence": chosen["score"],
            "method": method.value,
        }

    # ------------------------------------------------------------------
    # Text helpers
    # ------------------------------------------------------------------

    def _ensure_text(
        self, decision: Decision, org_afm: str, *, allow_ocr: bool
    ) -> tuple[DocumentExtraction | None, str]:
        extraction = getattr(decision, "text_extraction", None)
        text = self._usable_extraction_text(extraction)
        if self._has_usable_text(text, org_afm):
            return extraction, text

        if not allow_ocr:
            return extraction, text

        # Deliberately force OCR for self-counterpart decisions whose native
        # text is present but useless/garbled — not only for empty text.
        try:
            from core.tasks.tasks_decision_ai import extract_decision_text

            extract_decision_text(decision.id, force=True, allow_ocr=True)
            decision.refresh_from_db()
            extraction = getattr(decision, "text_extraction", None)
            text = self._usable_extraction_text(extraction)
        except Exception as exc:
            logger.warning(
                f"Counterpart recovery: forced OCR failed for {decision.ada}: {exc}"
            )
        return extraction, text

    @staticmethod
    def _usable_extraction_text(extraction: DocumentExtraction | None) -> str:
        if extraction is None:
            return ""
        if extraction.extraction_status != ProcessingStatus.COMPLETED:
            return ""
        return extraction.raw_text or ""

    @staticmethod
    def _has_usable_text(text: str, org_afm: str) -> bool:
        if len((text or "").strip()) < MIN_USABLE_TEXT_CHARS:
            return False
        result = AfmProcess().detect(text, org_afm=org_afm)
        return any(s.value.get("afm") != org_afm for s in result.spans)

    def _run_afm_process(
        self, decision: Decision, extraction: DocumentExtraction, org_afm: str
    ):
        """Run ``afm`` twice: once to discover AFMs, once enriched."""
        service = TextProcessService()
        first = service.run_process(
            extraction, "afm", force=True, params={"org_afm": org_afm}
        )
        afms = {
            s.value.get("afm")
            for s in first.spans.all()
            if s.value.get("afm")
        }
        entities = AFMEntity.objects.filter(afm__in=afms)
        params = {
            "org_afm": org_afm,
            "known_afms": {e.afm for e in entities},
            "seen_counts": {e.afm: e.total_appearances for e in entities},
        }
        run = service.run_process(extraction, "afm", force=True, params=params)
        return list(run.spans.all())

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_candidates(
        self,
        spans,
        text: str,
        org_afm: str,
        self_afms: set[str],
        entities: dict[str, AFMEntity],
    ) -> list[dict]:
        by_afm: dict[str, list] = {}
        for span in spans:
            afm = normalize_afm(span.value.get("afm"))
            if not afm or afm == org_afm or afm in self_afms:
                continue
            if not is_valid_afm(afm):
                continue
            by_afm.setdefault(afm, []).append(span)

        # A document with exactly one checksum-valid, non-org AFM is a very
        # strong signal when that AFM sits next to the "ΑΦΜ" label: the
        # recorded counterpart was the org itself, so the only other AFM on
        # the page is the real counterpart.  This lets the common
        # "εταιρεία ... με ΑΦΜ: ..." case auto-apply without an AI key; two or
        # more candidates remain ambiguous and go to the AI/needs-review path.
        single_candidate = len(by_afm) == 1

        scored: list[dict] = []
        for afm, occurrences in by_afm.items():
            score = 0.35
            signals: list[str] = []
            near_keyword = any(
                s.value.get("near_keyword") for s in occurrences
            )

            if near_keyword:
                score += 0.25
                signals.append("near_afm_keyword")

            if single_candidate and near_keyword:
                score += 0.25
                signals.append("only_candidate")

            role_keywords = sorted(
                {
                    kw
                    for s in occurrences
                    for kw in (s.value.get("role_keywords") or [])
                }
            )
            if role_keywords:
                score += min(0.20, 0.05 * len(role_keywords))
                signals.extend(f"role:{kw}" for kw in role_keywords)

            entity = entities.get(afm)
            if entity is not None:
                score += 0.15
                signals.append("known_entity")
                if entity.name:
                    score += 0.05
                    signals.append("entity_name_available")
                if (entity.total_appearances or 0) > 1:
                    score += 0.05
                    signals.append("multiple_appearances")

            if len(occurrences) > 1:
                score += 0.05
                signals.append("multiple_occurrences")

            first = min(occurrences, key=lambda s: s.start)
            if self._near_amount(text, first.start):
                score += 0.05
                signals.append("near_amount")

            scored.append(
                {
                    "afm": afm,
                    "score": min(round(score, 3), 0.99),
                    "signals": signals,
                    "occurrences": len(occurrences),
                    "span_start": first.start,
                    "span_end": first.end,
                    "span_text": first.text_snippet,
                }
            )

        scored.sort(key=lambda c: (-c["score"], c["afm"]))
        return scored

    @staticmethod
    def _near_amount(text: str, position: int, window: int = 120) -> bool:
        from core.services.grouped_amount_detection import (
            extract_grouped_amounts,
        )

        return any(
            abs(a.position - position) <= window
            for a in extract_grouped_amounts(text)
        )

    # ------------------------------------------------------------------
    # AI resolution
    # ------------------------------------------------------------------

    def _resolve_with_ai(
        self,
        decision: Decision,
        text: str,
        org_afm: str,
        self_rel: DecisionEntityRelationship,
        spans,
        candidates: list[dict],
    ) -> dict | None:
        try:
            from core.services.ai_counterpart_resolver import AICounterpartResolver

            detected = {
                s.value.get("afm")
                for s in spans
                if s.value.get("afm") and s.value.get("afm") != org_afm
            }
            return AICounterpartResolver().resolve(
                decision=decision,
                text=text,
                detected_afms=detected,
                recorded_afm=self_rel.entity.afm,
                candidates=candidates,
            )
        except Exception as exc:
            logger.warning(
                f"Counterpart recovery: AI resolver failed for {decision.ada}: {exc}"
            )
            return None

    @staticmethod
    def _ai_attempted(ai_result: dict | None) -> bool:
        """Whether an AI call was actually attempted (not just unavailable)."""
        return bool(ai_result) and ai_result.get("status") != "not_configured"

    @staticmethod
    def _ai_attempt_fields(ai_result: dict | None) -> dict:
        if not ai_result or ai_result.get("status") == "not_configured":
            return {}
        return {
            "provider": ai_result.get("provider"),
            "model": ai_result.get("model"),
            "cost_usd": ai_result.get("cost_usd"),
            "input_tokens": ai_result.get("input_tokens"),
            "output_tokens": ai_result.get("output_tokens"),
        }

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def _apply(
        self,
        *,
        decision: Decision,
        self_rel: DecisionEntityRelationship,
        chosen: dict,
        candidates: list[dict],
        extraction: DocumentExtraction | None,
        spans,
        method: RecoveryMethod,
        ai_result: dict | None,
        text: str,
        source_signature: str,
    ) -> CounterpartRecoveryAttempt:
        afm = chosen["afm"]
        source_span = next(
            (s for s in spans if s.value.get("afm") == afm), None
        )

        with transaction.atomic():
            # Snapshot the row we are about to change BEFORE touching it.
            attempt = self._create_attempt(
                decision,
                extraction,
                self_rel,
                method=method,
                status=RecoveryStatus.APPLIED,
                chosen_afm=afm,
                confidence=chosen["score"],
                candidate_afms=candidates,
                span_start=source_span.start if source_span else None,
                span_end=source_span.end if source_span else None,
                span_text=source_span.text_snippet if source_span else None,
                evidence={
                    "signals": chosen.get("signals") or [],
                    "ai": ai_result,
                    "near_amount": self._near_amount(text, source_span.start)
                    if source_span
                    else False,
                },
                ocr_provider=(extraction.ocr_metadata or {}).get("provider")
                if extraction
                else None,
                ocr_confidence=extraction.ocr_confidence if extraction else None,
                run_signature=source_signature,
                completed_at=timezone.now(),
                **(self._ai_attempt_fields(ai_result)),
            )

            target, created = AFMEntity.objects.select_for_update().get_or_create(
                afm=afm,
                defaults={
                    "entity_type": EntityType.UNKNOWN,
                    "name": None,
                    "total_appearances": 1,
                },
            )
            if not created:
                target.last_seen = timezone.now()
                target.total_appearances = (target.total_appearances or 0) + 1
                target.save(update_fields=["last_seen", "total_appearances"])

            provenance = {
                "is_inferred": True,
                "metadata_source": (
                    MetadataSource.AI_TEXT
                    if method == RecoveryMethod.AI_TEXT
                    else MetadataSource.OCR_AFM
                ),
                "confidence_score": chosen["score"],
                "source_extraction": extraction,
                "source_span": source_span,
            }

            existing_target = (
                DecisionEntityRelationship.objects.filter(
                    decision=decision,
                    entity=target,
                    role=self_rel.role,
                    parent_key_path=self_rel.parent_key_path,
                )
                .exclude(pk=self_rel.pk)
                .first()
            )

            if existing_target is not None:
                # Rare edge case: the target already has a relationship for
                # the same role/path.  Merge amount links into it, then remove
                # the self row (the attempt snapshot preserves the old state).
                DecisionAmountField.objects.filter(
                    associated_relationship=self_rel
                ).update(associated_relationship=existing_target)
                for field, value in provenance.items():
                    setattr(existing_target, field, value)
                existing_target.save(update_fields=list(provenance))
                live_rel = existing_target
                self_rel.delete()
                # The FK is SET_NULL; clear the in-memory object too, otherwise
                # saving the attempt trips Django's unsaved-related-object
                # guard.  The snapshot columns already preserve the old state.
                attempt.original_relationship = None
            else:
                self_rel.entity = target
                for field, value in provenance.items():
                    setattr(self_rel, field, value)
                self_rel.save(
                    update_fields=["entity", *provenance.keys()]
                )
                live_rel = self_rel

            # Only create an amount row when the decision has none at all and
            # the text actually reveals a cents-bearing amount.  The existing
            # awardAmount row (final-boss case) stays linked and untouched.
            if not DecisionAmountField.objects.filter(
                associated_relationship=live_rel
            ).exists() and not decision.amount_fields.exists():
                amount = self._detect_text_amount(text, source_span)
                if amount is not None:
                    DecisionAmountField.objects.create(
                        decision=decision,
                        parent_key_path="recovered_counterpart",
                        source_field_name="recoveredAmount",
                        amount=amount,
                        currency="EUR",
                        structure_type="other",
                        raw_context={"recovered_from_text": True},
                        associated_relationship=live_rel,
                    )

            attempt.new_relationship = live_rel
            attempt.save(
                update_fields=[
                    "original_relationship",
                    "new_relationship",
                    "completed_at",
                ]
            )

            logger.info(
                f"Counterpart recovered for decision {decision.id} "
                f"({decision.ada}): {attempt.original_afm} → {afm} "
                f"({method.value}, confidence={chosen['score']})"
            )

            try:
                from core.tasks.tasks_entities import (
                    fetch_company_data_for_single_afm,
                )

                transaction.on_commit(
                    lambda: fetch_company_data_for_single_afm.delay(afm)
                )
            except Exception:
                pass

            return attempt

    @staticmethod
    def _detect_text_amount(text: str, span) -> Decimal | None:
        from core.services.grouped_amount_detection import (
            extract_grouped_amounts,
        )

        amounts = extract_grouped_amounts(text)
        if not amounts:
            return None
        pivot = span.start if span is not None else 0
        nearest = min(amounts, key=lambda a: abs(a.position - pivot))
        return nearest.amount

    # ------------------------------------------------------------------
    # Attempt helpers
    # ------------------------------------------------------------------

    def _primary_self_relationship(
        self, decision: Decision, self_afms: set[str]
    ) -> DecisionEntityRelationship | None:
        return (
            DecisionEntityRelationship.objects.filter(
                decision=decision, entity__afm__in=self_afms
            )
            .select_related("entity")
            .annotate(
                has_amount=Exists(
                    DecisionAmountField.objects.filter(
                        associated_relationship=OuterRef("pk")
                    )
                )
            )
            .order_by("-has_amount", "id")
            .first()
        )

    @staticmethod
    def _source_signature(
        decision: Decision,
        org_afm: str,
        self_afms: set[str],
        extraction: DocumentExtraction | None,
        *,
        allow_ocr: bool,
        allow_ai: bool,
        apply: bool,
    ) -> str:
        """
        Fingerprint every input that can change the recovery outcome.

        Any difference (new text, OCR provider/lang/DPI, apply/AI flags, AI
        model, algorithm version, org/self AFMs) produces a new signature and
        makes the decision eligible for another attempt.  Identical inputs
        reuse the prior non-applied attempt instead of paying OCR/AI again.
        """
        text = (extraction.raw_text or "") if extraction else ""
        text_hash = (
            hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""
        )
        ocr_metadata = (extraction.ocr_metadata or {}) if extraction else {}
        payload = {
            "version": RECOVERY_SIGNATURE_VERSION,
            "decision_id": decision.id,
            "org_afm": org_afm,
            "self_afms": sorted(self_afms),
            "extraction_id": extraction.id if extraction else None,
            "extraction_provider": (
                extraction.extraction_provider if extraction else None
            ),
            "extraction_status": (
                extraction.extraction_status if extraction else None
            ),
            "text_hash": text_hash,
            "ocr_provider": ocr_metadata.get("provider"),
            "ocr_lang": ocr_metadata.get("lang"),
            "ocr_dpi": ocr_metadata.get("dpi"),
            # Current runtime OCR config, not just what the last extraction
            # recorded: changing the provider settings must invalidate the
            # skip guard even before a new extraction runs.
            "ocr_config_lang": os.environ.get("OCR_LANG", ""),
            "ocr_config_dpi": os.environ.get("OCR_DPI", ""),
            "ocr_config_psm": os.environ.get("OCR_PSM", ""),
            "allow_ocr": allow_ocr,
            "allow_ai": allow_ai,
            "apply": apply,
            "ocr_feature": feature_flags.is_enabled("DOCUMENT_OCR_ENABLED"),
            "ai_model": os.environ.get(
                "COUNTERPART_RECOVERY_AI_MODEL", ""
            ),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _prior_same_input_attempt(
        decision: Decision, signature: str
    ) -> CounterpartRecoveryAttempt | None:
        return (
            CounterpartRecoveryAttempt.objects.filter(
                decision=decision,
                evidence__run_signature=signature,
            )
            .exclude(status=RecoveryStatus.APPLIED)
            .order_by("-created_at", "-id")
            .first()
        )

    @staticmethod
    def _latest_applied(decision: Decision) -> CounterpartRecoveryAttempt | None:
        return (
            CounterpartRecoveryAttempt.objects.filter(
                decision=decision, status=RecoveryStatus.APPLIED
            )
            .order_by("-created_at", "-id")
            .first()
        )

    @classmethod
    def _json_safe(cls, value):
        """Make evidence JSON serializable (Decimal → str, unknown → str)."""
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, dict):
            return {str(k): cls._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [cls._json_safe(v) for v in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    def _create_attempt(
        self,
        decision: Decision,
        extraction: DocumentExtraction | None,
        self_rel: DecisionEntityRelationship | None,
        *,
        method: RecoveryMethod,
        status: RecoveryStatus,
        chosen_afm: str | None = None,
        confidence: float | None = None,
        candidate_afms: list[dict] | None = None,
        span_start: int | None = None,
        span_end: int | None = None,
        span_text: str | None = None,
        evidence: dict | None = None,
        ocr_provider: str | None = None,
        ocr_confidence: float | None = None,
        error_message: str | None = None,
        completed_at=None,
        provider: str | None = None,
        model: str | None = None,
        cost_usd=None,
        input_tokens=None,
        output_tokens=None,
        run_signature: str | None = None,
    ) -> CounterpartRecoveryAttempt:
        entity = getattr(self_rel, "entity", None) if self_rel else None
        evidence = dict(evidence or {})
        if run_signature:
            evidence["run_signature"] = run_signature
        return CounterpartRecoveryAttempt.objects.create(
            decision=decision,
            extraction=extraction,
            method=method,
            status=status,
            provider=provider,
            model=model,
            candidate_afms=[
                {
                    "afm": c.get("afm"),
                    "score": c.get("score"),
                    "signals": c.get("signals") or [],
                }
                for c in (candidate_afms or [])[:20]
            ],
            chosen_afm=chosen_afm,
            confidence=confidence,
            original_relationship=self_rel,
            original_afm=(getattr(entity, "afm", None) if entity else None),
            original_entity_id=(entity.id if entity else None),
            original_entity_name=(getattr(entity, "name", None) if entity else None),
            original_role=(self_rel.role if self_rel else None),
            original_parent_key_path=(
                self_rel.parent_key_path if self_rel else None
            ),
            original_source_field_name=(
                self_rel.source_field_name if self_rel else None
            ),
            original_raw_context=(
                self_rel.raw_context if self_rel else None
            ),
            previous_confidence=(
                self_rel.confidence_score if self_rel else None
            ),
            span_start=span_start,
            span_end=span_end,
            span_text=span_text,
            evidence=self._json_safe(evidence or {}),
            ocr_provider=ocr_provider,
            ocr_confidence=ocr_confidence,
            cost_usd=cost_usd,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error_message=error_message,
            completed_at=completed_at,
        )

    # ------------------------------------------------------------------
    # Re-import guard
    # ------------------------------------------------------------------

    @staticmethod
    def suppressed_original_afms(decision: Decision) -> set[str]:
        """AFMs that applied recovery attempts replaced (skip on re-import)."""
        return collect_recovered_original_afms(decision)
