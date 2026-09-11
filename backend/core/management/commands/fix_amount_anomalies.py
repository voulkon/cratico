"""
Treat decisions whose recorded amount is actually a **non-monetary value** —
an AFM (counterpart VAT number / ΑΦΜ) or a KAE (budget classification code /
ΚΑΕ) sitting in the amount field instead of a monetary amount.

This is the *treatment* half of the non-monetary-value guard.  Its read-only
twin, ``find_amount_anomalies``, only reports; this command writes the
**invalid-amount marker** on the affected ``DecisionAmountField`` rows:

    invalid_amount_reason      = "afm_as_amount" | "kae_as_amount"
    invalid_amount_value       = the matched AFM / KAE digits
    invalid_amount_flagged_at  = when it was flagged

It **never** writes a monetary value.  The real amount is unknown, and
``verified_amount`` means "we found the real value in the document" — storing a
guess there would be a lie.  The marker is what excludes the bogus figure from
every monetary aggregation (facet layer) and surfaces the decision in the
Diavgeia feedback pool.

Safety
------
* **Dry-run by default** — nothing is written unless ``--apply`` is given.
* No document is downloaded or read; the guard is DB-only, so this is cheap
  and safe to run on a production database.
* Idempotent — re-running rewrites the same reason/value.  ``--only-new`` skips
  decisions whose detected fields are already flagged.
* Reversible — ``--clear --apply`` removes the marker (it never touches
  ``verified_amount``, so nothing else is affected).

Usage
-----
    # Preview what would be flagged (whole database, no writes)
    python manage.py fix_amount_anomalies

    # Apply the marker
    python manage.py fix_amount_anomalies --apply

    # One decision, regardless of the amount bounds
    python manage.py fix_amount_anomalies --ada Ψ0Α74690Β9-52Ρ --apply

    # Only AFM cases imported in a window, with an audit trail
    python manage.py fix_amount_anomalies --kind afm \\
        --imported-since 2026-01-01 --imported-until 2026-02-01 \\
        --apply --output flagged.json

    # Roll back
    python manage.py fix_amount_anomalies --clear --apply

NOTE: candidate selection mirrors ``find_amount_anomalies`` so that what the
scanner reports is exactly what this command treats.  Keep the two in sync.
"""

import json
from datetime import datetime, time
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Prefetch
from django.utils import timezone

from core.models.decisions import Decision
from core.models.document_analysis import TextProcessResolution
from core.models.entities import DecisionAmountField
from core.services.amount_correction_service import AmountCorrectionService
from core.services.non_monetary_value_guard import (
    KIND_AFM,
    KIND_KAE,
    collect_non_monetary_values,
)


class Command(BaseCommand):
    help = (
        "Flag (or clear the flag on) decisions whose recorded amount is a "
        "non-monetary value — an AFM (VAT number) or a budget KAE code. "
        "Dry-run by default; pass --apply to write."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually write the marker. Without this the command only reports.",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help=(
                "Remove the invalid-amount marker instead of setting it "
                "(rollback). Honours --apply."
            ),
        )
        parser.add_argument(
            "--ada",
            type=str,
            default=None,
            help=(
                "Treat a single decision by ADA (bypasses the amount bounds and "
                "uses the KAE stored next to each amount for higher precision)."
            ),
        )
        parser.add_argument(
            "--kind",
            choices=[KIND_AFM, KIND_KAE, "all"],
            default="all",
            help="Restrict treatment to one anomaly kind. Default: all",
        )
        parser.add_argument(
            "--min-amount",
            type=float,
            default=100_000,
            help=(
                "Lower bound (EUR) for candidate amounts. Ignored with --ada. "
                "Default: 100000"
            ),
        )
        parser.add_argument(
            "--max-amount",
            type=float,
            default=100_000_000_000,
            help="Upper bound (EUR) for candidate amounts. Default: 100000000000",
        )
        parser.add_argument(
            "--imported-since",
            type=str,
            default=None,
            help="Only decisions imported on/after this date (YYYY-MM-DD).",
        )
        parser.add_argument(
            "--imported-until",
            type=str,
            default=None,
            help="Only decisions imported before this date (YYYY-MM-DD).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Stop after scanning this many candidate decisions.",
        )
        parser.add_argument(
            "--only-new",
            action="store_true",
            help=(
                "Skip decisions whose detected fields are ALL already flagged. "
                "Useful for a fast re-run; the write itself is idempotent."
            ),
        )
        parser.add_argument(
            "--output",
            type=str,
            default=None,
            help="Write a JSON record of what was (or would be) changed here.",
        )

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        apply_changes = options["apply"]
        clear = options["clear"]
        kind_filter = options["kind"]
        svc = AmountCorrectionService()

        decisions, scanned = self._candidate_decisions(options)

        if clear:
            self._banner(
                "CLEARING invalid-amount markers" if apply_changes
                else "PREVIEW — would clear invalid-amount markers"
            )
        else:
            self._banner(
                "FLAGGING non-monetary values (AFM/KAE)" if apply_changes
                else "DRY RUN — nothing will be written (pass --apply to write)"
            )

        report: list[dict] = []
        decisions_changed = 0
        fields_written = 0
        fields_already = 0
        fields_cleared = 0

        for decision in decisions:
            if clear:
                cleared = svc.clear_non_monetary_markers(
                    decision,
                    kind=None if kind_filter == "all" else kind_filter,
                    dry_run=not apply_changes,
                )
                if cleared:
                    decisions_changed += 1
                    fields_cleared += cleared
                    report.append(
                        {
                            "ada": decision.ada,
                            "decision_id": decision.id,
                            "action": "cleared" if apply_changes else "would_clear",
                            "fields_cleared": cleared,
                        }
                    )
                    self.stdout.write(
                        f"  {'✓' if apply_changes else '·'} {decision.ada}: "
                        f"{cleared} marker(s) removed"
                    )
                continue

            # Detect first so we can report new vs already-flagged.
            anomalies = collect_non_monetary_values(
                decision,
                use_raw_context=options["ada"] is not None,
            )
            if kind_filter != "all":
                anomalies = [a for a in anomalies if a.kind == kind_filter]
            if not anomalies:
                continue

            existing = set(
                decision.amount_fields
                .filter(invalid_amount_reason__isnull=False)
                .values_list("id", flat=True)
            )
            already = [a for a in anomalies if a.field_id in existing]
            new = [a for a in anomalies if a.field_id not in existing]

            if options["only_new"] and not new:
                continue

            if apply_changes:
                svc.flag_non_monetary_values(decision, dry_run=False)

            decisions_changed += 1
            fields_written += len(new)
            fields_already += len(already)

            report.append(
                {
                    "ada": decision.ada,
                    "decision_id": decision.id,
                    "action": "flagged" if apply_changes else "would_flag",
                    "anomalies": [
                        {
                            "field_id": a.field_id,
                            "kind": a.kind,
                            "source_field_name": a.source_field,
                            "parent_key_path": a.parent_key_path,
                            "amount": str(a.amount),
                            "matched_value": a.matched_value,
                            "discrepancy_reason": a.reason,
                            "already_flagged": a.field_id in existing,
                        }
                        for a in anomalies
                    ],
                }
            )

            for a in anomalies:
                mark = "✓ flagged" if a.field_id in existing else "· new"
                self.stdout.write(
                    f"  [{mark}] {decision.ada} ({decision.id}) "
                    f"{a.kind.upper()} {a.source_field} @ {a.parent_key_path}: "
                    f"{a.amount} == {a.matched_value}"
                )

        self._summary(
            report=report,
            scanned=scanned,
            decisions_changed=decisions_changed,
            fields_written=fields_written,
            fields_already=fields_already,
            fields_cleared=fields_cleared,
            apply_changes=apply_changes,
            clear=clear,
        )

        if options["output"]:
            payload = {
                "generated_at": timezone.now().isoformat(),
                "mode": "clear" if clear else "flag",
                "applied": apply_changes,
                "kind": kind_filter,
                "scanned_decisions": scanned,
                "decisions_changed": decisions_changed,
                "fields_written": fields_written,
                "fields_already_flagged": fields_already,
                "fields_cleared": fields_cleared,
                "results": report,
            }
            with open(options["output"], "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            self.stdout.write(
                self.style.SUCCESS(f"Record written to {options['output']}")
            )

        if not apply_changes:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING("DRY RUN — nothing was written. Re-run with --apply.")
            )

    # ------------------------------------------------------------------
    def _candidate_decisions(self, options):
        """
        Return (queryset, candidate_count).

        Mirrors ``find_amount_anomalies._candidate_decisions`` so the scanner
        and the fixer always agree on scope.
        """
        prefetch = [
            "entity_relationships__entity",
            "amount_fields",
            Prefetch(
                "text_process_resolutions",
                queryset=TextProcessResolution.objects.filter(
                    process="amount"
                ).select_related("winning_run"),
            ),
        ]

        if options["ada"]:
            qs = Decision.objects.filter(ada=options["ada"]).prefetch_related(
                *prefetch
            )
            return qs, qs.count()

        min_amount = Decimal(str(options["min_amount"]))
        max_amount = Decimal(str(options["max_amount"]))

        # NOTE: ``--limit`` is applied to the SQL query (not after
        # materialising every candidate id) so a bounded admin/manual run
        # never pulls the whole high-value set into memory.
        candidate_qs = (
            DecisionAmountField.objects.filter(
                amount__gte=min_amount,
                amount__lt=max_amount,
            )
            .order_by("decision_id")
            .values_list("decision_id", flat=True)
            .distinct()
        )

        if options["imported_since"]:
            candidate_qs = candidate_qs.filter(
                decision__created_at__gte=self._parse_date(options["imported_since"])
            )
        if options["imported_until"]:
            candidate_qs = candidate_qs.filter(
                decision__created_at__lt=self._parse_date(options["imported_until"])
            )

        if options["limit"]:
            candidate_qs = candidate_qs[: options["limit"]]

        decision_ids = list(candidate_qs)
        if not decision_ids:
            return Decision.objects.none(), 0

        self.stdout.write(
            f"Scanning {len(decision_ids)} candidate decision(s) with amount "
            f"in [{min_amount:,}, {max_amount:,}) EUR ..."
        )

        qs = (
            Decision.objects.filter(id__in=decision_ids)
            .prefetch_related(*prefetch)
            .order_by("id")
        )
        return qs, len(decision_ids)

    # ------------------------------------------------------------------
    def _banner(self, text: str):
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(text))
        self.stdout.write(self.style.MIGRATE_HEADING("=" * len(text)))

    def _summary(
        self,
        *,
        report: list[dict],
        scanned: int,
        decisions_changed: int,
        fields_written: int,
        fields_already: int,
        fields_cleared: int,
        apply_changes: bool,
        clear: bool,
    ):
        verb = (
            "cleared" if clear and apply_changes
            else "would clear" if clear
            else "flagged" if apply_changes
            else "would flag"
        )
        self.stdout.write("")
        if not report:
            self.stdout.write(
                self.style.SUCCESS(f"No decisions to treat; scanned {scanned}. 🎉")
            )
            return
        self.stdout.write(
            self.style.WARNING(
                f"{decisions_changed} decision(s) {verb}; "
                f"{fields_written} field(s) flagged, "
                f"{fields_already} already flagged, "
                f"{fields_cleared} marker(s) cleared (scanned {scanned})."
            )
        )

    @staticmethod
    def _parse_date(value: str) -> datetime:
        return timezone.make_aware(
            datetime.combine(datetime.fromisoformat(value).date(), time.min)
        )
