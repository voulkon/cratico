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
        for decision in context.decisions:
            text = self._get_decision_text(decision, re_extract=re_extract)
            if max_chars and len(text) > max_chars:
                text = text[:max_chars]
            # Dict vs model-safe ID extraction:
            # Using ``getattr`` with an eagerly-evaluated default like
            # ``decision.get("id", "")`` would crash on model instances
            # because Python evaluates the default *before* getattr runs.
            if isinstance(decision, dict):
                item_id = str(decision.get("id", ""))
            else:
                item_id = str(decision.pk)
            texts[item_id] = text

        # Store in context for downstream steps
        context.per_item_outputs = texts
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
        """Get the raw text for a single decision.

        Resolution order:
        1. Cached ``DocumentExtraction.raw_text`` (unless ``re_extract``)
        2. On-demand extraction via ``DocumentAnalysisService``
        3. Decision subject as a clearly-marked last resort
        """
        # Handle dict-like decisions (from serialized contexts)
        if isinstance(decision, dict):
            return decision.get("raw_text", "") or decision.get("text", "") or ""

        # 1. Try cached DocumentExtraction first
        if not re_extract:
            extraction = getattr(decision, "text_extraction", None)
            if extraction and extraction.raw_text:
                return extraction.raw_text

        # 2. No cached text — extract on demand so we never summarize a title
        text = self._extract_on_demand(decision)
        if text:
            return text

        # 3. Last resort: subject, clearly marked so downstream steps (and
        #    readers of the summary) know this was not the full document.
        subject = getattr(decision, "subject", "") or ""
        logger.warning(
            f"ExtractStep: no extractable text for decision "
            f"{getattr(decision, 'pk', '?')} — falling back to subject"
        )
        return f"[EXTRACTION_UNAVAILABLE] {subject}"

    def _extract_on_demand(self, decision) -> str:
        """Attempt synchronous extraction for a decision missing cached text."""
        try:
            from core.services.document_processor import DocumentAnalysisService

            if not getattr(decision, "document_url_or_fallback", None):
                return ""
            result = DocumentAnalysisService().process_decision(decision)
            if not result.get("success"):
                logger.warning(
                    f"ExtractStep: on-demand extraction failed for decision "
                    f"{decision.pk}: {result.get('error')}"
                )
                return ""
            extraction = getattr(decision, "text_extraction", None)
            # text_extraction may be a stale cached relation — refetch
            if extraction is None or not extraction.raw_text:
                from core.models.document_analysis import DocumentExtraction

                extraction = DocumentExtraction.objects.filter(
                    decision=decision
                ).first()
            return extraction.raw_text if extraction and extraction.raw_text else ""
        except Exception as exc:
            logger.error(
                f"ExtractStep: on-demand extraction error for decision "
                f"{getattr(decision, 'pk', '?')}: {exc}"
            )
            return ""
