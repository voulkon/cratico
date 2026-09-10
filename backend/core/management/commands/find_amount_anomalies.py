"""
Find decisions whose recorded amount is actually a **non-monetary value** —
an AFM (counterpart VAT number / ΑΦΜ) or a KAE (budget classification code /
ΚΑΕ) sitting in the amount field instead of a monetary amount.

This is the *discovery* half of the non-monetary-value guard (the guard itself
lives in ``core.services.non_monetary_value_guard`` and is applied during amount
verification/correction).  Unlike the guard, this command needs **no document
text** — it compares the recorded ``DecisionAmountField.amount`` values against
the decision's AFMs and KAEs — so it also finds historical rows that were never
run through the verification pipeline.

Canonical cases
---------------
- AFM: decision ``Ψ0Α74690Β9-52Ρ`` — sponsor AFM ``099370337`` (VIOLAK
  INTERNATIONAL) recorded as ``expenseAmount`` = ``99370337`` (€99,370,337).
- KAE: decision ``ΨΡΙ0Ω12-0ΙΘ`` — sponsor ``expenseAmount`` =
  ``7.06273001E8`` (€706,273,001) where the sibling ``kae`` is ``70.6273.001``.

Usage
-----
    # Whole database, human report + JSON artefact
    python manage.py find_amount_anomalies --output anomalies.json

    # Only AFM cases, written as CSV for a spreadsheet
    python manage.py find_amount_anomalies --kind afm --csv anomalies.csv

    # Inspect one decision directly (ignores amount bounds)
    python manage.py find_amount_anomalies --ada Ψ0Α74690Β9-52Ρ

    # Scope to decisions imported on a given day
    python manage.py find_amount_anomalies --imported-since 2026-01-01 --imported-until 2026-01-02
"""

import csv
import json
from datetime import datetime, time
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Prefetch
from django.utils import timezone

from core.models.decisions import Decision
from core.models.document_analysis import TextProcessResolution
from core.models.entities import DecisionAmountField
from core.services.non_monetary_value_guard import (
    DISCREPANCY_REASON_AFM,
    DISCREPANCY_REASON_KAE,
    KIND_AFM,
    KIND_KAE,
    collect_non_monetary_values,
)

# Markers that identify an already-flagged resolution / note.
_NOTE_MARKERS = {
    KIND_AFM: "[AFM-AS-AMOUNT]",
    KIND_KAE: "[KAE-AS-AMOUNT]",
}


class Command(BaseCommand):
    help = (
        "Find decisions whose recorded amount is a non-monetary value — an "
        "AFM (VAT number) or a budget KAE code."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--min-amount",
            type=float,
            default=100_000,
            help=(
                "Lower bound (EUR) for candidate amounts. An AFM/KAE rendered "
                "as a number has 8-9 digits, so very small amounts are skipped. "
                "Ignored when --ada is given. Default: 100000"
            ),
        )
        parser.add_argument(
            "--max-amount",
            type=float,
            default=100_000_000_000,
            help="Upper bound (EUR) for candidate amounts. Default: 100000000000",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Stop after scanning this many candidate decisions.",
        )
        parser.add_argument(
            "--ada",
            type=str,
            default=None,
            help=(
                "Inspect a single decision by ADA (bypasses amount bounds and "
                "uses the KAE stored next to each amount for higher precision)."
            ),
        )
        parser.add_argument(
            "--kind",
            choices=[KIND_AFM, KIND_KAE, "all"],
            default="all",
            help="Restrict the report to one anomaly kind. Default: all",
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
            "--max-candidates",
            type=int,
            default=5,
            help=(
                "How many sibling amount values to show per hit as hints for "
                "the real amount. Default: 5"
            ),
        )
        parser.add_argument(
            "--output",
            type=str,
            default=None,
            help="Write the full report to this JSON file.",
        )
        parser.add_argument(
            "--csv",
            type=str,
            default=None,
            help="Write a one-row-per-anomaly CSV to this file.",
        )

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        max_candidates = options["max_candidates"]
        kind_filter = options["kind"]

        decisions, scanned = self._candidate_decisions(options)

        report = []
        for decision in decisions:
            anomalies = collect_non_monetary_values(
                decision,
                use_raw_context=options["ada"] is not None,
            )
            if kind_filter != "all":
                anomalies = [a for a in anomalies if a.kind == kind_filter]
            if not anomalies:
                continue
            report.append(
                self._build_row(decision, anomalies, max_candidates=max_candidates)
            )

        self._print_report(report, scanned)

        if options["output"]:
            payload = {
                "generated_at": timezone.now().isoformat(),
                "kind": kind_filter,
                "scanned_decisions": scanned,
                "hit_count": len(report),
                "anomaly_count": sum(len(r["anomalies"]) for r in report),
                "hits": report,
            }
            with open(options["output"], "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            self.stdout.write(
                self.style.SUCCESS(f"Report written to {options['output']}")
            )

        if options["csv"]:
            self._write_csv(options["csv"], report)

    # ------------------------------------------------------------------
    def _candidate_decisions(self, options):
        """Return (queryset, number_of_candidate_decisions)."""
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
        # materialising every candidate id) so a bounded run never pulls the
        # whole high-value set into memory.  Mirrors fix_amount_anomalies —
        # keep the two in sync.
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
                decision__created_at__gte=self._parse_date(
                    options["imported_since"]
                )
            )
        if options["imported_until"]:
            candidate_qs = candidate_qs.filter(
                decision__created_at__lt=self._parse_date(
                    options["imported_until"]
                )
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
    def _build_row(self, decision, anomalies, max_candidates: int) -> dict:
        anomaly_field_ids = {a.field_id for a in anomalies}

        # Sibling amounts that are NOT anomalies — hints for the real value.
        candidates = []
        for field in sorted(
            decision.amount_fields.all(),
            key=lambda f: f.amount or Decimal("0"),
            reverse=True,
        ):
            if field.id in anomaly_field_ids or field.amount is None:
                continue
            candidates.append(str(field.amount))
            if len(candidates) >= max_candidates:
                break

        return {
            "ada": decision.ada,
            "decision_id": decision.id,
            "created_at": decision.created_at.isoformat()
            if decision.created_at
            else None,
            "anomalies": [
                {
                    "field_id": a.field_id,
                    "kind": a.kind,
                    "parent_key_path": a.parent_key_path,
                    "source_field_name": a.source_field,
                    "amount": str(a.amount),
                    "matched_value": a.matched_value,
                    "discrepancy_reason": a.reason,
                    "already_flagged": self._is_already_flagged(decision, a.kind),
                    "note": a.note,
                }
                for a in anomalies
            ],
            "candidate_real_amounts": candidates,
        }

    def _is_already_flagged(self, decision, kind: str) -> bool:
        marker = _NOTE_MARKERS.get(kind)
        reason = (
            DISCREPANCY_REASON_AFM if kind == KIND_AFM else DISCREPANCY_REASON_KAE
        )
        for resolution in decision.text_process_resolutions.all():
            winning = resolution.winning_run
            if winning and (winning.meta or {}).get(
                "discrepancy_reason"
            ) == reason:
                return True
            if marker and resolution.note and marker in resolution.note:
                return True
        return False

    def _print_report(self, report: list[dict], scanned: int):
        if not report:
            self.stdout.write(
                self.style.SUCCESS("No non-monetary-value-as-amount cases found. 🎉")
            )
            return

        total = sum(len(r["anomalies"]) for r in report)
        afm = sum(
            1 for r in report for a in r["anomalies"] if a["kind"] == KIND_AFM
        )
        kae = total - afm
        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(
                f"Found {total} anomaly(ies) across {len(report)} decision(s) "
                f"[{afm} AFM, {kae} KAE]; scanned {scanned}."
            )
        )
        self.stdout.write("")
        for row in report:
            self.stdout.write(f"{row['ada']} (id={row['decision_id']})")
            for a in row["anomalies"]:
                mark = "✓ flagged" if a["already_flagged"] else "· new"
                self.stdout.write(
                    f"    [{mark}] {a['kind'].upper()} "
                    f"{a['source_field_name']} @ {a['parent_key_path']}: "
                    f"{a['amount']} == {a['matched_value']}"
                )
            if row["candidate_real_amounts"]:
                self.stdout.write(
                    "    candidate real amounts (siblings, not the matched value): "
                    + ", ".join(row["candidate_real_amounts"])
                )
            self.stdout.write("")

    def _write_csv(self, path: str, report: list[dict]):
        fields = [
            "ada",
            "decision_id",
            "created_at",
            "kind",
            "field_id",
            "parent_key_path",
            "source_field_name",
            "amount",
            "matched_value",
            "discrepancy_reason",
            "already_flagged",
            "candidate_real_amounts",
        ]
        count = 0
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for row in report:
                for a in row["anomalies"]:
                    writer.writerow(
                        {
                            "ada": row["ada"],
                            "decision_id": row["decision_id"],
                            "created_at": row["created_at"],
                            "kind": a["kind"],
                            "field_id": a["field_id"],
                            "parent_key_path": a["parent_key_path"],
                            "source_field_name": a["source_field_name"],
                            "amount": a["amount"],
                            "matched_value": a["matched_value"],
                            "discrepancy_reason": a["discrepancy_reason"],
                            "already_flagged": a["already_flagged"],
                            "candidate_real_amounts": "|".join(
                                row["candidate_real_amounts"]
                            ),
                        }
                    )
                    count += 1
        self.stdout.write(
            self.style.SUCCESS(f"CSV written to {path} ({count} row(s))")
        )

    @staticmethod
    def _parse_date(value: str) -> datetime:
        return timezone.make_aware(
            datetime.combine(datetime.fromisoformat(value).date(), time.min)
        )
