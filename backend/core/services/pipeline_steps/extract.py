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
        """Get the raw text for a single decision."""
        # Handle dict-like decisions (from serialized contexts)
        if isinstance(decision, dict):
            return decision.get("raw_text", "") or decision.get("text", "") or ""

        # Try cached DocumentExtraction first
        if not re_extract:
            extraction = getattr(decision, "text_extraction", None)
            if extraction and extraction.raw_text:
                return extraction.raw_text

        # Fallback: use subject + extra_data if no extraction
        subject = getattr(decision, "subject", "") or ""
        return subject
