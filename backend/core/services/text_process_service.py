"""
Text Process Service.

Runs a registered text process over a ``DocumentExtraction`` and persists
the resulting ``TextProcessRun`` + ``TextSpan`` rows.  Also prepares the
span payload for the API (text + spans rendered together so offsets never
drift).

Resolution (picking a "winner" among spans) is *not* handled here — each
process that needs one (e.g. amount verification) computes and persists a
``TextProcessResolution`` itself.
"""

from typing import Any

from core.models.document_analysis import (
    DocumentExtraction,
    TextProcessRun,
    TextProcessStatus,
    TextSpan,
)
from core.services.text_processes import TEXT_PROCESSES
from core.services.text_processes.base import TextSpanData
from loguru import logger


def get_available_processes() -> list[dict[str, Any]]:
    """Return metadata for all registered processes (for the API)."""
    return [
        {
            "slug": cls.slug,
            "name": cls.name,
            "description": cls.description,
            "methods": list(cls.methods),
        }
        for cls in TEXT_PROCESSES.values()
    ]


class TextProcessService:
    """Executes text processes and persists their spans."""

    def run_process(
        self,
        extraction: DocumentExtraction,
        process_slug: str,
        method: str = "regex",
        provider: str | None = None,
        model: str | None = None,
        version: str = "1.0",
        params: dict[str, Any] | None = None,
        user=None,
        pipeline_run=None,
        force: bool = False,
    ) -> TextProcessRun:
        """
        Run *process_slug* over *extraction* and persist spans.

        Idempotent: an existing COMPLETED run for the same
        (extraction, process, method, provider, model, version) is returned
        unchanged unless ``force=True``.
        """
        process_cls = TEXT_PROCESSES.get(process_slug)
        if not process_cls:
            raise ValueError(f"Unknown text process: {process_slug!r}")

        run_provider = "REGEX" if method == "regex" else provider
        run_model = f"{process_slug}-v{version}" if method == "regex" else model

        run, created = TextProcessRun.objects.get_or_create(
            extraction=extraction,
            process=process_slug,
            method=method,
            provider=run_provider,
            model=run_model,
            version=version,
            defaults={
                "status": TextProcessStatus.PENDING,
                "triggered_by": user,
                "pipeline_run": pipeline_run,
                "meta": {"params": params or {}},
            },
        )

        if not created and run.status == TextProcessStatus.COMPLETED and not force:
            logger.debug(
                f"{process_slug} run {run.id} already completed, skipping"
            )
            return run

        text = extraction.raw_text or ""
        process = process_cls()

        run.status = TextProcessStatus.RUNNING
        run.save(update_fields=["status", "updated_at"])

        try:
            result = process.detect(text, method=method, **(params or {}))

            run.meta = {**(run.meta or {}), **result.meta}
            if result.success:
                self._save_spans(run, result.spans)
                run.status = TextProcessStatus.COMPLETED
                run.error_message = None
            else:
                run.status = TextProcessStatus.FAILED
                run.error_message = (result.error or "process failed")[:500]
        except Exception as exc:
            run.status = TextProcessStatus.FAILED
            run.error_message = str(exc)[:500]
            logger.error(
                f"{process_slug} run failed for extraction {extraction.id}: {exc}",
                exc_info=True,
            )

        run.save()
        return run

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_spans(self, run: TextProcessRun, spans: list[TextSpanData]) -> None:
        """
        Persist spans for a run, replacing any existing ones (re-runs stay
        idempotent).  Repeated identical (label, start, end) occurrences are
        collapsed with an incremented ``occurrence_count``.
        """
        run.spans.all().delete()
        if not spans:
            return

        # Collapse exact-duplicate spans (same label/start/end).  The total
        # occurrence count is the SUM of the collapsed spans' counts, since a
        # process may already have deduped by value and set its own
        # occurrence_count > 1 (e.g. the amount process dedupes by value).
        first: dict[tuple, TextSpanData] = {}
        total: dict[tuple, int] = {}
        for s in spans:
            key = (s.label, s.start, s.end)
            first.setdefault(key, s)
            total[key] = total.get(key, 0) + (s.occurrence_count or 1)

        TextSpan.objects.bulk_create(
            TextSpan(
                run=run,
                label=first[key].label,
                start=first[key].start,
                end=first[key].end,
                text_snippet=first[key].text_snippet[:500],
                value=first[key].value,
                confidence=first[key].confidence,
                occurrence_count=total[key],
            )
            for key in first
        )

    # ------------------------------------------------------------------
    # Rendering helpers (text + spans together → offsets never drift)
    # ------------------------------------------------------------------

    def serialize_run(self, run: TextProcessRun) -> dict[str, Any]:
        """Serialize a run with its spans for the API."""
        return {
            "id": run.id,
            "process": run.process,
            "method": run.method,
            "provider": run.provider,
            "model": run.model,
            "version": run.version,
            "status": run.status,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "spans": [
                {
                    "id": span.id,
                    "label": span.label,
                    "start": span.start,
                    "end": span.end,
                    "text": span.text_snippet,
                    "value": span.value,
                    "confidence": span.confidence,
                    "occurrence_count": span.occurrence_count,
                }
                for span in run.spans.all()
            ],
        }

    def get_runs_payload(
        self,
        extraction: DocumentExtraction,
        process_slugs: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return serialized runs (with spans) for an extraction."""
        qs = extraction.text_process_runs.prefetch_related("spans").order_by(
            "-created_at"
        )
        if process_slugs:
            qs = qs.filter(process__in=process_slugs)
        return [self.serialize_run(run) for run in qs]
