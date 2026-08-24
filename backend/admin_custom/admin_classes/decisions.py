from django import forms
from django.contrib import admin, messages
from django.db.models import Exists, OuterRef
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from api.redis_keys import ADMIN_FEEDBACK_POOL_CORRECTED_DECISIONS_KEY

class ImportDecisionsForm(forms.Form):
    """Form for importing decisions"""

    pass  # Add form fields as needed


class AmountCorrectionForm(forms.Form):
    """Form for batch amount correction with configurable parameters."""

    threshold = forms.DecimalField(
        max_digits=15,
        decimal_places=2,
        initial=100000,
        help_text="Minimum computed total (€) for a decision to be checked.",
    )
    start_date = forms.DateField(
        required=False,
        help_text="Optional: only check decisions issued on/after this date.",
    )
    end_date = forms.DateField(
        required=False,
        help_text="Optional: only check decisions issued on/before this date.",
    )
    limit = forms.IntegerField(
        required=False,
        initial=500,
        min_value=1,
        help_text="Max number of decisions to process (default 500).",
    )
    dry_run = forms.BooleanField(
        required=False,
        initial=False,
        help_text="If checked, only report what WOULD be corrected (no changes).",
    )
    read_if_missing = forms.BooleanField(
        required=False,
        initial=True,
        help_text=(
            "If checked, decisions without extracted text are read first "
            "(download + extract) before correction. Uncheck to only process "
            "already-extracted decisions and keep batch runs fast."
        ),
    )


class DiavgeiaFeedbackForm(forms.Form):
    """Form for batch Diavgeia feedback reporting with configurable parameters."""

    reporter_email = forms.EmailField(
        required=False,
        help_text="Email to report from (blank uses the configured default).",
    )
    feedback_errors = forms.CharField(
        required=False,
        initial="FE_1",
        help_text="Comma-separated feedback error codes (e.g. FE_1).",
    )
    limit = forms.IntegerField(
        required=False,
        initial=500,
        min_value=1,
        help_text="Max number of unreported decisions to process (default 500).",
    )
    dry_run = forms.BooleanField(
        required=False,
        initial=False,
        help_text="If checked, only report what WOULD be sent (no API calls).",
    )
    start_date = forms.DateField(
        required=False,
        help_text="Optional: only report decisions issued on/after this date.",
    )
    end_date = forms.DateField(
        required=False,
        help_text="Optional: only report decisions issued on/before this date.",
    )


def _corrected_fields_count() -> int:
    """Count amount-field rows that have a verified (corrected) amount.

    Uses the partial index ``idx_daf_verified_amounts`` so this is an
    index-only scan instead of a full table scan (the table has millions
    of rows).
    """
    from core.models.entities import DecisionAmountField

    return (
        DecisionAmountField.objects
        .filter(verified_amount__isnull=False)
        .count()
    )


def _corrected_decisions_count() -> int:
    """Count distinct decisions that have at least one corrected amount.

    Counts ``decision_id`` directly on the amount-field table rather than
    joining ``Decision`` and doing ``SELECT DISTINCT`` of every column, then
    counting the subquery — a fraction of the work. Backed by the same
    partial index (index-only scan).
    """
    from core.models.entities import DecisionAmountField

    return (
        DecisionAmountField.objects
        .filter(verified_amount__isnull=False)
        .values("decision_id")
        .distinct()
        .count()
    )


def _approximate_table_count(model) -> int:
    """Near-instant row estimate from the Postgres catalog (pg_class.reltuples).

    Falls back to a real ``COUNT(*)`` only if the estimate is unavailable.
    """
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute(
            "SELECT reltuples::bigint FROM pg_class WHERE relname = %s",
            [model._meta.db_table],
        )
        row = cur.fetchone()
    if row and row[0]:
        return int(row[0])
    return model.objects.count()


def _get_cached_stats(cache_key, compute, timeout=300):
    """Return stats from the Redis cache, computing them on a miss.

    Redis failures are swallowed so a cache outage never blocks the admin
    page — we simply recompute the stats.
    """
    from django.core.cache import cache

    try:
        stats = cache.get(cache_key)
        if stats is not None:
            return stats
    except Exception:
        pass
    stats = compute()
    try:
        cache.set(cache_key, stats, timeout)
    except Exception:
        pass
    return stats


class EstimatedCountPaginator:
    """Paginator that uses Postgres catalog estimates instead of COUNT(*).

    Replaces Django's ``django.core.paginator.Paginator`` for large tables
    where an exact ``COUNT(*)`` — especially one carrying ``EXISTS``
    subqueries — is prohibitively slow.  The estimate comes from
    ``pg_class.reltuples`` and is labelled "≈" in the template.
    """

    def __init__(self, queryset, per_page=25, orphans=0):
        self.queryset = queryset
        self.per_page = per_page
        self.orphans = orphans
        self._count = None  # cached estimate

    def page(self, number):
        """Return a single page, computing an estimated count on first call."""
        from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator

        if self._count is None:
            self._count = _approximate_table_count(self.queryset.model)
        # Build a real Paginator just for slicing (its .page() only slices,
        # it doesn't re-count because we pass the count directly).
        paginator = Paginator(self.queryset, self.per_page, orphans=self.orphans)
        paginator._count = self._count
        return paginator.page(number)

    @property
    def count(self):
        if self._count is None:
            self._count = _approximate_table_count(self.queryset.model)
        return self._count

    @property
    def num_pages(self):
        if self._count is None:
            self._count = _approximate_table_count(self.queryset.model)
        if self._count == 0:
            return 1
        return (self._count + self.per_page - 1) // self.per_page


class HasCorrectedAmountsFilter(admin.SimpleListFilter):
    """Filter decisions that have at least one corrected (verified) amount."""

    title = "amount correction"
    parameter_name = "has_corrected_amounts"

    def lookups(self, request, model_admin):
        return (
            ("yes", "Has corrected amounts"),
            ("no", "No corrected amounts"),
        )

    def queryset(self, request, queryset):
        from core.models.entities import DecisionAmountField

        corrected = DecisionAmountField.objects.filter(
            decision=OuterRef("pk"), verified_amount__isnull=False
        )
        if self.value() == "yes":
            return queryset.filter(Exists(corrected))
        if self.value() == "no":
            return queryset.filter(~Exists(corrected))
        return queryset


class ReportedStatusFilter(admin.SimpleListFilter):
    """Filter decisions by whether they've been reported to Diavgeia."""

    title = "reported to Diavgeia"
    parameter_name = "reported_status"

    def lookups(self, request, model_admin):
        return (
            ("yes", "Reported"),
            ("no", "Not reported"),
        )

    def queryset(self, request, queryset):
        from core.models.diavgeia_feedback_report import DiavgeiaFeedbackReport

        reported = DiavgeiaFeedbackReport.objects.filter(
            decision=OuterRef("pk"), reported=True
        )
        if self.value() == "yes":
            return queryset.filter(Exists(reported))
        if self.value() == "no":
            return queryset.filter(~Exists(reported))
        return queryset


class DecisionAdmin(admin.ModelAdmin):
    """Admin interface for Decision model"""

    list_display = (
        "ada", "subject", "organization", "issue_date", "status",
        "corrected_amounts_link", "reported_status",
    )
    list_filter = (
        "status", "decision_type", "has_private_data",
        HasCorrectedAmountsFilter, ReportedStatusFilter,
    )
    search_fields = ("ada", "subject", "protocol_number")
    date_hierarchy = "issue_date"
    change_list_template = "admin/core/decision/change_list.html"

    actions = [
        "import_decisions",
        "check_pipeline_health",
        "fix_common_issues",
        "correct_amounts",
        "clear_verified_amounts",
        "report_feedback",
        "reset_feedback_reports",
    ]

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["batch_correct_url"] = reverse(
            "admin:decision_batch_correct_amounts"
        )
        extra_context["corrected_pool_url"] = reverse(
            "admin:decision_corrected_amounts_pool"
        )
        extra_context["feedback_pool_url"] = reverse(
            "admin:decision_feedback_pool"
        )
        return super().changelist_view(request, extra_context)

    @admin.display(description="Reported")
    def reported_status(self, obj):
        """Badge + reference when this decision was reported to Diavgeia."""
        report = getattr(obj, "diavgeia_feedback_report", None)
        if not report or not report.reported:
            return "—"
        when = (
            report.reported_at.strftime("%Y-%m-%d %H:%M")
            if report.reported_at
            else ""
        )
        ref = f"<code>{report.reference}</code>" if report.reference else ""
        return format_html(
            '<span style="background:#d1ecf1;color:#0c5460;padding:2px 8px;'
            'border-radius:10px;">✓ {} {}</span>',
            when,
            ref,
        )

    @admin.display(description="Corrected")
    def corrected_amounts_link(self, obj):
        """Badge + frontend link when a decision has corrected amounts."""
        from core.models.entities import DecisionAmountField

        count = DecisionAmountField.objects.filter(
            decision=obj, verified_amount__isnull=False
        ).count()
        if not count:
            return "—"
        from core.services.amount_correction_service import AmountCorrectionService

        url = AmountCorrectionService.frontend_url(obj)
        return format_html(
            '<a href="{}" target="_blank" '
            'style="background:#d4edda;color:#155724;padding:2px 8px;'
            'border-radius:10px;text-decoration:none;">'
            "✓ {} field{} · view</a>",
            url,
            count,
            "s" if count != 1 else "",
        )

    @admin.action(description="[AMOUNT] Verify & correct amounts (cents-based)")
    def correct_amounts(self, request, queryset):
        """
        Run cents-based amount detection on selected decisions and
        correct individual DecisionAmountField rows that show a
        decimal-shift discrepancy.
        """
        from core.services.amount_correction_service import AmountCorrectionService

        svc = AmountCorrectionService(threshold=0)  # no threshold — explicit selection
        decisions = list(queryset)

        if len(decisions) > 100:
            messages.warning(
                request,
                f"Amount correction limited to 100 decisions "
                f"(selected {len(decisions)})",
            )
            decisions = decisions[:100]

        total_corrected = 0
        total_fields = 0
        consistent = 0
        skipped = 0
        details: list[str] = []

        for decision in decisions:
            try:
                result = svc.correct_decision(decision)
                if result["status"] == "corrected":
                    fields = result["fields_corrected"]
                    total_corrected += 1
                    total_fields += fields
                    for c in result["corrections"]:
                        details.append(
                            f"  {decision.ada}/{c['source_field']}: "
                            f"€{c['db_amount']} → €{c['corrected_to']} "
                            f"(factor {c['clone_factor']})"
                        )
                elif result["status"] == "consistent":
                    consistent += 1
                else:
                    skipped += 1
            except Exception as exc:
                messages.error(request, f"Failed on {decision.ada}: {exc}")
                skipped += 1

        if total_corrected:
            messages.success(
                request,
                f"Corrected {total_fields} field(s) in {total_corrected} "
                f"decision(s):\n" + "\n".join(details[:10])
                + ("\n  ..." if len(details) > 10 else ""),
            )
        if consistent:
            messages.info(request, f"{consistent} decision(s) already consistent.")
        if skipped:
            messages.info(request, f"{skipped} decision(s) skipped (no text, etc.).")

        # Invalidate caches so corrected amounts propagate
        if total_corrected:
            from core.services.response_cache_service import response_cache
            count = response_cache.invalidate_prefix("top_")
            messages.info(request, f"Invalidated {count} analytics cache keys.")

    @admin.action(description="[AMOUNT] Clear verified amounts (reset to DB)")
    def clear_verified_amounts(self, request, queryset):
        """Clear verified_amount on DecisionAmountField rows for selected decisions."""
        from core.models.entities import DecisionAmountField

        count = (
            DecisionAmountField.objects
            .filter(decision__in=queryset, verified_amount__isnull=False)
            .update(verified_amount=None, amount_verified_at=None)
        )
        messages.success(
            request, f"Cleared verified amounts for {count} field(s)."
        )

        # Invalidate caches
        from core.services.response_cache_service import response_cache
        response_cache.invalidate_prefix("top_")

    # ── Feedback reporting actions ───────────────────────────────────

    @admin.action(description="[FEEDBACK] Report corrected amounts to Diavgeia")
    def report_feedback(self, request, queryset):
        """
        Report selected decisions' corrected (wrong) amounts to the Diavgeia
        feedback API.  Skips decisions already reported.
        """
        from django.db.models import Exists, OuterRef

        from core.models.diavgeia_feedback_report import DiavgeiaFeedbackReport
        from core.services.diavgeia_feedback_service import DiavgeiaFeedbackService

        svc = DiavgeiaFeedbackService()

        already_reported = Exists(
            DiavgeiaFeedbackReport.objects.filter(
                decision=OuterRef("pk"), reported=True
            )
        )
        already = queryset.filter(already_reported).count()
        decisions = list(queryset.exclude(already_reported))

        if len(decisions) > 50:
            messages.warning(
                request,
                f"Feedback limited to 50 decisions (selected {len(decisions)})",
            )
            decisions = decisions[:50]

        reported = 0
        errors = 0
        for decision in decisions:
            result = svc.report_decision(decision)
            if result["status"] == "reported":
                reported += 1
            else:
                errors += 1

        if reported:
            messages.success(
                request, f"Reported {reported} decision(s) to Diavgeia."
            )
        if already:
            messages.info(request, f"{already} selected decision(s) already reported.")
        if errors:
            messages.error(request, f"{errors} decision(s) failed to report.")

    @admin.action(description="[FEEDBACK] Reset reported flags (re-test)")
    def reset_feedback_reports(self, request, queryset):
        """Delete the DiavgeiaFeedbackReport rows for selected decisions."""
        from core.models.diavgeia_feedback_report import DiavgeiaFeedbackReport

        count, _ = (
            DiavgeiaFeedbackReport.objects
            .filter(decision__in=queryset)
            .delete()
        )
        messages.success(
            request, f"Reset feedback reports on {count} decision(s)."
        )

    # ── Custom admin view: batch amount correction ──────────────────

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "batch-correct-amounts/",
                self.admin_site.admin_view(self.batch_correct_amounts_view),
                name="decision_batch_correct_amounts",
            ),
            path(
                "corrected-amounts-pool/",
                self.admin_site.admin_view(self.corrected_amounts_pool_view),
                name="decision_corrected_amounts_pool",
            ),
            path(
                "correction-job/<uuid:job_id>/",
                self.admin_site.admin_view(self.correction_job_status_view),
                name="decision_correction_job_status",
            ),
            # ── Diavgeia feedback (wrong-amount reporting) ────────────
            path(
                "feedback-pool/",
                self.admin_site.admin_view(self.feedback_pool_view),
                name="decision_feedback_pool",
            ),
            path(
                "feedback-report/<int:decision_id>/",
                self.admin_site.admin_view(self.report_decision_view),
                name="decision_feedback_report",
            ),
            path(
                "feedback-report-selected/",
                self.admin_site.admin_view(self.report_selected_view),
                name="decision_feedback_report_selected",
            ),
            path(
                "feedback-batch/",
                self.admin_site.admin_view(self.feedback_batch_view),
                name="decision_feedback_batch",
            ),
            path(
                "feedback-job/<uuid:job_id>/",
                self.admin_site.admin_view(self.feedback_job_status_view),
                name="decision_feedback_job_status",
            ),
        ]
        return custom_urls + urls

    def correction_job_status_view(self, request, job_id):
        """Live progress / results page for a correction job (auto-refresh)."""
        from core.models.amount_correction_job import AmountCorrectionJob
        from core.services.amount_correction_service import AmountCorrectionService

        job = AmountCorrectionJob.objects.prefetch_related(
            "results__decision"
        ).get(job_id=job_id)
        job.finalize_if_done()
        job.refresh_from_db()

        results = [
            {
                "ada": r.decision.ada,
                "subject": r.decision.subject,
                "status": r.status,
                "reason": r.reason,
                "group_correction": r.group_correction,
                "corrections": r.corrections,
                "frontend_url": AmountCorrectionService.frontend_url(r.decision),
            }
            for r in job.results.all()
        ]

        context = {
            **self.admin_site.each_context(request),
            "title": f"Correction Job {job.job_id}",
            "job": job,
            "results": results,
            "opts": self.model._meta,
        }
        return render(request, "admin/decision_correction_job.html", context)

    def corrected_amounts_pool_view(self, request):
        """
        List every decision that currently has corrected (verified) amounts.

        This is the "pool" of decisions whose metadata amounts disagreed with
        the document text — the set you may want to review or report to the
        Diavgeia API admins.
        """
        from core.models.decisions import Decision
        from core.models.entities import DecisionAmountField
        from core.services.amount_correction_service import (
            AmountCorrectionService,
        )

        decisions_qs = (
            Decision.objects
            .filter(amount_fields__verified_amount__isnull=False)
            .distinct()
            .order_by("-issue_date")
            .prefetch_related("amount_fields")
            .only("id", "ada", "subject", "issue_date")
        )

        rows = []
        for d in decisions_qs:
            corrected_fields = [
                f for f in d.amount_fields.all()
                if f.verified_amount is not None
            ]
            rows.append({
                "decision": d,
                "frontend_url": AmountCorrectionService.frontend_url(d),
                "fields": corrected_fields,
            })

        context = {
            **self.admin_site.each_context(request),
            "title": "Corrected Amounts Pool",
            "rows": rows,
            "total": len(rows),
            "opts": self.model._meta,
        }
        return render(request, "admin/decision_corrected_pool.html", context)

    def batch_correct_amounts_view(self, request):
        """
        Admin view for batch amount correction with configurable parameters.

        Allows the admin to specify:
          - Minimum amount threshold (€)
          - Optional issue-date range
          - Max decisions to process
          - Dry-run mode
        """
        from core.services.amount_correction_service import AmountCorrectionService

        if request.method == "POST":
            form = AmountCorrectionForm(request.POST)
            if form.is_valid():
                from core.models.amount_correction_job import AmountCorrectionJob
                from core.tasks.tasks_amount_correction import (
                    run_amount_correction_job,
                )

                job = AmountCorrectionJob.objects.create(
                    created_by=request.user if request.user.is_authenticated else None,
                    threshold=form.cleaned_data["threshold"],
                    start_date=form.cleaned_data["start_date"],
                    end_date=form.cleaned_data["end_date"],
                    limit=form.cleaned_data["limit"],
                    dry_run=form.cleaned_data["dry_run"],
                    read_if_missing=form.cleaned_data["read_if_missing"],
                )
                run_amount_correction_job.delay(job_id=str(job.job_id))

                messages.info(
                    request,
                    f"Correction job {job.job_id} dispatched to worker "
                    f"({'dry-run' if job.dry_run else 'applying corrections'}).",
                )
                return redirect(
                    reverse(
                        "admin:decision_correction_job_status",
                        args=[job.job_id],
                    )
                )
        else:
            form = AmountCorrectionForm()

        # Show current stats — computed lazily and cached briefly.
        #
        # These three numbers used to run full-table scans on EVERY page load:
        #   * already_corrected was a JOIN + SELECT DISTINCT of all columns + a
        #     COUNT over the subquery (the slowest of the three),
        #   * total_fields_corrected scanned the whole (millions-of-rows)
        #     DecisionAmountField table with no index on verified_amount,
        #   * total_decisions was a full COUNT(*) over millions of decisions.
        #
        # Now: corrected-amount counts hit the partial index
        # idx_daf_verified_amounts (index-only scan, DISTINCT on decision_id
        # only), total_decisions uses Postgres' catalog estimate, and all
        # three are cached in Redis for 5 minutes.
        from core.models.decisions import Decision

        stats = _get_cached_stats(
            "admin:batch_correct_amounts:stats:v1",
            lambda: {
                "already_corrected": _corrected_decisions_count(),
                "total_fields_corrected": _corrected_fields_count(),
                "total_decisions": _approximate_table_count(Decision),
            },
            timeout=300,
        )

        context = {
            **self.admin_site.each_context(request),
            "title": "Batch Amount Correction",
            "form": form,
            "already_corrected": stats["already_corrected"],
            "total_fields_corrected": stats["total_fields_corrected"],
            "total_decisions": stats["total_decisions"],
            "opts": self.model._meta,
        }
        return render(request, "admin/decision_batch_correct.html", context)

    # ── Custom admin views: Diavgeia feedback (wrong-amount reports) ──

    def feedback_pool_view(self, request):
        """
        Control panel for wrong-amount feedback reporting.

        Lists every decision with corrected amounts (verified_amount set),
        paginated, and filterable by:
          - reported status (reported / unreported / all)
          - issue-date range
          - free-text search (ADA / subject)

        Unreported rows get a one-click “Report” button; a “Report all
        pending” button creates a background batch job.
        """
        import time

        from django.core.paginator import Paginator
        from django.db.models import Exists, OuterRef, Prefetch, Q
        from loguru import logger
        from urllib.parse import urlencode

        from core.models.decisions import Decision
        from core.models.diavgeia_feedback_report import DiavgeiaFeedbackReport
        from core.models.entities import DecisionAmountField
        from core.services.diavgeia_feedback_service import DiavgeiaFeedbackService

        already_reported = Exists(
            DiavgeiaFeedbackReport.objects.filter(
                decision=OuterRef("pk"), reported=True
            )
        )

        # ── Parse filters first (used by stats and pagination) ──────
        reported = request.GET.get("reported", "no")
        start_date = request.GET.get("start_date", "").strip()
        end_date = request.GET.get("end_date", "").strip()
        q = request.GET.get("q", "").strip()

        # ── Global stats: cheap, index-backed counts ──────────────────
        #
        # The old implementation ran COUNT(*) over the whole Decision table
        # with two correlated EXISTS subqueries per row — the dominant cost
        # of this page.  Corrected-amount counts now hit the partial index
        # idx_daf_verified_amounts (index-only scan), and the reported count
        # reads the tiny DiavgeiaFeedbackReport table.
        _t_stats = time.perf_counter()
        # The corrected-decision count only changes when a correction batch
        # runs (not when reporting), so cache it briefly.  reported/pending
        # are computed live below so the header still updates instantly
        # after each report.
        total = _get_cached_stats(
            ADMIN_FEEDBACK_POOL_CORRECTED_DECISIONS_KEY,
            _corrected_decisions_count,
            timeout=300,
        )
        reported_ids = DiavgeiaFeedbackReport.objects.filter(
            reported=True
        ).values_list("decision_id", flat=True)
        total_reported = (
            DecisionAmountField.objects
            .filter(verified_amount__isnull=False, decision_id__in=reported_ids)
            .values("decision_id")
            .distinct()
            .count()
        )
        total_pending = total - total_reported
        _t_stats = time.perf_counter() - _t_stats

        # ── Build the filtered queryset ──────────────────────────────
        #
        # Start from the set of decisions that actually have corrected
        # amounts (derived from the amount-field table via its partial
        # index) instead of a correlated EXISTS over the whole Decision
        # table — that EXISTS forced PostgreSQL to probe every decision
        # row while hunting for the first page of matches.
        corrected_ids = (
            DecisionAmountField.objects
            .filter(verified_amount__isnull=False)
            .values("decision_id")
        )
        qs = Decision.objects.filter(id__in=corrected_ids)

        if reported == "yes":
            qs = qs.filter(already_reported)
        elif reported == "no":
            qs = qs.exclude(already_reported)

        if start_date:
            qs = qs.filter(issue_date_day__gte=start_date)
        if end_date:
            qs = qs.filter(issue_date_day__lte=end_date)

        if q:
            qs = qs.filter(Q(ada__icontains=q) | Q(subject__icontains=q))

        qs = (
            qs.order_by("-issue_date")
            .select_related("organization", "diavgeia_feedback_report")
            .prefetch_related(
                Prefetch(
                    "amount_fields",
                    queryset=DecisionAmountField.objects.filter(
                        verified_amount__isnull=False
                    ).only("id", "source_field_name", "amount", "verified_amount"),
                    to_attr="verified_fields",
                )
            )
        )

        # ── Pagination with an accurate, index-backed count ───────────
        #
        # A plain COUNT(*) over ``qs`` would re-run the correlated EXISTS
        # subqueries, so we count distinct decision_id directly on the
        # amount-field table (partial index, index-only) with the same
        # filters applied, then seed Paginator's cached count.
        _t_count = time.perf_counter()
        if not (start_date or end_date or q):
            # No date/search filters — the pagination count is exactly one of
            # the global stats already computed above.
            if reported == "yes":
                filtered_total = total_reported
            elif reported == "no":
                filtered_total = total_pending
            else:
                filtered_total = total
        else:
            count_qs = DecisionAmountField.objects.filter(verified_amount__isnull=False)
            if reported == "yes":
                count_qs = count_qs.filter(
                    decision__diavgeia_feedback_report__reported=True
                )
            elif reported == "no":
                count_qs = count_qs.exclude(
                    decision__diavgeia_feedback_report__reported=True
                )
            if start_date:
                count_qs = count_qs.filter(decision__issue_date_day__gte=start_date)
            if end_date:
                count_qs = count_qs.filter(decision__issue_date_day__lte=end_date)
            if q:
                count_qs = count_qs.filter(
                    Q(decision__ada__icontains=q) | Q(decision__subject__icontains=q)
                )
            filtered_total = count_qs.values("decision_id").distinct().count()
        _t_count = time.perf_counter() - _t_count

        per_page = 25
        paginator = Paginator(qs, per_page)
        # Seed Paginator's cached count so page()/num_pages never run COUNT(*).
        paginator.__dict__["count"] = filtered_total
        page = request.GET.get("page", "1")
        _t_page = time.perf_counter()
        try:
            page_obj = paginator.page(page)
        except Exception:
            page_obj = paginator.page(1)
        _t_page = time.perf_counter() - _t_page

        logger.info(
            "feedback_pool_view timing: stats={:.3f}s count={:.3f}s "
            "page={:.3f}s (reported={!r}, start_date={!r}, end_date={!r}, "
            "q={!r})",
            _t_stats,
            _t_count,
            _t_page,
            reported,
            start_date,
            end_date,
            q,
        )

        rows = []
        for d in page_obj.object_list:
            report = getattr(d, "diavgeia_feedback_report", None)
            activation_url = None
            if report and report.reported and report.reference:
                activation_url = DiavgeiaFeedbackService.activation_url(
                    report.reference
                )
            rows.append(
                {
                    "decision": d,
                    "verified_fields": getattr(d, "verified_fields", []),
                    "frontend_url": DiavgeiaFeedbackService.frontend_url(d),
                    "activation_url": activation_url,
                }
            )

        pagination_qs = urlencode(
            {
                k: v
                for k, v in {
                    "reported": reported,
                    "start_date": start_date,
                    "end_date": end_date,
                    "q": q,
                }.items()
                if v not in (None, "", "all")
            }
        )

        context = {
            **self.admin_site.each_context(request),
            "title": "Diavgeia Feedback Pool",
            "rows": rows,
            "page_obj": page_obj,
            "paginator": paginator,
            "total_pending": total_pending,
            "total_reported": total_reported,
            "total": total,
            "is_estimate": False,
            "filters": {
                "reported": reported,
                "start_date": start_date,
                "end_date": end_date,
                "q": q,
            },
            "pagination_qs": pagination_qs,
            "report_url": reverse(
                "admin:decision_feedback_report", kwargs={"decision_id": 0}
            )[:-2],  # strip trailing "0/" — template appends the real ID
            "batch_url": reverse("admin:decision_feedback_batch"),
            "report_selected_url": reverse(
                "admin:decision_feedback_report_selected"
            ),
            "opts": self.model._meta,
        }
        return render(request, "admin/decision_feedback_pool.html", context)

    def report_decision_view(self, request, decision_id):
        """
        Queue a single decision for Diavgeia feedback reporting.

        Reporting is a network call to the Diavgeia feedback API, so it runs
        on a worker instead of blocking this admin request.  Previously the
        browser sat loading until the API responded (up to ``timeout``
        seconds), which is what made the “Report” button feel slow.
        """
        from django.shortcuts import get_object_or_404

        from core.models.decisions import Decision
        from core.tasks.tasks_diavgeia_feedback import (
            report_single_decision_feedback,
        )

        decision = get_object_or_404(Decision, id=decision_id)
        report = getattr(decision, "diavgeia_feedback_report", None)
        if report and report.reported:
            messages.info(request, f"{decision.ada} was already reported.")
        else:
            report_single_decision_feedback.delay(decision_id=decision.id)
            messages.info(
                request,
                f"Report for {decision.ada} queued — it will be sent in the "
                "background. Refresh in a few seconds to see the result.",
            )

        referer = request.META.get("HTTP_REFERER")
        if referer and "feedback-pool" in referer:
            return redirect(referer)
        return redirect(reverse("admin:decision_feedback_pool"))

    def report_selected_view(self, request):
        """
        Queue several decisions for Diavgeia feedback reporting in one go.

        Each selected decision is enqueued as its own background task (the
        same path as the single “Report” button), so the request returns
        immediately.
        """
        from core.models.diavgeia_feedback_report import DiavgeiaFeedbackReport
        from core.tasks.tasks_diavgeia_feedback import (
            report_single_decision_feedback,
        )

        if request.method != "POST":
            return redirect(reverse("admin:decision_feedback_pool"))

        ids = []
        for raw in request.POST.getlist("decision_ids"):
            try:
                ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        if not ids:
            messages.warning(request, "No decisions selected.")
            return redirect(reverse("admin:decision_feedback_pool"))

        already = set(
            DiavgeiaFeedbackReport.objects
            .filter(decision_id__in=ids, reported=True)
            .values_list("decision_id", flat=True)
        )
        queued = 0
        for decision_id in ids:
            if decision_id in already:
                continue
            report_single_decision_feedback.delay(decision_id=decision_id)
            queued += 1

        if queued:
            messages.info(
                request,
                f"{queued} report(s) queued for background processing.",
            )
        skipped = len(ids) - queued
        if skipped:
            messages.info(request, f"{skipped} already reported — skipped.")

        referer = request.META.get("HTTP_REFERER")
        if referer and "feedback-pool" in referer:
            return redirect(referer)
        return redirect(reverse("admin:decision_feedback_pool"))

    def feedback_batch_view(self, request):
        """
        Create a background Diavgeia feedback job over all pending
        (unreported, corrected) decisions.
        """
        if request.method == "POST":
            form = DiavgeiaFeedbackForm(request.POST)
            if form.is_valid():
                from core.models.diavgeia_feedback_job import DiavgeiaFeedbackJob
                from core.tasks.tasks_diavgeia_feedback import run_feedback_job

                errors_raw = form.cleaned_data["feedback_errors"] or "FE_1"
                feedback_errors = [
                    e.strip() for e in errors_raw.split(",") if e.strip()
                ]

                job = DiavgeiaFeedbackJob.objects.create(
                    created_by=(
                        request.user if request.user.is_authenticated else None
                    ),
                    reporter_email=form.cleaned_data["reporter_email"] or "",
                    feedback_errors=feedback_errors,
                    limit=form.cleaned_data["limit"],
                    dry_run=form.cleaned_data["dry_run"],
                    start_date=form.cleaned_data["start_date"],
                    end_date=form.cleaned_data["end_date"],
                )
                run_feedback_job.delay(job_id=str(job.job_id))

                messages.info(
                    request,
                    f"Feedback job {job.job_id} dispatched to worker "
                    f"({'dry-run' if job.dry_run else 'sending reports'}).",
                )
                return redirect(
                    reverse(
                        "admin:decision_feedback_job_status",
                        args=[job.job_id],
                    )
                )
        else:
            form = DiavgeiaFeedbackForm()

        from core.services.diavgeia_feedback_service import DiavgeiaFeedbackService

        svc = DiavgeiaFeedbackService()
        total_pending = svc.pending_decisions().count()

        context = {
            **self.admin_site.each_context(request),
            "title": "Batch Diavgeia Feedback",
            "form": form,
            "total_pending": total_pending,
            "opts": self.model._meta,
        }
        return render(request, "admin/decision_feedback_batch.html", context)

    def feedback_job_status_view(self, request, job_id):
        """Live progress / results page for a feedback job (auto-refresh)."""
        from core.models.diavgeia_feedback_job import (
            DiavgeiaFeedbackJob,
            DiavgeiaFeedbackJobResult,
        )

        job = DiavgeiaFeedbackJob.objects.get(job_id=job_id)
        job.finalize_if_done()
        job.refresh_from_db()

        results = [
            {
                "ada": r.decision.ada,
                "subject": r.decision.subject,
                "status": r.status,
                "reason": r.reason,
                "reference": r.reference,
                "response": r.response,
            }
            for r in job.results.select_related("decision").all()
        ]

        context = {
            **self.admin_site.each_context(request),
            "title": f"Feedback Job {job.job_id}",
            "job": job,
            "results": results,
            "opts": self.model._meta,
        }
        return render(request, "admin/diavgeia_feedback_job.html", context)

    # ── Existing actions ─────────────────────────────────────────────

    def import_decisions(self, request, queryset=None):
        """Import decisions action"""
        # Implementation

    def check_pipeline_health(self, request, queryset):
        """Run health checks on selected decisions"""
        from core.models.decision_health import HealthStatus
        from core.services.decision_health_service import DecisionHealthService

        health_service = DecisionHealthService()
        decisions = list(queryset)

        if len(decisions) > 50:
            messages.warning(
                request,
                f"Health check limited to 50 decisions (selected {len(decisions)})",
            )
            decisions = decisions[:50]

        # Run bulk health checks
        results = health_service.bulk_check_decisions(decisions)

        # Show summary message
        summary = results["summary"]
        messages.success(
            request,
            f"Health check completed: {summary['healthy']} healthy, "
            f"{summary['warnings']} warnings, {summary['errors']} errors",
        )

        # Show specific issues if any
        if summary["errors"] > 0:
            error_decisions = [
                hc.decision.ada
                for hc in results["health_checks"]
                if hc.overall_status == HealthStatus.ERROR
            ][
                :5
            ]  # Show first 5
            messages.error(
                request,
                f"Decisions with errors: {', '.join(error_decisions)}"
                + (
                    f" and {summary['errors'] - 5} more"
                    if summary["errors"] > 5
                    else ""
                ),
            )

    check_pipeline_health.short_description = "[SCAN] Check pipeline health"

    def fix_common_issues(self, request, queryset):
        """Attempt to fix common issues for selected decisions"""
        from core.tasks.health_check_tasks import auto_fix_simple_issues

        decision_count = queryset.count()

        if decision_count > 20:
            messages.warning(
                request, f"Auto-fix limited to 20 decisions (selected {decision_count})"
            )
            decision_adas = list(queryset[:20].values_list("ada", flat=True))
        else:
            decision_adas = list(queryset.values_list("ada", flat=True))

        # Queue auto-fix task for these specific decisions
        try:
            auto_fix_simple_issues.delay(decision_adas=decision_adas)

            messages.success(
                request,
                f"Queued auto-fix for {len(decision_adas)} decisions. "
                "Check back in a few minutes to see results.",
            )
        except Exception as e:
            messages.error(request, f"Failed to queue auto-fix: {str(e)}")

    fix_common_issues.short_description = "[CONFIG] Attempt auto-fix"


class AttachmentAdmin(admin.ModelAdmin):
    """Admin interface for Attachment model"""

    list_display = ("id", "decision", "filename", "mime_type")
    list_filter = ("mime_type",)
    search_fields = ("filename", "decision__ada")


class OrganizationAdmin(admin.ModelAdmin):
    """Admin interface for Organization model"""

    list_display = ("label", "vat_number", "category")
    list_filter = ("category",)
    search_fields = ("label", "vat_number")


class UnitAdmin(admin.ModelAdmin):
    """Admin interface for Unit model"""

    list_display = ("label", "uid", "organization")
    search_fields = ("label", "uid")
    list_filter = ("organization",)


class SignerAdmin(admin.ModelAdmin):
    """Admin interface for Signer model"""

    list_display = ("uid", "first_name", "last_name", "organization", "active")
    search_fields = ("uid", "first_name", "last_name")
    list_filter = ("active", "organization")
