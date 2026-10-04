"""
Detector: decimal-separator shift (the classic ×100 / ÷100 Diavgeia typo).

Dropping the decimal comma when typing ``30.000,00`` produces ``3.000.000`` —
the recorded amount is 100× the amount actually written in the document.
The reverse (a ÷100 shift) also occurs.

Detection is cents-based (``grouped_amount_detection``): only amounts carrying
two decimals are compared, because a Greek official document writes money as
``1.234.567,89`` and a 2-decimal match is a very strong signal — a round
number *could* appear in the text by coincidence, one with cents cannot.

Treatment: ``DecisionAmountField.verified_amount`` (never the raw ``amount``,
so the import payload stays auditable) — see ``AmountCorrectionService``.

There is also a *group* variant: when no individual field matches but the SUM
has a ×100 / ÷100 clone, every field was uniformly mistyped, so each is
re-scaled proportionally and the last field absorbs the rounding remainder.
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Exists, OuterRef

from core.services.data_quality.base import (
    STATUS_CONSISTENT,
    STATUS_DETECTED,
    BaseDetector,
    Outcome,
)

#: ``correct_decision`` statuses this detector owns.
_REPAIR_STATUSES = ("corrected", "would_correct")

#: Statuses owned by the non-monetary detector — do not double-report them.
_FOREIGN_STATUSES = ("afm_as_amount", "kae_as_amount", "non_monetary_value_as_amount")


class DecimalShiftDetector(BaseDetector):
    """Find amounts whose text copy is exactly ×100 / ÷100 of the recorded one."""

    slug = "decimal-shift"
    mode_key = "decimal_shift"
    name = "Decimal separator shift"
    description = (
        "A recorded amount is ×100 or ÷100 of the amount written in the "
        "document — a dropped/added decimal separator (30.000,00 → 3.000.000)."
    )
    note_marker = "[DECIMAL-SHIFT]"

    needs_text = True
    can_repair = True
    uses_total_amount = True
    default_min_amount = Decimal("100000")  # matches DEFAULT_CORRECTION_THRESHOLD

    # ------------------------------------------------------------------
    # Candidates
    # ------------------------------------------------------------------

    def candidate_ids(
        self,
        *,
        min_amount: Decimal | None = None,
        max_amount: Decimal | None = None,
        imported_since=None,
        imported_until=None,
        issue_start=None,
        issue_end=None,
        limit: int | None = None,
    ) -> list[int]:
        """
        Decisions whose *aggregate* total crosses the threshold and that still
        have at least one correction-eligible amount field.

        Rows already flagged as non-monetary values are excluded from
        ``has_uncorrected`` so an un-recoverable amount is never re-selected on
        every run.

        NOTE: the aggregate is never ``.count()``-ed — counting the un-sliced
        annotate+GROUP BY query is what produced the 16h runaway query and its
        cluster-wide lock pileup (see
        ``docs/lessons_learnt/runaway_query_lock_pileup.md``).  The count is
        always derived from the already-limited list.
        """
        from core.models.decisions import Decision
        from core.models.entities import DecisionAmountField
        from core.services.decision_facets import amount_sum_excluding_kae

        min_amount, max_amount = self.bounds(min_amount, max_amount)

        has_uncorrected = Exists(
            DecisionAmountField.objects.filter(
                decision=OuterRef("pk"),
                amount__gt=0,
                verified_amount__isnull=True,
                invalid_amount_reason__isnull=True,
            )
        )

        qs = (
            Decision.objects
            .annotate(calc_total=amount_sum_excluding_kae())
            .filter(has_uncorrected)
        )
        if min_amount is not None:
            qs = qs.filter(calc_total__gte=min_amount)
        if max_amount is not None:
            qs = qs.filter(calc_total__lte=max_amount)
        if imported_since is not None:
            qs = qs.filter(created_at__gte=imported_since)
        if imported_until is not None:
            qs = qs.filter(created_at__lt=imported_until)
        if issue_start is not None:
            qs = qs.filter(issue_date_day__gte=issue_start)
        if issue_end is not None:
            qs = qs.filter(issue_date_day__lte=issue_end)

        qs = qs.order_by("-calc_total")
        if limit:
            qs = qs[:limit]
        return list(qs.values_list("id", flat=True))

    # ------------------------------------------------------------------
    # Contract
    # ------------------------------------------------------------------

    def scan(self, decision, *, read_if_missing: bool = True, **kwargs) -> Outcome:
        """
        Dry-run the correction service and translate its result into findings.

        Read-only w.r.t. the *verdict*: it never writes ``verified_amount`` or
        the invalid-amount marker.  It may persist the extracted document text
        (``read_if_missing``), which is a cache, not a decision.
        """
        result = self._service().correct_decision(
            decision, dry_run=True, read_if_missing=read_if_missing
        )
        return self._to_outcome(result)

    def apply(self, decision, outcome: Outcome, *, dry_run: bool = False, **kwargs) -> int:
        """
        Write ``verified_amount`` for every planned correction.

        Delegated to ``AmountCorrectionService.correct_decision`` so there is
        exactly one write path (the service re-derives the same corrections;
        the second pass is cheap because ``scan`` already persisted the text
        extraction, so no document is downloaded twice).
        """
        result = self._service().correct_decision(
            decision,
            dry_run=dry_run,
            read_if_missing=kwargs.get("read_if_missing", True),
        )
        if result.get("status") in _REPAIR_STATUSES:
            return len(result.get("corrections", []))
        return 0

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _service():
        from core.services.amount_correction_service import AmountCorrectionService

        return AmountCorrectionService()

    def _to_outcome(self, result: dict) -> Outcome:
        status = result.get("status", "")

        if status in _REPAIR_STATUSES:
            findings = [
                self.finding(
                    kind="decimal_shift",
                    reason="decimal_shift",
                    field_id=c["field_id"],
                    source_field=c.get("source_field", ""),
                    recorded=str(c.get("db_amount", "")),
                    suggested=str(c.get("corrected_to", "")),
                    note=(
                        f"text amount is ×{c['clone_factor']} the recorded value"
                        if c.get("clone_factor")
                        else "group re-scale"
                    ),
                    payload={
                        "clone_factor": str(c.get("clone_factor", "")),
                        "group_correction": bool(c.get("group_correction")),
                    },
                )
                for c in result.get("corrections", [])
            ]
            return Outcome(slug=self.slug, status=STATUS_DETECTED, findings=findings)

        if status in _FOREIGN_STATUSES:
            # The non-monetary detector owns this verdict.
            return self.skip("non_monetary")

        if status == "consistent":
            return Outcome(slug=self.slug, status=STATUS_CONSISTENT)

        if status == "no_text_amounts_found":
            return self.skip("no_text_amounts_found")

        if status == "no_correctable_fields":
            return self.skip("no_correctable_fields")

        return self.skip(result.get("reason") or status or "unknown")
