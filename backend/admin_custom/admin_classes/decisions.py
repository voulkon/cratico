from django import forms
from django.contrib import admin, messages
from django.db.models import Exists, OuterRef
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html


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


class DecisionAdmin(admin.ModelAdmin):
    """Admin interface for Decision model"""

    list_display = (
        "ada", "subject", "organization", "issue_date", "status",
        "corrected_amounts_link",
    )
    list_filter = (
        "status", "decision_type", "has_private_data",
        HasCorrectedAmountsFilter,
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
    ]

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["batch_correct_url"] = reverse(
            "admin:decision_batch_correct_amounts"
        )
        extra_context["corrected_pool_url"] = reverse(
            "admin:decision_corrected_amounts_pool"
        )
        return super().changelist_view(request, extra_context)

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
