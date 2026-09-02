"""
Admin interface for Feature Flags.

Provides a user-friendly interface for managing feature flags with:
- Real-time flag toggling
- Category-based organization
- Environment variable comparison
- Audit logging
- Cache management
"""

from api.utils.url_prefixes import (
    get_all_url_module_prefixes,
    get_default_exempt_prefixes,
)
from core.models.feature_flags import FeatureFlag, FeatureFlagAuditLog
from core.models.types import ActType
from core.services.feature_flag_service import feature_flags
from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

User = get_user_model()


class FeatureFlagForm(forms.ModelForm):
    """Custom form for FeatureFlag with dynamic widgets based on value_type."""

    # Dynamic field for ActType multi-select (only shown for FILTER_DECISION_TYPES)
    selected_decision_types = forms.ModelMultipleChoiceField(
        queryset=ActType.objects.all().order_by("uid"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Select decision types to import. Leave empty to import all types.",
        label="Decision Types",
    )

    # Dynamic field for additional exempt prefixes (only shown for STEALTH_EXEMPT_PREFIXES)
    selected_exempt_prefixes = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text=(
            "Select additional prefixes to exempt from stealth mode authentication. "
            "Grayed-out items below are ALWAYS exempt and cannot be changed."
        ),
        label="Optional Exempt Prefixes",
    )

    # Read-only display of always-exempt prefixes
    always_exempt_prefixes_display = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 6,
                "readonly": "readonly",
                "style": "background-color: #f5f5f5; cursor: not-allowed; font-family: monospace;",
            }
        ),
        help_text="These endpoints are ALWAYS exempt from stealth mode (cannot be changed to prevent lockout).",
        label="Always Exempt (Read-Only)",
    )

    # Dynamic fields for STEALTH_ALLOWLIST
    selected_users = forms.ModelMultipleChoiceField(
        queryset=User.objects.filter(is_active=True).order_by("email"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Select existing users to allow access when Stealth Mode is enabled.",
        label="Select Users",
    )

    additional_emails = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 6,
                "placeholder": "Enter one email address per line:\nuser1@example.com\nuser2@example.com",
                "style": "font-family: monospace;",
            }
        ),
        help_text="Enter additional email addresses (one per line) to allow access. These don't need to be existing users.",
        label="Additional Email Addresses",
    )

    # Dynamic field for ENTITY_SEARCH_METHOD
    selected_search_method = forms.ChoiceField(
        required=False,
        choices=[
            ("postgres_simple", "PostgreSQL Simple (Basic ILIKE search)"),
            ("postgres_fts", "PostgreSQL Full-Text Search (Smart language detection)"),
            ("opensearch", "OpenSearch (Advanced search - not yet implemented)"),
        ],
        widget=forms.Select(attrs={"style": "width: 100%; max-width: 600px;"}),
        help_text=(
            "Select the search method for entities (organizations, signers, units, companies, company persons). "
            "Note: postgres_fts requires backfill of search_vector fields."
        ),
        label="Search Method",
    )

    # Dynamic field for SEARCH_HISTORY_RECORDING_MODE
    selected_recording_mode = forms.ChoiceField(
        required=False,
        choices=[
            ("none", "None - Don't record any search history"),
            (
                "selections_only",
                "Selections Only - Only record when user clicks/selects a result",
            ),
            (
                "filtered",
                "Filtered - Smart filtering (skip short queries & rapid duplicates) [RECOMMENDED]",
            ),
            ("all", "All - Record everything including partial typing"),
        ],
        widget=forms.Select(attrs={"style": "width: 100%; max-width: 700px;"}),
        help_text=(
            "Controls how search queries are recorded in user search history. "
            "Filtered mode (default) provides optimal balance between UX and storage."
        ),
        label="Recording Mode",
    )

    # Read-only display of prerequisite status for ENTITY_SEARCH_METHOD
    prerequisite_status_display = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 12,
                "readonly": "readonly",
                "style": "background-color: #f5f5f5; cursor: not-allowed; font-family: monospace; font-size: 12px;",
            }
        ),
        help_text="Current status of PostgreSQL FTS prerequisites. Updated when page loads.",
        label="PostgreSQL FTS Prerequisites",
    )

    class Meta:
        model = FeatureFlag
        fields = "__all__"
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 2}),
            "list_value": forms.Textarea(
                attrs={"rows": 4, "placeholder": '["Δ.1", "Β.2.2"]'}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Customize checkbox labels to show "UID - Label" format
        self.fields["selected_decision_types"].label_from_instance = (
            lambda obj: f"{obj.uid} - {obj.label}"
        )

        # Customize checkbox labels for users to show email
        self.fields["selected_users"].label_from_instance = lambda obj: obj.email

        # Dynamically populate exempt prefix choices
        all_prefixes = get_all_url_module_prefixes()
        default_exempt = get_default_exempt_prefixes()

        # Build choices: only show prefixes that are NOT always exempt
        # Format: [(module_name, "module_name - /api/prefix/")]
        optional_prefixes = [
            (name, f"{name} - /api/{prefix}")
            for name, prefix in all_prefixes
            if prefix not in default_exempt  # Exclude always-exempt prefixes
        ]
        self.fields["selected_exempt_prefixes"].choices = optional_prefixes

        # Populate always-exempt prefixes display
        always_exempt_display_lines = []
        for prefix in default_exempt:
            if prefix == "health":
                always_exempt_display_lines.append(
                    "/api/health - Monitoring & health checks"
                )
            elif prefix == "v1/health":
                always_exempt_display_lines.append(
                    "/api/v1/health - Versioned health check"
                )
            elif prefix == "admin":
                always_exempt_display_lines.append("/api/admin - Admin interface")
            elif prefix == "docs":
                always_exempt_display_lines.append("/api/docs - API documentation")
            elif prefix.rstrip("/") == "auth":
                always_exempt_display_lines.append(
                    "/api/auth/ - Authentication (CRITICAL - prevents lockout!)"
                )
            else:
                always_exempt_display_lines.append(f"/api/{prefix}")

        self.fields["always_exempt_prefixes_display"].initial = "\n".join(
            always_exempt_display_lines
        )

        # If this is FILTER_DECISION_TYPES flag and we have list_value, pre-select types
        if (
            self.instance
            and self.instance.pk
            and self.instance.key == "FILTER_DECISION_TYPES"
        ):
            if self.instance.list_value:
                # Pre-select the types based on list_value
                selected_uids = (
                    self.instance.list_value
                    if isinstance(self.instance.list_value, list)
                    else []
                )
                self.fields["selected_decision_types"].initial = ActType.objects.filter(
                    uid__in=selected_uids
                )

        # If this is STEALTH_EXEMPT_PREFIXES flag, pre-select additional exempt prefixes
        if (
            self.instance
            and self.instance.pk
            and self.instance.key == "STEALTH_EXEMPT_PREFIXES"
        ):
            if self.instance.list_value:
                # Pre-select the module names from list_value
                selected_modules = (
                    self.instance.list_value
                    if isinstance(self.instance.list_value, list)
                    else []
                )
                self.fields["selected_exempt_prefixes"].initial = selected_modules

        # If this is STEALTH_ALLOWLIST flag and we have list_value, populate both fields
        if (
            self.instance
            and self.instance.pk
            and self.instance.key == "STEALTH_ALLOWLIST"
        ):
            if self.instance.list_value:
                emails = (
                    self.instance.list_value
                    if isinstance(self.instance.list_value, list)
                    else []
                )
                # Separate into existing users and additional emails
                existing_users = User.objects.filter(email__in=emails, is_active=True)
                existing_emails = set(existing_users.values_list("email", flat=True))
                additional = [email for email in emails if email not in existing_emails]

                # Pre-select existing users
                self.fields["selected_users"].initial = existing_users
                # Populate additional emails
                if additional:
                    self.fields["additional_emails"].initial = "\n".join(additional)

        # If this is ENTITY_SEARCH_METHOD flag and we have string_value, pre-select the method
        if (
            self.instance
            and self.instance.pk
            and self.instance.key == "ENTITY_SEARCH_METHOD"
        ):
            if self.instance.string_value:
                self.fields["selected_search_method"].initial = (
                    self.instance.string_value
                )

            # Populate prerequisite status display (force fresh check, no cache)
            from core.services.prerequisite_check_service import prerequisite_check

            # Clear cache first to get fresh status
            prerequisite_check.clear_cache()
            prereq_status = prerequisite_check.check_postgres_fts_prerequisites()

            status_lines = []
            status_lines.append("=" * 60)
            status_lines.append("PostgreSQL Full-Text Search Prerequisites")
            status_lines.append("=" * 60)
            status_lines.append("")

            # Overall status
            if prereq_status["available"]:
                status_lines.append("[OK] STATUS: READY")
            else:
                status_lines.append("[FAIL] STATUS: NOT READY")
            status_lines.append("")

            # Migration status
            status_lines.append(
                f"Migration: {'[OK] Applied' if prereq_status.get('migration_applied') else '[FAIL] Not Applied'}"
            )
            status_lines.append("")

            # Backfill status
            if prereq_status.get("details"):
                status_lines.append("Backfill Status:")
                for model_key, details in prereq_status["details"].items():
                    if "error" in details:
                        status_lines.append(
                            f"  {model_key}: ERROR - {details['error']}"
                        )
                    else:
                        if details.get("is_empty"):
                            status = "[OK]"
                            detail_text = "empty table (nothing to backfill)"
                        elif details.get("backfilled"):
                            status = "[OK]"
                            detail_text = "backfilled"
                        else:
                            status = "[FAIL]"
                            detail_text = "NULL search_vector rows found - partial backfill"
                        status_lines.append(f"  {status} {model_key}: {detail_text}")
            status_lines.append("")

            # Summary message
            status_lines.append("Summary:")
            status_lines.append(f"  {prereq_status['reason']}")
            status_lines.append("")

            if not prereq_status["available"]:
                status_lines.append("Action Required:")
                if not prereq_status.get("migration_applied"):
                    status_lines.append("  1. Run: python manage.py migrate")
                if prereq_status.get("missing_models"):
                    status_lines.append(
                        "  2. Run: python manage.py backfill_search_vectors --others-only"
                    )

            self.fields["prerequisite_status_display"].initial = "\n".join(status_lines)

        # If this is SEARCH_HISTORY_RECORDING_MODE flag and we have string_value, pre-select the mode
        if (
            self.instance
            and self.instance.pk
            and self.instance.key == "SEARCH_HISTORY_RECORDING_MODE"
        ):
            if self.instance.string_value:
                self.fields["selected_recording_mode"].initial = (
                    self.instance.string_value
                )

        # Show/hide fields based on value_type
        if self.instance and self.instance.pk:
            if self.instance.value_type == "boolean":
                self.fields["list_value"].widget = forms.HiddenInput()
                self.fields["string_value"].widget = forms.HiddenInput()
                self.fields["selected_decision_types"].widget = forms.HiddenInput()
                self.fields["selected_exempt_prefixes"].widget = forms.HiddenInput()
                self.fields["always_exempt_prefixes_display"].widget = (
                    forms.HiddenInput()
                )
                self.fields["selected_users"].widget = forms.HiddenInput()
                self.fields["additional_emails"].widget = forms.HiddenInput()
                self.fields["selected_search_method"].widget = forms.HiddenInput()
                self.fields["prerequisite_status_display"].widget = forms.HiddenInput()
                self.fields["selected_recording_mode"].widget = forms.HiddenInput()
            elif self.instance.value_type == "list":
                self.fields["enabled"].widget = forms.HiddenInput()
                self.fields["default_value"].widget = forms.HiddenInput()
                # For FILTER_DECISION_TYPES, show the nice checkbox UI
                if self.instance.key == "FILTER_DECISION_TYPES":
                    # Hide the raw JSON field, show the checkbox UI instead
                    self.fields["list_value"].widget = forms.HiddenInput()
                    self.fields["selected_exempt_prefixes"].widget = forms.HiddenInput()
                    self.fields["always_exempt_prefixes_display"].widget = (
                        forms.HiddenInput()
                    )
                    self.fields["selected_users"].widget = forms.HiddenInput()
                    self.fields["additional_emails"].widget = forms.HiddenInput()
                # For STEALTH_EXEMPT_PREFIXES, show the prefix checkboxes
                elif self.instance.key == "STEALTH_EXEMPT_PREFIXES":
                    self.fields["list_value"].widget = forms.HiddenInput()
                    self.fields["selected_decision_types"].widget = forms.HiddenInput()
                    self.fields["selected_users"].widget = forms.HiddenInput()
                    self.fields["additional_emails"].widget = forms.HiddenInput()
                    # Show both optional and always-exempt prefixes
                # For STEALTH_ALLOWLIST, show user selection fields
                elif self.instance.key == "STEALTH_ALLOWLIST":
                    self.fields["list_value"].widget = forms.HiddenInput()
                    self.fields["selected_decision_types"].widget = forms.HiddenInput()
                    self.fields["selected_exempt_prefixes"].widget = forms.HiddenInput()
                    self.fields["always_exempt_prefixes_display"].widget = (
                        forms.HiddenInput()
                    )
                else:
                    # For other list-type flags, use the raw JSON field
                    self.fields["selected_decision_types"].widget = forms.HiddenInput()
                    self.fields["selected_exempt_prefixes"].widget = forms.HiddenInput()
                    self.fields["always_exempt_prefixes_display"].widget = (
                        forms.HiddenInput()
                    )
                    self.fields["selected_users"].widget = forms.HiddenInput()
                    self.fields["additional_emails"].widget = forms.HiddenInput()
                self.fields["selected_search_method"].widget = forms.HiddenInput()
                self.fields["prerequisite_status_display"].widget = forms.HiddenInput()
                self.fields["selected_recording_mode"].widget = forms.HiddenInput()
            elif self.instance.value_type == "string":
                self.fields["enabled"].widget = forms.HiddenInput()
                self.fields["list_value"].widget = forms.HiddenInput()
                self.fields["selected_decision_types"].widget = forms.HiddenInput()
                self.fields["selected_exempt_prefixes"].widget = forms.HiddenInput()
                self.fields["always_exempt_prefixes_display"].widget = (
                    forms.HiddenInput()
                )
                self.fields["selected_users"].widget = forms.HiddenInput()
                self.fields["additional_emails"].widget = forms.HiddenInput()
                # For ENTITY_SEARCH_METHOD (choice type), show the dropdown selector
                if self.instance.key == "ENTITY_SEARCH_METHOD":
                    # Hide the raw string field, show the dropdown instead
                    self.fields["string_value"].widget = forms.HiddenInput()
                    # Show prerequisite status
                    self.fields["selected_recording_mode"].widget = forms.HiddenInput()
                else:
                    # For other string-type flags, hide the dropdown
                    self.fields["selected_search_method"].widget = forms.HiddenInput()
                    self.fields["prerequisite_status_display"].widget = (
                        forms.HiddenInput()
                    )
                    self.fields["selected_recording_mode"].widget = forms.HiddenInput()
            elif self.instance.value_type == "choice":
                self.fields["enabled"].widget = forms.HiddenInput()
                self.fields["list_value"].widget = forms.HiddenInput()
                self.fields["selected_decision_types"].widget = forms.HiddenInput()
                self.fields["selected_exempt_prefixes"].widget = forms.HiddenInput()
                self.fields["always_exempt_prefixes_display"].widget = (
                    forms.HiddenInput()
                )
                self.fields["selected_users"].widget = forms.HiddenInput()
                self.fields["additional_emails"].widget = forms.HiddenInput()
                # For ENTITY_SEARCH_METHOD (choice type), show the dropdown selector
                if self.instance.key == "ENTITY_SEARCH_METHOD":
                    # Hide the raw string field, show the dropdown instead
                    self.fields["string_value"].widget = forms.HiddenInput()
                    # Show prerequisite status
                    self.fields["selected_recording_mode"].widget = forms.HiddenInput()
                elif self.instance.key == "SEARCH_HISTORY_RECORDING_MODE":
                    # Hide the raw string field, show the recording mode dropdown
                    self.fields["string_value"].widget = forms.HiddenInput()
                    self.fields["selected_search_method"].widget = forms.HiddenInput()
                    self.fields["prerequisite_status_display"].widget = (
                        forms.HiddenInput()
                    )
                else:
                    # For other choice-type flags, hide all custom dropdowns
                    self.fields["selected_search_method"].widget = forms.HiddenInput()
                    self.fields["prerequisite_status_display"].widget = (
                        forms.HiddenInput()
                    )
                    self.fields["selected_recording_mode"].widget = forms.HiddenInput()

    def clean(self):
        cleaned_data = super().clean()
        value_type = cleaned_data.get("value_type", "boolean")

        # For FILTER_DECISION_TYPES, sync selected_decision_types to list_value
        if cleaned_data.get("key") == "FILTER_DECISION_TYPES" and value_type == "list":
            selected_types = cleaned_data.get("selected_decision_types", [])
            cleaned_data["list_value"] = [act_type.uid for act_type in selected_types]

        # For STEALTH_EXEMPT_PREFIXES, sync selected_exempt_prefixes to list_value
        if (
            cleaned_data.get("key") == "STEALTH_EXEMPT_PREFIXES"
            and value_type == "list"
        ):
            # Store the selected module names (e.g., ['system', 'tasks'])
            # The middleware will convert these to actual prefixes at runtime
            selected_modules = cleaned_data.get("selected_exempt_prefixes", [])
            cleaned_data["list_value"] = list(selected_modules)

        # For STEALTH_ALLOWLIST, merge selected users and additional emails
        if cleaned_data.get("key") == "STEALTH_ALLOWLIST" and value_type == "list":
            emails = []

            # Add emails from selected users
            selected_users = cleaned_data.get("selected_users", [])
            emails.extend([user.email for user in selected_users])

            # Add additional emails from textarea
            additional_text = cleaned_data.get("additional_emails", "")
            additional = [
                line.strip() for line in additional_text.split("\n") if line.strip()
            ]
            emails.extend(additional)

            # Remove duplicates while preserving order
            seen = set()
            unique_emails = []
            for email in emails:
                if email.lower() not in seen:
                    seen.add(email.lower())
                    unique_emails.append(email)

            cleaned_data["list_value"] = unique_emails

        # For ENTITY_SEARCH_METHOD, sync selected_search_method to string_value
        if cleaned_data.get("key") == "ENTITY_SEARCH_METHOD" and cleaned_data.get(
            "value_type"
        ) in ("string", "choice"):
            selected_method = cleaned_data.get("selected_search_method")
            if selected_method:
                cleaned_data["string_value"] = selected_method

                # Validate prerequisites for postgres_fts (force fresh check on save)
                if selected_method == "postgres_fts":
                    from core.services.prerequisite_check_service import (
                        prerequisite_check,
                    )

                    # Clear cache to get real-time status when saving
                    prerequisite_check.clear_cache()
                    prereq_status = (
                        prerequisite_check.check_postgres_fts_prerequisites()
                    )

                    if not prereq_status["available"]:
                        raise forms.ValidationError(
                            f"Cannot set search method to 'postgres_fts': {prereq_status['reason']}"
                        )

        # For SEARCH_HISTORY_RECORDING_MODE, sync selected_recording_mode to string_value
        if cleaned_data.get(
            "key"
        ) == "SEARCH_HISTORY_RECORDING_MODE" and cleaned_data.get("value_type") in (
            "string",
            "choice",
        ):
            selected_mode = cleaned_data.get("selected_recording_mode")
            if selected_mode:
                cleaned_data["string_value"] = selected_mode

        return cleaned_data


class FeatureFlagAuditLogInline(admin.TabularInline):
    """Inline admin for viewing audit logs."""

    model = FeatureFlagAuditLog
    extra = 0
    can_delete = False
    readonly_fields = [
        "changed_by",
        "change_type",
        "old_value",
        "new_value",
        "changed_at",
        "notes",
    ]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(FeatureFlag)
class FeatureFlagAdmin(admin.ModelAdmin):
    """Admin interface for Feature Flags."""

    form = FeatureFlagForm

    list_display = [
        "status_icon",
        "key",
        "name",
        "enabled_badge",
        "toggle_action",
        "requires_restart_badge",
        "source_info",
        "last_changed_by",
        "last_checked_display",
    ]

    list_filter = [
        "category",
        "value_type",
        "enabled",
        "is_active",
        "requires_restart",
    ]

    search_fields = [
        "key",
        "name",
        "description",
        "notes",
    ]

    readonly_fields = [
        "created_at",
        "updated_at",
        "last_checked_at",
        "current_value_display",
        "environment_value_display",
        "last_change_info",
    ]

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("key", "name", "category", "value_type", "is_active")},
        ),
        (
            "Value Configuration",
            {
                "fields": (
                    "enabled",
                    "list_value",
                    "string_value",
                    "selected_decision_types",
                    "selected_exempt_prefixes",
                    "always_exempt_prefixes_display",
                    "selected_users",
                    "additional_emails",
                    "selected_search_method",
                    "prerequisite_status_display",
                    "selected_recording_mode",
                ),
                "description": "Configure the value based on the value type selected above.",
            },
        ),
        ("Description", {"fields": ("description", "notes")}),
        (
            "Advanced Configuration",
            {
                "fields": ("default_value", "env_var_name", "requires_restart"),
                "classes": ("collapse",),
            },
        ),
        (
            "Current Status",
            {
                "fields": (
                    "current_value_display",
                    "environment_value_display",
                    "last_change_info",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at", "last_checked_at"),
                "classes": ("collapse",),
            },
        ),
    )

    inlines = [FeatureFlagAuditLogInline]

    actions = [
        "enable_flags",
        "disable_flags",
        "clear_cache_for_selected",
    ]

    def save_model(self, request, obj, form, change):
        """Override to create audit log when flag is changed via admin form."""
        if change:
            # Track what changed
            if "enabled" in form.changed_data:
                old_value = FeatureFlag.objects.get(pk=obj.pk).enabled
                new_value = obj.enabled

                # Save the object first
                super().save_model(request, obj, form, change)

                # Create audit log
                FeatureFlagAuditLog.objects.create(
                    feature_flag=obj,
                    changed_by=(
                        request.user.username
                        if request.user.is_authenticated
                        else "unknown"
                    ),
                    change_type="enabled" if new_value else "disabled",
                    old_value=old_value,
                    new_value=new_value,
                    notes=f'Changed via admin form. Other changes: {", ".join(form.changed_data)}',
                )

                messages.info(request, f"Audit log created for {obj.key} status change")
            else:
                # No status change, just save
                super().save_model(request, obj, form, change)

                # Log metadata update if significant fields changed
                if any(
                    field in form.changed_data
                    for field in ["name", "description", "category", "is_active"]
                ):
                    FeatureFlagAuditLog.objects.create(
                        feature_flag=obj,
                        changed_by=(
                            request.user.username
                            if request.user.is_authenticated
                            else "unknown"
                        ),
                        change_type="updated",
                        old_value=None,
                        new_value=None,
                        notes=f'Metadata updated: {", ".join(form.changed_data)}',
                    )
        else:
            # New flag being created
            super().save_model(request, obj, form, change)

            FeatureFlagAuditLog.objects.create(
                feature_flag=obj,
                changed_by=(
                    request.user.username
                    if request.user.is_authenticated
                    else "unknown"
                ),
                change_type="created",
                old_value=None,
                new_value=obj.enabled,
                notes="Created via admin form",
            )

    def get_queryset(self, request):
        """Optimize queryset by prefetching audit logs."""
        queryset = super().get_queryset(request)
        return queryset.prefetch_related("audit_logs")

    def changelist_view(self, request, extra_context=None):
        """Override to add initialization prompt and group flags by category."""
        extra_context = extra_context or {}

        # Check if flags need initialization
        flag_count = FeatureFlag.objects.count()
        known_flags_count = len(feature_flags.KNOWN_FLAGS)

        extra_context["show_initialize_prompt"] = flag_count == 0
        extra_context["flag_count"] = flag_count
        extra_context["known_flags_count"] = known_flags_count
        extra_context["needs_sync"] = flag_count < known_flags_count

        # Group flags by category for collapsible sections
        if flag_count > 0:
            from collections import OrderedDict

            flags_by_category = OrderedDict()
            all_flags = FeatureFlag.objects.filter(is_active=True).order_by(
                "category", "key"
            )

            for flag in all_flags:
                category = flag.get_category_display()
                if category not in flags_by_category:
                    flags_by_category[category] = []
                flags_by_category[category].append(flag)

            extra_context["flags_by_category"] = flags_by_category

        return super().changelist_view(request, extra_context)

    def get_urls(self):
        """Add custom admin URLs."""
        urls = super().get_urls()
        custom_urls = [
            path(
                "dashboard/",
                self.admin_site.admin_view(self.flag_dashboard),
                name="featureflag_dashboard",
            ),
            path(
                "<int:flag_id>/toggle/",
                self.admin_site.admin_view(self.toggle_flag),
                name="featureflag_toggle",
            ),
            path(
                "clear-cache/",
                self.admin_site.admin_view(self.clear_all_cache),
                name="featureflag_clear_cache",
            ),
            path(
                "initialize/",
                self.admin_site.admin_view(self.initialize_flags),
                name="featureflag_initialize",
            ),
        ]
        return custom_urls + urls

    def status_icon(self, obj):
        """Display status icon."""
        if not obj.is_active:
            return format_html('<span style="color: gray;">⊗</span>')

        # Handle different value types
        if obj.value_type == "boolean":
            return format_html(
                '<span style="color: {};">●</span>', "green" if obj.enabled else "red"
            )
        elif obj.value_type == "list":
            count = len(obj.list_value) if obj.list_value else 0
            return format_html(
                '<span style="color: {};">[COPY]</span>',
                "green" if count > 0 else "gray",
            )
        else:
            return format_html('<span style="color: blue;">[NOTE]</span>')

    status_icon.short_description = ""

    def enabled_badge(self, obj):
        """Display enabled status as badge."""
        if obj.value_type == "boolean":
            if obj.enabled:
                return format_html(
                    '<span style="background-color: #28a745; color: white; padding: 3px 10px; '
                    'border-radius: 3px; font-weight: bold;">ON</span>'
                )
            return format_html(
                '<span style="background-color: #dc3545; color: white; padding: 3px 10px; '
                'border-radius: 3px; font-weight: bold;">OFF</span>'
            )
        elif obj.value_type == "list":
            count = len(obj.list_value) if obj.list_value else 0
            if count > 0:
                return format_html(
                    '<span style="background-color: #007bff; color: white; padding: 3px 10px; '
                    'border-radius: 3px; font-weight: bold;">{} items</span>',
                    count,
                )
            return format_html(
                '<span style="background-color: #6c757d; color: white; padding: 3px 10px; '
                'border-radius: 3px;">Empty</span>'
            )
        else:  # string
            has_value = bool(obj.string_value)
            return format_html(
                '<span style="background-color: #17a2b8; color: white; padding: 3px 10px; '
                'border-radius: 3px;">{}</span>',
                "Set" if has_value else "Empty",
            )

    enabled_badge.short_description = "Status"

    def requires_restart_badge(self, obj):
        """Display requires restart badge."""
        if obj.requires_restart:
            return format_html(
                '<span style="background-color: #ffc107; color: black; padding: 2px 8px; '
                'border-radius: 3px; font-size: 11px;">[WARN] Restart Required</span>'
            )
        return "-"

    requires_restart_badge.short_description = "Restart"

    def source_info(self, obj):
        """Display where the flag value is coming from."""
        info = feature_flags.get_flag_info(obj.key)
        if info:
            source = info.get("source", "default")
            colors = {
                "database": "#007bff",
                "environment": "#6c757d",
                "default": "#17a2b8",
            }
            return format_html(
                '<span style="color: {}; font-size: 11px;">● {}</span>',
                colors.get(source, "#6c757d"),
                source.upper(),
            )
        return "-"

    source_info.short_description = "Source"

    def last_changed_by(self, obj):
        """Display who last changed this flag."""
        latest_log = obj.audit_logs.filter(
            change_type__in=["enabled", "disabled"]
        ).first()

        if latest_log:
            from django.utils.timesince import timesince

            time_ago = timesince(latest_log.changed_at)
            return format_html(
                '<span title="{} - {}">{}<br><small style="color: #666;">{} ago</small></span>',
                latest_log.changed_at.strftime("%Y-%m-%d %H:%M:%S"),
                latest_log.change_type,
                latest_log.changed_by,
                time_ago,
            )
        return format_html('<span style="color: #999;">—</span>')

    last_changed_by.short_description = "Last Changed By"

    def last_checked_display(self, obj):
        """Display last checked time in a readable format."""
        if obj.last_checked_at:
            from django.utils.timesince import timesince

            return f"{timesince(obj.last_checked_at)} ago"
        return "Never"

    last_checked_display.short_description = "Last Checked"

    def toggle_action(self, obj):
        """Display toggle button (only for boolean flags)."""
        if obj.value_type != "boolean":
            return format_html('<span style="color: #999;">N/A</span>')

        url = reverse("admin:featureflag_toggle", args=[obj.id])
        action = "Disable" if obj.enabled else "Enable"
        color = "#dc3545" if obj.enabled else "#28a745"
        return format_html(
            '<a href="{}" style="background-color: {}; color: white; padding: 5px 10px; '
            'border-radius: 3px; text-decoration: none; font-size: 12px;">{}</a>',
            url,
            color,
            action,
        )

    toggle_action.short_description = "Quick Action"

    def current_value_display(self, obj):
        """Display the current effective value of the flag."""
        current_value = feature_flags.get_value(obj.key)

        if obj.value_type == "boolean":
            is_enabled = bool(current_value)
            return format_html(
                '<strong style="color: {};">{}</strong>',
                "green" if is_enabled else "red",
                "Enabled" if is_enabled else "Disabled",
            )
        elif obj.value_type == "list":
            if isinstance(current_value, list) and current_value:
                # For decision types, show them in a nice format
                if obj.key == "FILTER_DECISION_TYPES":
                    items_html = ", ".join(
                        [f"<code>{item}</code>" for item in current_value[:10]]
                    )
                    if len(current_value) > 10:
                        items_html += f" <em>...and {len(current_value) - 10} more</em>"
                    return format_html(
                        '<div style="max-width: 400px;"><strong>{} types:</strong><br>{}</div>',
                        len(current_value),
                        items_html,
                    )
                else:
                    return format_html(
                        "<code>{}</code>",
                        str(current_value[:5])
                        + ("..." if len(current_value) > 5 else ""),
                    )
            return format_html('<em style="color: #999;">Empty list</em>')
        else:  # string
            if current_value:
                return format_html("<code>{}</code>", str(current_value)[:100])
            return format_html('<em style="color: #999;">Empty</em>')

    current_value_display.short_description = "Current Effective Value"

    def environment_value_display(self, obj):
        """Display the environment variable value if set."""
        import os

        env_value = os.getenv(obj.env_var_name or obj.key)
        if env_value:
            return format_html(
                "<code>{}</code> = <strong>{}</strong>",
                obj.env_var_name or obj.key,
                env_value,
            )
        return "Not set"

    environment_value_display.short_description = "Environment Variable"

    def last_change_info(self, obj):
        """Display detailed information about the last change."""
        latest_log = obj.audit_logs.order_by("-changed_at").first()

        if latest_log:
            return format_html(
                '<div style="padding: 10px; background: #f8f9fa; border-left: 3px solid #007bff; border-radius: 3px;">'
                "<strong>Changed by:</strong> {}<br>"
                "<strong>Action:</strong> {}<br>"
                "<strong>When:</strong> {}<br>"
                "<strong>Old value:</strong> {}<br>"
                "<strong>New value:</strong> {}<br>"
                "{}"
                "</div>",
                latest_log.changed_by,
                latest_log.get_change_type_display(),
                latest_log.changed_at.strftime("%Y-%m-%d %H:%M:%S"),
                (
                    "[RUNNING] ON"
                    if latest_log.old_value
                    else "[PENDING] OFF" if latest_log.old_value is not None else "N/A"
                ),
                (
                    "[RUNNING] ON"
                    if latest_log.new_value
                    else "[PENDING] OFF" if latest_log.new_value is not None else "N/A"
                ),
                (
                    f"<strong>Notes:</strong> {latest_log.notes}"
                    if latest_log.notes
                    else ""
                ),
            )
        return format_html('<span style="color: #999;">No changes recorded yet</span>')

    last_change_info.short_description = "Last Change Details"

    def toggle_flag(self, request, flag_id):
        """Toggle a feature flag."""
        flag = FeatureFlag.objects.get(pk=flag_id)
        old_value = flag.enabled
        flag.enabled = not flag.enabled
        flag.save()

        # Create audit log
        FeatureFlagAuditLog.objects.create(
            feature_flag=flag,
            changed_by=(
                request.user.username if request.user.is_authenticated else "system"
            ),
            change_type="enabled" if flag.enabled else "disabled",
            old_value=old_value,
            new_value=flag.enabled,
            notes=f"Toggled via admin interface",
        )

        messages.success(
            request,
            f'Feature flag "{flag.name}" has been {"enabled" if flag.enabled else "disabled"}.',
        )

        if flag.requires_restart:
            messages.warning(
                request,
                f"[WARN]️ This flag requires a service restart to take full effect!",
            )

        return redirect("admin:core_featureflag_changelist")

    def enable_flags(self, request, queryset):
        """Enable selected flags."""
        count = 0
        for flag in queryset:
            if not flag.enabled:
                flag.enabled = True
                flag.save()
                FeatureFlagAuditLog.objects.create(
                    feature_flag=flag,
                    changed_by=request.user.username,
                    change_type="enabled",
                    old_value=False,
                    new_value=True,
                    notes="Bulk enabled via admin",
                )
                count += 1

        self.message_user(request, f"{count} flag(s) enabled successfully.")

    enable_flags.short_description = "Enable selected flags"

    def disable_flags(self, request, queryset):
        """Disable selected flags."""
        count = 0
        for flag in queryset:
            if flag.enabled:
                flag.enabled = False
                flag.save()
                FeatureFlagAuditLog.objects.create(
                    feature_flag=flag,
                    changed_by=request.user.username,
                    change_type="disabled",
                    old_value=True,
                    new_value=False,
                    notes="Bulk disabled via admin",
                )
                count += 1

        self.message_user(request, f"{count} flag(s) disabled successfully.")

    disable_flags.short_description = "Disable selected flags"

    def clear_cache_for_selected(self, request, queryset):
        """Clear cache for selected flags."""
        for flag in queryset:
            feature_flags.clear_cache(flag.key)

        self.message_user(request, f"Cache cleared for {queryset.count()} flag(s).")

    clear_cache_for_selected.short_description = "Clear cache for selected flags"

    def clear_all_cache(self, request):
        """Clear all feature flag caches."""
        feature_flags.clear_cache()
        messages.success(request, "All feature flag caches have been cleared.")
        return redirect("admin:core_featureflag_changelist")

    def initialize_flags(self, request):
        """Initialize all known flags in the database."""
        count = feature_flags.initialize_flags_in_db()
        messages.success(
            request, f"Initialized {count} feature flag(s) from configuration."
        )
        return redirect("admin:core_featureflag_changelist")

    def flag_dashboard(self, request):
        """Display feature flag dashboard."""
        flags_by_category = {}
        all_flags = FeatureFlag.objects.filter(is_active=True).select_related()

        for flag in all_flags:
            if flag.category not in flags_by_category:
                flags_by_category[flag.category] = []

            info = feature_flags.get_flag_info(flag.key)
            flags_by_category[flag.category].append(
                {
                    "flag": flag,
                    "info": info,
                }
            )

        context = {
            "title": "Feature Flags Dashboard",
            "flags_by_category": flags_by_category,
            "total_flags": all_flags.count(),
            "enabled_flags": all_flags.filter(enabled=True).count(),
        }

        return render(request, "admin/feature_flags/dashboard.html", context)


@admin.register(FeatureFlagAuditLog)
class FeatureFlagAuditLogAdmin(admin.ModelAdmin):
    """Admin interface for Feature Flag Audit Logs."""

    list_display = [
        "feature_flag",
        "change_type",
        "old_value",
        "new_value",
        "changed_by",
        "changed_at",
    ]

    list_filter = [
        "change_type",
        "changed_at",
        "feature_flag__category",
    ]

    search_fields = [
        "feature_flag__key",
        "feature_flag__name",
        "changed_by",
        "notes",
    ]

    readonly_fields = [
        "feature_flag",
        "changed_by",
        "change_type",
        "old_value",
        "new_value",
        "changed_at",
        "notes",
    ]

    def has_add_permission(self, request):
        """Prevent manual creation of audit logs."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of audit logs."""
        return False
