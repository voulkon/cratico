"""
ExtractStep — reads document text for each decision in the context.

By default reads the existing ``DocumentExtraction.raw_text`` (cached PyMuPDF
output).  If ``config.re_extract = true``, calls the configured extractor
via ``ProviderRegistry`` (future; currently only reads cached text).

Config:
    extractor: "PYMUPDF" (default) — which extractor to use for re-extraction
    re_extract: false (default) — if true, re-extract instead of reading cache
    max_pages: null — optional page cap
    max_chars: 50000 — optional truncation

Provenance: for model-instance decisions the id of the exact
``DocumentExtraction`` row the text came from is recorded in
``context.metadata["item_extractions"]`` ({item_id: extraction_id or None})
so downstream steps (e.g. the one-liner cache in ``AICallStep``) can pin
generation to the extraction snapshot.  ``None`` marks the subject-fallback
path; dict decisions are skipped.
"""

from core.models.pipeline import PipelineStepRun
from core.services.pipeline_engine import PipelineContext
from loguru import logger

MAX_CHARS_DEFAULT = 50000


class ExtractStep:
    """Extracts raw text for each decision in the pipeline context."""

    def execute(self, step, step_run: PipelineStepRun, context: PipelineContext, run):
        config = step.config or {}
        max_chars = config.get("max_chars", MAX_CHARS_DEFAULT)
        re_extract = config.get("re_extract", False)

        texts = {}
        extractions = {}  # item_id -> extraction id (None = subject fallback)
        for decision in context.decisions:
            if isinstance(decision, dict):
                item_id = str(decision.get("id", ""))
                text = self._get_decision_text(decision, re_extract=re_extract)
            else:
                item_id = str(decision.pk)
                text, extraction = self._get_decision_text_with_extraction(
                    decision, re_extract=re_extract
                )
                extractions[item_id] = (
                    extraction.pk if extraction is not None else None
                )
            if max_chars and len(text) > max_chars:
                text = text[:max_chars]
            texts[item_id] = text

        # Store in context for downstream steps
        context.per_item_outputs = texts
        if extractions:
            context.metadata["item_extractions"] = extractions
        context.steps_output[step.order] = "\n---\n".join(texts.values())

        # Store a truncated preview on the step run
        preview = context.steps_output[step.order]
        step_run.input_preview = preview[:2000] if preview else ""
        step_run.output_text = preview[:2000] if preview else ""
        step_run.save()

        logger.info(
            f"ExtractStep: extracted text for {len(texts)} decisions "
            f"(total chars: {sum(len(t) for t in texts.values())})"
        )

    def _get_decision_text(self, decision, re_extract: bool = False) -> str:
        """Get the raw text for a single decision (text only)."""
        return self._get_decision_text_with_extraction(decision, re_extract)[0]

    def _get_decision_text_with_extraction(self, decision, re_extract: bool = False):
        """Get the raw text for a single decision and the extraction row it
        came from (``(text, extraction_or_None)``).

        Resolution order:
        1. Cached ``DocumentExtraction.raw_text`` (unless ``re_extract``)
        2. On-demand extraction via ``DocumentAnalysisService``
        3. Decision subject as a clearly-marked last resort
        """
        # Handle dict-like decisions (from serialized contexts)
        if isinstance(decision, dict):
            text = (
                decision.get("raw_text", "") or decision.get("text", "") or ""
            )
            return text, None

        # 1. Try cached DocumentExtraction first
        if not re_extract:
            extraction = getattr(decision, "text_extraction", None)
            if extraction and extraction.raw_text:
                return extraction.raw_text, extraction

        # 2. No cached text — extract on demand so we never summarize a title
        text, extraction = self._extract_on_demand(decision)
        if text:
            return text, extraction

        # 3. Last resort: subject, clearly marked so downstream steps (and
        #    readers of the summary) know this was not the full document.
        subject = getattr(decision, "subject", "") or ""
        logger.warning(
            f"ExtractStep: no extractable text for decision "
            f"{getattr(decision, 'pk', '?')} — falling back to subject"
        )
        return f"[EXTRACTION_UNAVAILABLE] {subject}", None

    def _extract_on_demand(self, decision):
        """Attempt synchronous extraction for a decision missing cached text.

        Returns ``(text, extraction_or_None)`` — the extraction row is
        resolved after the service call because ``text_extraction`` may be a
        stale cached relation."""
        try:
            from core.services.document_processor import DocumentAnalysisService

            if not getattr(decision, "document_url_or_fallback", None):
                return "", None
            result = DocumentAnalysisService().process_decision(decision)
            if not result.get("success"):
                logger.warning(
                    f"ExtractStep: on-demand extraction failed for decision "
                    f"{decision.pk}: {result.get('error')}"
                )
                return "", None
            extraction = getattr(decision, "text_extraction", None)
            # text_extraction may be a stale cached relation — refetch
            if extraction is None or not extraction.raw_text:
                from core.models.document_analysis import DocumentExtraction

                extraction = DocumentExtraction.objects.filter(
                    decision=decision
                ).first()
            if extraction and extraction.raw_text:
                return extraction.raw_text, extraction
            return "", None
        except Exception as exc:
            logger.error(
                f"ExtractStep: on-demand extraction error for decision "
                f"{getattr(decision, 'pk', '?')}: {exc}"
            )
            return "", None
