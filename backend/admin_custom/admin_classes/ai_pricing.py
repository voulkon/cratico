from django.contrib import admin
from django.db.models import Sum
from django.urls import reverse
from django.utils.html import format_html


class AIModelPricingAdmin(admin.ModelAdmin):
    """Admin interface for AI Model Pricing"""

    list_display = [
        "provider",
        "display_name",
        "model_name",
        "model_type",
        "input_price_display",
        "output_price_display",
        "effective_date",
        "is_active",
    ]

    list_filter = [
        "provider",
        "model_type",
        "is_active",
        "effective_date",
    ]

    search_fields = [
        "provider",
        "model_name",
        "display_name",
        "notes",
    ]

    readonly_fields = [
        "created_at",
        "updated_at",
    ]

    fieldsets = (
        (
            "Model Information",
            {
                "fields": (
                    "provider",
                    "model_name",
                    "display_name",
                    "model_type",
                    "context_window",
                ),
                "description": "model_name is the actual API identifier, display_name is human-friendly",
            },
        ),
        (
            "Pricing",
            {
                "fields": ("pricing_unit", "input_price", "output_price"),
                "description": "Pricing is per unit selected (per million or per thousand tokens)",
            },
        ),
        ("Status", {"fields": ("is_active", "effective_date", "notes")}),
        (
            "Metadata",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    date_hierarchy = "effective_date"

    ordering = ["-effective_date", "provider", "model_name"]

    def input_price_display(self, obj):
        """Display input price formatted"""
        unit = "/M" if obj.pricing_unit == "PER_MILLION" else "/K"
        formatted_price = f"{float(obj.input_price):.4f}"
        return format_html("${}{}", formatted_price, unit)

    input_price_display.short_description = "Input Price"
    input_price_display.admin_order_field = "input_price"

    def output_price_display(self, obj):
        """Display output price formatted"""
        if obj.output_price:
            unit = "/M" if obj.pricing_unit == "PER_MILLION" else "/K"
            formatted_price = f"{float(obj.output_price):.4f}"
            return format_html("${}{}", formatted_price, unit)
        return format_html('<span style="color: #999;">N/A</span>')

    output_price_display.short_description = "Output Price"
    output_price_display.admin_order_field = "output_price"

    actions = ["activate_pricing", "deactivate_pricing"]

    def activate_pricing(self, request, queryset):
        """Mark selected pricing as active"""
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} pricing entries marked as active.")

    activate_pricing.short_description = "Mark as active"

    def deactivate_pricing(self, request, queryset):
        """Mark selected pricing as inactive"""
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} pricing entries marked as inactive.")

    deactivate_pricing.short_description = "Mark as inactive"


class TaskOutputEstimateAdmin(admin.ModelAdmin):
    """Admin interface for Task Output Estimates"""

    list_display = [
        "task_type",
        "output_ratio_display",
        "fixed_tokens_display",
        "overhead_display",
        "description",
    ]

    search_fields = [
        "task_type",
        "description",
    ]

    readonly_fields = [
        "created_at",
        "updated_at",
    ]

    fieldsets = (
        ("Task Information", {"fields": ("task_type", "description")}),
        (
            "Output Estimation",
            {
                "fields": ("output_ratio", "fixed_output_tokens"),
                "description": "Either use ratio (percentage of input) or fixed token count",
            },
        ),
        (
            "Overhead",
            {
                "fields": ("prompt_overhead_ratio",),
                "description": "Additional tokens for system prompts and instructions",
            },
        ),
        (
            "Metadata",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    ordering = ["task_type"]

    def output_ratio_display(self, obj):
        """Display output ratio as percentage"""
        return format_html("{}%", float(obj.output_ratio) * 100)

    output_ratio_display.short_description = "Output Ratio"
    output_ratio_display.admin_order_field = "output_ratio"

    def fixed_tokens_display(self, obj):
        """Display fixed tokens or N/A"""
        if obj.fixed_output_tokens:
            return format_html("{} tokens", obj.fixed_output_tokens)
        return format_html('<span style="color: #999;">N/A (uses ratio)</span>')

    fixed_tokens_display.short_description = "Fixed Tokens"

    def overhead_display(self, obj):
        """Display overhead as percentage"""
        return format_html("{}%", float(obj.prompt_overhead_ratio) * 100)

    overhead_display.short_description = "Prompt Overhead"
    overhead_display.admin_order_field = "prompt_overhead_ratio"


class AIJobDefinitionAdmin(admin.ModelAdmin):
    """Admin interface for AI Job Definitions"""

    list_display = [
        "display_name",
        "job_name",
        "default_provider",
        "default_model",
        "batch_size",
        "is_active",
        "execution_stats_display",
        "estimate_cost_link",
    ]

    list_filter = [
        "is_active",
        "default_provider",
        "analysis_type",
        "output_estimation_mode",
    ]

    search_fields = [
        "job_name",
        "display_name",
        "description",
    ]

    readonly_fields = [
        "created_at",
        "updated_at",
        "execution_summary",
        "available_models_display",
        "estimate_cost_link",
    ]

    fieldsets = (
        (
            "Basic Information",
            {
                "fields": (
                    "job_name",
                    "display_name",
                    "description",
                    "is_active",
                    "estimate_cost_link",
                )
            },
        ),
        (
            "Job Implementation",
            {
                "fields": ("algorithm_module", "algorithm_class"),
                "description": "Python module and class that implements this job (e.g., core.jobs.daily_summary, DailySummaryJob)",
            },
        ),
        (
            "Default AI Configuration",
            {
                "fields": (
                    "default_provider",
                    "default_model",
                    "analysis_type",
                    "available_models_display",
                ),
                "description": "Select provider and model. Use the exact model_name from AI Model Pricing (not display_name).",
            },
        ),
        (
            "Prompt Configuration",
            {
                "fields": (
                    "system_prompt",
                    "prompt_overhead_tokens",
                    "prompt_overhead_percentage",
                ),
                "description": "Configure how prompts add overhead to token counts",
            },
        ),
        (
            "Output Estimation",
            {
                "fields": (
                    "output_estimation_mode",
                    "output_ratio",
                    "fixed_output_tokens",
                ),
                "description": "How to estimate output token count",
            },
        ),
        (
            "Batch Processing",
            {
                "fields": ("batch_size", "items_per_batch_context"),
                "description": "Configure how items are batched for processing",
            },
        ),
        (
            "Execution Settings",
            {"fields": ("max_concurrent_executions", "extra_config")},
        ),
        ("Statistics", {"fields": ("execution_summary",), "classes": ("collapse",)}),
        (
            "Metadata",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    actions = ["activate_jobs", "deactivate_jobs", "estimate_sample_cost"]

    def estimate_cost_link(self, obj):
        """Link to estimate cost page"""
        url = reverse("admin:estimate_job_cost", args=[obj.pk])
        return format_html('<a class="button" href="{}">Estimate Cost</a>', url)

    estimate_cost_link.short_description = "Actions"

    def execution_stats_display(self, obj):
        """Display execution statistics"""
        total = obj.executions.count()
        completed = obj.executions.filter(status="COMPLETED").count()
        if total > 0:
            return format_html(
                '{} total<br><span style="color: green;">{} completed</span>',
                total,
                completed,
            )
        return format_html('<span style="color: #999;">No executions</span>')

    execution_stats_display.short_description = "Executions"

    def execution_summary(self, obj):
        """Display detailed execution summary"""
        executions = obj.executions.all()
        completed = executions.filter(status="COMPLETED")

        if not completed.exists():
            return format_html("<em>No completed executions yet</em>")

        total_cost = completed.aggregate(total=Sum("actual_cost_usd"))["total"] or 0

        total_items = completed.aggregate(total=Sum("items_processed"))["total"] or 0

        avg_cost = total_cost / total_items if total_items > 0 else 0

        html = f"""
        <div style="background: #f8f9fa; padding: 15px; border-radius: 5px;">
            <h4>Execution Statistics</h4>
            <table>
                <tr><td><strong>Total Executions:</strong></td><td>{executions.count()}</td></tr>
                <tr><td><strong>Completed:</strong></td><td style="color: green;">{completed.count()}</td></tr>
                <tr><td><strong>Total Items Processed:</strong></td><td>{total_items:,}</td></tr>
                <tr><td><strong>Total Cost:</strong></td><td>${total_cost:.6f}</td></tr>
                <tr><td><strong>Average Cost/Item:</strong></td><td>${avg_cost:.6f}</td></tr>
            </table>
        </div>
        """
        return format_html(html)

    execution_summary.short_description = "Execution Summary"

    def available_models_display(self, obj):
        """Display available models from AIModelPricing"""
        from core.models.ai_pricing import AIModelPricing

        # Get active models grouped by provider
        models = AIModelPricing.objects.filter(is_active=True).order_by(
            "provider", "model_name"
        )

        if not models.exists():
            return format_html(
                '<em style="color: #999;">No active models found. Add models in AI Model Pricing first.</em>'
            )

        html = '<div style="background: #f0f8ff; padding: 15px; border-radius: 5px; margin-top: 10px;">'
        html += (
            '<h4 style="margin-top: 0;">Available Models (from AI Model Pricing)</h4>'
        )
        html += '<p style="font-size: 11px; color: #666;">Copy the <strong>Model Name</strong> (not Display Name) to the "Default model" field above.</p>'

        current_provider = None
        for model in models:
            if model.provider != current_provider:
                if current_provider:
                    html += "</table>"
                html += f'<h5 style="color: #0066cc; margin-top: 15px; margin-bottom: 5px;">{model.provider}</h5>'
                html += '<table style="width: 100%; border-collapse: collapse; font-size: 12px;">'
                html += '<tr style="background: #e8f4f8;"><th style="text-align: left; padding: 5px;">Display Name</th><th style="text-align: left; padding: 5px;">Model Name (use this)</th><th style="text-align: right; padding: 5px;">Input</th><th style="text-align: right; padding: 5px;">Output</th></tr>'
                current_provider = model.provider

            display = model.display_name or model.model_name
            unit = "/M" if model.pricing_unit == "PER_MILLION" else "/K"
            output_price = (
                f"${float(model.output_price):.4f}{unit}"
                if model.output_price
                else "N/A"
            )

            html += f"""
            <tr style="border-bottom: 1px solid #ddd;">
                <td style="padding: 5px;">{display}</td>
                <td style="padding: 5px; font-family: monospace; background: #fff3cd;">{model.model_name}</td>
                <td style="padding: 5px; text-align: right;">${float(model.input_price):.4f}{unit}</td>
                <td style="padding: 5px; text-align: right;">{output_price}</td>
            </tr>
            """

        html += "</table></div>"
        return format_html(html)

    available_models_display.short_description = "Available Models Reference"

    def activate_jobs(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} jobs activated.")

    activate_jobs.short_description = "Activate selected jobs"

    def deactivate_jobs(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} jobs deactivated.")

    deactivate_jobs.short_description = "Deactivate selected jobs"


class AIJobExecutionAdmin(admin.ModelAdmin):
    """Admin interface for AI Job Executions"""

    list_display = [
        "execution_id",
        "job_definition",
        "status",
        "started_at",
        "items_processed",
        "cost_display",
        "variance_display",
    ]

    list_filter = [
        "status",
        "job_definition",
        "started_at",
    ]

    search_fields = [
        "execution_id",
        "job_definition__job_name",
        "job_definition__display_name",
    ]

    readonly_fields = [
        "execution_id",
        "job_definition",
        "started_at",
        "completed_at",
        "created_at",
        "cost_breakdown",
        "token_breakdown",
    ]

    fieldsets = (
        ("Execution Info", {"fields": ("execution_id", "job_definition", "status")}),
        ("Configuration", {"fields": ("provider_used", "model_used")}),
        (
            "Progress",
            {
                "fields": (
                    "items_processed",
                    "items_scope",
                    "started_at",
                    "completed_at",
                    "execution_time_seconds",
                )
            },
        ),
        ("Costs", {"fields": ("cost_breakdown", "token_breakdown")}),
        (
            "Results",
            {"fields": ("result_summary", "error_message"), "classes": ("collapse",)},
        ),
    )

    date_hierarchy = "started_at"

    def cost_display(self, obj):
        """Display cost information"""
        if obj.actual_cost_usd:
            return format_html("${:.6f}", obj.actual_cost_usd)
        elif obj.estimated_cost_usd:
            return format_html(
                '<span style="color: #999;">${:.6f} (est)</span>',
                obj.estimated_cost_usd,
            )
        return format_html('<span style="color: #999;">N/A</span>')

    cost_display.short_description = "Cost"
    cost_display.admin_order_field = "actual_cost_usd"

    def variance_display(self, obj):
        """Display cost variance"""
        variance_pct = obj.cost_variance_percentage
        if variance_pct is not None:
            color = (
                "red"
                if variance_pct > 10
                else "green" if variance_pct < -10 else "orange"
            )
            return format_html(
                '<span style="color: {};">{:+.1f}%</span>', color, variance_pct
            )
        return format_html('<span style="color: #999;">N/A</span>')

    variance_display.short_description = "Variance"

    def cost_breakdown(self, obj):
        """Display cost breakdown"""
        html = """
        <table style="width: 100%;">
            <tr><td><strong>Estimated Cost:</strong></td><td>${:.6f}</td></tr>
            <tr><td><strong>Actual Cost:</strong></td><td>{}</td></tr>
            <tr><td><strong>Variance:</strong></td><td>{}</td></tr>
        </table>
        """.format(
            obj.estimated_cost_usd or 0,
            f"${obj.actual_cost_usd:.6f}" if obj.actual_cost_usd else "N/A",
            (
                f"{obj.cost_variance:+.6f} ({obj.cost_variance_percentage:+.1f}%)"
                if obj.cost_variance is not None
                else "N/A"
            ),
        )
        return format_html(html)

    cost_breakdown.short_description = "Cost Breakdown"

    def token_breakdown(self, obj):
        """Display token usage breakdown"""
        html = """
        <table style="width: 100%;">
            <tr><td><strong>Input Tokens:</strong></td><td>{:,}</td></tr>
            <tr><td><strong>Output Tokens:</strong></td><td>{:,}</td></tr>
            <tr><td><strong>Total Tokens:</strong></td><td>{:,}</td></tr>
        </table>
        """.format(
            obj.total_input_tokens,
            obj.total_output_tokens,
            obj.total_input_tokens + obj.total_output_tokens,
        )
        return format_html(html)

    token_breakdown.short_description = "Token Usage"
