"""
Detector: a **non-monetary value recorded as the amount**.

The amount field holds a value that belongs to a *different* numeric field of
the same decision — typically the counterpart's AFM (VAT number / ΑΦΜ) or a
budget KAE code (ΚΑΕ).  The value is **misplaced**, not duplicated, and the
real amount is **unknown**.

Canonical cases
---------------
- AFM: decision ``Ψ0Α74690Β9-52Ρ`` — sponsor AFM ``099370337`` recorded as
  ``expenseAmount`` = ``99370337`` (€99,370,337).
- KAE: decision ``ΨΡΙ0Ω12-0ΙΘ`` — ``expenseAmount`` = ``7.06273001E8``
  (€706,273,001) where the sibling ``kae`` is ``70.6273.001``.

This detector is **DB-only** (``needs_text = False``): it compares the recorded
amount against the decision's own AFMs/KAEs, so it also finds historical rows
that never went through the verification pipeline — and it costs no document
read.

Treatment is the **invalid-amount marker**, never ``verified_amount``: storing
any monetary figure here would be a lie, and ``verified_amount = 0`` would
falsely assert €0.  The marker makes every facet aggregation exclude the row
(``COALESCE(verified_amount, amount)`` alone cannot) and puts the decision in
the feedback pool for manual follow-up.

See ``docs/lessons_learnt/non_monetary_value_as_amount.md``.
"""

from __future__ import annotations

from decimal import Decimal

from core.services.data_quality.base import (
    TARGET_UNUSABLE,
    STATUS_CONSISTENT,
    STATUS_DETECTED,
    BaseDetector,
    Outcome,
)


class NonMonetaryValueDetector(BaseDetector):
    """Find amount fields whose value is really an AFM (VAT no.) or a KAE code."""

    slug = "non-monetary-value"
    mode_key = "non_monetary"
    name = "Non-monetary value recorded as amount"
    description = (
        "A recorded amount is actually a different numeric field of the same "
        "decision — the counterpart's AFM (VAT number) or a budget KAE code. "
        "The real amount is unknown, so the row is flagged, never guessed."
    )
    note_marker = "[NON-MONETARY]"

    needs_text = False
    can_repair = False
    uses_total_amount = False
    # An AFM/KAE rendered as a number has 8-9 digits, so tiny amounts are noise.
    # Mirrors the defaults of ``manage.py find_amount_anomalies``.
    default_min_amount = Decimal("100000")
    default_max_amount = Decimal("100000000000")

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
        Decisions with at least one amount field inside the value bounds and
        not already carrying the invalid-amount marker.

        The bound is on the **individual** ``DecisionAmountField.amount`` (that
        is the value being mistaken for money), not on the decision total —
        which is why this detector declares ``uses_total_amount = False``.

        ``--limit`` is pushed into the SQL (``.distinct()[:limit]``) so a
        bounded run never materialises the whole candidate set; this mirrors
        the ``find_*`` / ``fix_*`` management commands.
        """
        from core.models.entities import DecisionAmountField

        min_amount, max_amount = self.bounds(min_amount, max_amount)

        qs = DecisionAmountField.objects.filter(
            verified_amount__isnull=True,
            invalid_amount_reason__isnull=True,
        )
        if min_amount is not None:
            qs = qs.filter(amount__gte=min_amount)
        if max_amount is not None:
            qs = qs.filter(amount__lt=max_amount)
        if imported_since is not None:
            qs = qs.filter(decision__created_at__gte=imported_since)
        if imported_until is not None:
            qs = qs.filter(decision__created_at__lt=imported_until)
        if issue_start is not None:
            qs = qs.filter(decision__issue_date_day__gte=issue_start)
        if issue_end is not None:
            qs = qs.filter(decision__issue_date_day__lte=issue_end)

        qs = qs.order_by("decision_id").values_list("decision_id", flat=True).distinct()
        if limit:
            qs = qs[:limit]
        return list(qs)

    # ------------------------------------------------------------------
    # Contract
    # ------------------------------------------------------------------

    def scan(self, decision, *, use_raw_context: bool = False, **kwargs) -> Outcome:
        """
        Compare every recorded amount against the decision's own AFMs / KAEs.

        ``use_raw_context`` additionally tests the KAE stored *next to* each
        amount (higher precision) — only enable it when ``raw_context`` is
        already loaded, since a deferred JSONField would trigger a query per
        row.
        """
        anomalies = self._collect(decision, use_raw_context=use_raw_context)
        if not anomalies:
            return Outcome(slug=self.slug, status=STATUS_CONSISTENT)

        findings = [
            self.finding(
                kind=a.kind,
                reason=a.reason,
                target=TARGET_UNUSABLE,
                field_id=a.field_id,
                source_field=a.source_field,
                recorded=str(a.amount),
                suggested="",  # the real amount is unknown — never guess
                note=a.note,
                payload={
                    "matched_value": a.matched_value,
                    "parent_key_path": a.parent_key_path,
                },
            )
            for a in anomalies
        ]
        return Outcome(slug=self.slug, status=STATUS_DETECTED, findings=findings)

    def apply(self, decision, outcome: Outcome, *, dry_run: bool = False, **kwargs) -> int:
        """
        Write the invalid-amount marker for every flagged field.

        Delegated to ``AmountCorrectionService.flag_non_monetary_values`` so
        the marker vocabulary and the "never touch ``verified_amount``"
        invariant live in exactly one place.  Idempotent.
        """
        from core.services.amount_correction_service import AmountCorrectionService

        anomalies = AmountCorrectionService().flag_non_monetary_values(
            decision, dry_run=dry_run
        )
        return 0 if dry_run else len(anomalies)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _collect(decision, *, use_raw_context: bool = False):
        from core.services.non_monetary_value_guard import collect_non_monetary_values

        return collect_non_monetary_values(
            decision, use_raw_context=use_raw_context
        )
