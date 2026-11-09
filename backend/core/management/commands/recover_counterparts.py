"""
Recover the real counterpart of self-as-counterpart decisions.

Diavgeia sometimes records the issuing organization's own VAT number (ΑΦΜ) as
the counterpart.  This command reads the document text (OCR if needed), scores
the AFMs found there, and — with ``--apply`` — repoints the live relationship
row, preserving the replaced state in ``CounterpartRecoveryAttempt``.

Examples
--------
    # Inspect one decision (no writes)
    python manage.py recover_counterparts --ada 6ΧΩΜ469ΗΣΥ-ΒΗ4 --dry-run

    # Recover and apply for one decision
    python manage.py recover_counterparts --ada 6ΧΩΜ469ΗΣΥ-ΒΗ4 --apply

    # Bounded backfill for an import window
    python manage.py recover_counterparts \
        --imported-since 2026-11-01 --imported-until 2026-11-02 --limit 50 --apply
"""

from __future__ import annotations

from datetime import datetime

from core.models.decisions import Decision
from core.services.counterpart_recovery_service import (
    DEFAULT_CANDIDATE_LIMIT,
    CounterpartRecoveryService,
)
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


def _aware(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


class Command(BaseCommand):
    help = "Recover self-as-counterpart decisions from document text."

    def add_arguments(self, parser):
        parser.add_argument("--ada", default=None, help="Single decision ADA.")
        parser.add_argument(
            "--imported-since",
            default=None,
            help="Only decisions imported on/after this ISO date/datetime.",
        )
        parser.add_argument(
            "--imported-until",
            default=None,
            help="Only decisions imported before this ISO date/datetime.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=DEFAULT_CANDIDATE_LIMIT,
            help=f"Max decisions to process (default {DEFAULT_CANDIDATE_LIMIT}).",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply high-confidence matches (requires the apply flag unless --force).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Score and report without writing anything.",
        )
        parser.add_argument(
            "--ocr",
            action="store_true",
            dest="ocr",
            default=True,
            help="Allow OCR (default).",
        )
        parser.add_argument(
            "--no-ocr",
            action="store_false",
            dest="ocr",
            help="Never run OCR.",
        )
        parser.add_argument(
            "--ai",
            action="store_true",
            dest="ai",
            default=None,
            help="Allow the AI resolver.",
        )
        parser.add_argument(
            "--no-ai",
            action="store_false",
            dest="ai",
            help="Disable the AI resolver.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Bypass the COUNTERPART_RECOVERY_ENABLED master flag.",
        )

    def handle(self, *args, **options):
        imported_since = _aware(options["imported_since"])
        imported_until = _aware(options["imported_until"])
        service = CounterpartRecoveryService()

        if options["ada"]:
            try:
                decision = Decision.objects.select_related("organization").get(
                    ada__iexact=options["ada"]
                )
            except Decision.DoesNotExist:
                raise CommandError(f"Decision {options['ada']} not found")
            decisions = [decision]
        else:
            decisions = service.get_candidates(
                imported_since=imported_since,
                imported_until=imported_until,
                limit=options["limit"],
            )

        if not decisions:
            self.stdout.write(self.style.WARNING("No self-counterpart candidates."))
            return

        self.stdout.write(f"Processing {len(decisions)} decision(s)...")

        totals = {
            "recovered": 0,
            "needs_review": 0,
            "no_candidate": 0,
            "already_recovered": 0,
            "would_apply": 0,
            "skipped": 0,
            "errors": 0,
        }

        for decision in decisions:
            try:
                result = service.recover_decision(
                    decision,
                    apply=True if options["apply"] else None,
                    allow_ocr=options["ocr"],
                    allow_ai=options["ai"],
                    dry_run=options["dry_run"],
                    force=options["force"],
                )
            except Exception as exc:  # keep going; report at the end
                totals["errors"] += 1
                self.stderr.write(f"{decision.ada}: ERROR {exc}")
                continue

            status = result.get("status", "unknown")
            totals[status] = totals.get(status, 0) + 1
            self.stdout.write(
                f"{decision.ada}: {status}"
                + (
                    f" → {result.get('chosen_afm')} "
                    f"({result.get('confidence')})"
                    if result.get("chosen_afm")
                    else ""
                )
                + (
                    f" [{result.get('reason')}]"
                    if result.get("reason")
                    else ""
                )
            )

        self.stdout.write(self.style.SUCCESS(f"Done: {totals}"))
