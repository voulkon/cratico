import decimal
from enum import Enum
from zoneinfo import ZoneInfo

from core.models.organizations import Organization, Signer, Unit
from django.conf import settings
from django.contrib.postgres.search import SearchVectorField
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


class DecisionStatus(str, Enum):
    """Κατάσταση πράξης (decision state)."""

    PUBLISHED = "PUBLISHED"
    REVOKED = "REVOKED"  # Ανακληθείσα
    PENDING_REVOCATION = "PENDING_REVOCATION"  # Εν αναμονή ανάκλησης
    ALL = "ALL"

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """
        Return tuples in the form expected by Django's `choices=`.
        """
        return [(member.value, member.name.title().replace("_", " ")) for member in cls]


class Decision(models.Model):
    """
    Django ORM representation of a Diavgeia Decision.
    Field names mirror the Pydantic `Decision` model (camelCase → snake_case).
    """

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------
    ada = models.CharField(
        _("ΑΔΑ"),
        max_length=15,
        unique=True,
        db_index=True,
        help_text=_("The unique identifier (ΑΔΑ) of the decision."),
    )

    version_id = models.CharField(max_length=36)
    corrected_version_id = models.CharField(max_length=36, null=True, blank=True)

    # ------------------------------------------------------------------
    # Core metadata
    # ------------------------------------------------------------------
    protocol_number = models.CharField(max_length=255, null=True, blank=True)
    subject = models.TextField()
    issue_date = models.DateTimeField()

    # ------------------------------------------------------------------
    # Batch tracking
    # ------------------------------------------------------------------
    import_job = models.ForeignKey(
        "core.ImportJob",
        on_delete=models.SET_NULL,
        related_name="decisions",
        null=True,
        blank=True,
        db_index=True,
        help_text=_("The import batch (ImportJob) that created/updated this decision"),
    )

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,  # Prevent deleting Org if Decisions exist
        related_name="decisions",
        verbose_name=_("Organization"),
        db_index=True,  # Often queried by organization
        null=True,  # Allow NULL for cases where the organization doesn't exist
        blank=True,  # Allow blank in forms
    )

    # TODO: Replace any reference of them, especially in tests
    # signer_ids = models.JSONField(default=list, blank=True)  # List[str]
    # unit_ids = models.JSONField(default=list, blank=True)  # List[str]

    # ManyToMany for Signers (Links to Signer model via its PK: uid)
    signers = models.ManyToManyField(
        Signer,
        related_name="signed_decisions",
        verbose_name=_("Signers"),
        blank=True,  # A decision might have no signers? Check Diavgeia spec
    )
    # ManyToMany for Units (Links to Unit model via its PK: uid)
    units = models.ManyToManyField(
        Unit,
        related_name="decisions",
        verbose_name=_("Organizational Units"),
        blank=True,
    )

    # Replace CharField with ForeignKey
    decision_type = models.ForeignKey(
        "core.ActType",  # Reference to your ActType model
        on_delete=models.PROTECT,  # Prevent deleting a type if decisions reference it
        related_name="decisions",
        verbose_name=_("Decision Type"),
        db_index=True,
        null=True,  # Allow NULL temporarily
    )

    thematic_category_ids = models.JSONField(
        _("Thematic Category IDs"),
        default=list,
        blank=True,
        help_text=_(
            "List of thematic category IDs (e.g., ['12.1', '12.2']). Consider FK/M2M if querying by category is needed."
        ),
        # If querying by category is frequent, consider a ManyToManyField
        # to a ThematicCategory model.
    )
    # TODO: I need to add fetch_all_types in the seed_all and make it a foreign key

    has_private_data = models.BooleanField(  # Renamed from privateData
        _("Contains Private Data"), default=False
    )
    status = models.CharField(
        _("Status"), max_length=25, choices=DecisionStatus.choices(), db_index=True
    )

    # ------------------------------------------------------------------
    # Document / URL information
    # ------------------------------------------------------------------
    document_url = models.URLField(
        _("Document URL"), max_length=2048, null=True, blank=True
    )
    document_checksum = models.CharField(
        _("Document Checksum"),
        max_length=64,  # SHA256? Check length
        null=True,
        blank=True,
    )
    # URL for the decision page on Diavgeia?
    url = models.URLField(_("Diavgeia URL"), max_length=2048, null=True, blank=True)
    warnings = models.TextField(  # From Pydantic 'warnings' field
        _("Warnings"), null=True, blank=True
    )

    # ------------------------------------------------------------------
    # Timestamps
    # ------------------------------------------------------------------
    submission_timestamp = models.DateTimeField(_("Submission Timestamp"))
    publish_timestamp = models.DateTimeField(
        _("Publish Timestamp"), null=True, blank=True, db_index=True
    )
    # ------------------------------------------------------------------
    # Extra fields (Promoted & Raw JSON)
    # ------------------------------------------------------------------
    # --- Promoted fields for querying/aggregation ---
    financial_year = models.IntegerField(
        _("Financial Year"),
        null=True,
        blank=True,
        db_index=True,
        help_text=_("Extracted from extraFieldValues.financialYear"),
    )
    # Using DecimalField for monetary values is crucial
    amount = models.DecimalField(
        _("Amount"),
        max_digits=15,  # Adjust precision as needed
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_(
            "The primary financial amount (e.g., from amountWithVAT or awardAmount)"
        ),
    )
    currency = models.CharField(
        _("Currency"),
        max_length=3,  # e.g., 'EUR'
        null=True,
        blank=True,
        help_text=_("Currency code for the primary amount"),
    )
    # --- Raw JSON backup ---
    extra_field_values_json = models.JSONField(  # Renamed to avoid clash
        _("Raw Extra Field Values"),
        default=dict,
        null=True,
        blank=True,
        help_text=_("Stores the original extraFieldValues JSON data."),
    )

    # ------------------------------------------------------------------
    # Audit fields
    # ------------------------------------------------------------------
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    # ------------------------------------------------------------------
    # Discovery tracking
    # ------------------------------------------------------------------
    discovery_sources = models.JSONField(
        _("Discovery Sources"),
        default=list,
        null=True,  # Allow NULL for backwards compatibility
        blank=True,
        help_text=_(
            "Tracks how this decision was discovered. List of source objects with "
            "source_type (default/org-specific/unit-specific/etc) and search_params."
        ),
    )
    first_discovery_source = models.CharField(
        _("First Discovery Source"),
        max_length=50,
        null=True,
        blank=True,
        db_index=True,
        help_text=_("The type of the first source that discovered this decision"),
    )

    # ------------------------------------------------------------------
    # Computed date fields for efficient querying
    # ------------------------------------------------------------------
    issue_date_day = models.DateField(
        _("Issue Date (Day Only)"),
        null=True,
        blank=True,
        db_index=True,
        help_text=_("Date part only for efficient grouping"),
    )
    issue_date_month = models.DateField(
        _("Issue Date (Month Only)"),
        null=True,
        blank=True,
        db_index=True,
        help_text=_("First day of month for grouping"),
    )
    issue_date_year = models.IntegerField(
        _("Issue Year"),
        null=True,
        blank=True,
        db_index=True,
    )

    # submission_timestamp is the upload/publish date used by the Diavgeia API's
    # from_date / to_date search parameters.  We store its date portion so that
    # BackfillCoverageService can count decisions by the same date type the
    # fetch pipeline uses, keeping both in sync.
    publish_date_day = models.DateField(
        _("Publish Date (Day Only)"),
        null=True,
        blank=True,
        db_index=True,
        help_text=_(
            "Date portion of publish_timestamp in Athens timezone. "
            "Matches the from_date / to_date Diavgeia API parameters."
        ),
    )

    # PostgreSQL Full-Text Search
    search_vector = SearchVectorField(null=True, blank=True)

    def save(self, *args, **kwargs):
        # Auto-populate the computed fields
        # Diavgeia encodes issue dates as midnight Athens time, so we must
        # convert to Europe/Athens before extracting the date — otherwise UTC
        # midnight (22:00 UTC previous day) would land on the wrong calendar day.
        if self.issue_date:
            athens_dt = self.issue_date.astimezone(ZoneInfo(settings.TIME_ZONE))
            self.issue_date_day = athens_dt.date()
            self.issue_date_month = athens_dt.date().replace(day=1)
            self.issue_date_year = athens_dt.year
        # publish_date_day mirrors the Diavgeia API's from_date / to_date.
        # publish_timestamp is a real clock time (not Athens midnight), but we
        # still convert to Athens timezone so that 23:30 UTC (= 01:30 Athens next
        # day) lands on the correct calendar day.
        if self.publish_timestamp:
            pub_athens = self.publish_timestamp.astimezone(ZoneInfo(settings.TIME_ZONE))
            self.publish_date_day = pub_athens.date()
        super().save(*args, **kwargs)

    # ------------------------------------------------------------------
    # Meta and String Representation
    # ------------------------------------------------------------------
    class Meta:
        verbose_name = _("Decision")
        verbose_name_plural = _("Decisions")
        indexes = [
            # Regular indexes for exact lookups
            models.Index(fields=["ada"]),
            models.Index(fields=["status"]),
            models.Index(fields=["organization"]),
            # Date range indexes (these help with filtering by date ranges)
            models.Index(fields=["issue_date"]),
            models.Index(fields=["publish_timestamp"]),
            # Composite indexes for common query patterns
            models.Index(fields=["organization", "issue_date"]),
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["issue_date", "status"]),
            # Financial queries
            models.Index(fields=["amount", "issue_date"]),
            models.Index(fields=["financial_year", "organization"]),
            # Efficient date grouping indexes
            models.Index(fields=["organization", "issue_date_day"]),
            models.Index(fields=["organization", "issue_date_month"]),
            models.Index(fields=["organization", "issue_date_year"]),
            models.Index(fields=["issue_date_month", "amount"]),
            # Publish-date grouping (mirrors Diavgeia API from_date / to_date)
            models.Index(fields=["publish_date_day"]),
            models.Index(fields=["organization", "publish_date_day"]),
            # For M2M relationships (these help with JOIN operations)
            # Note: These are automatically created for M2M fields, but listing for completeness
        ]

    def __str__(self) -> str:
        return f"Decision {self.ada}"

    def get_decision_type_label(self) -> str:
        """Returns the human-readable type label."""
        return self.decision_type.label if self.decision_type else "Unknown Type"


# Separate model for Attachments
class Attachment(models.Model):
    """Represents an attachment associated with a Decision."""

    decision = models.ForeignKey(
        Decision,
        on_delete=models.CASCADE,  # If decision is deleted, delete attachments
        related_name="attachments",
        verbose_name=_("Decision"),
    )
    # Using 'attachment_id' to avoid clash with Django's implicit 'id' PK
    attachment_id = models.CharField(
        _("Attachment ID (from source)"),
        max_length=255,  # Check length
        help_text=_("The ID of the attachment as provided by Diavgeia."),
    )
    description = models.TextField(_("Description"), null=True, blank=True)
    filename = models.CharField(_("Filename"), max_length=255)
    mime_type = models.CharField(_("MIME Type"), max_length=100)
    checksum = models.CharField(_("Checksum"), max_length=64)  # Check length

    # You might add a FileField if you intend to download and store the files
    # file = models.FileField(upload_to='attachments/%Y/%m/%d/', null=True, blank=True)

    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Attachment")
        verbose_name_plural = _("Attachments")
        # Ensure an attachment isn't added multiple times for the same decision
        unique_together = [["decision", "attachment_id"]]
        indexes = [
            models.Index(fields=["filename"]),
            models.Index(fields=["mime_type"]),
        ]

    def __str__(self) -> str:
        return f"Attachment {self.filename} for Decision {self.decision.ada}"


class DecisionAmountKAE(models.Model):
    """Represents a specific KAE amount associated with a Decision."""

    decision = models.ForeignKey(
        Decision,
        on_delete=models.CASCADE,  # If Decision deleted, KAE amounts go too
        related_name="kae_amounts",  # How to access from Decision instance
        verbose_name=_("Decision"),
    )
    kae = models.CharField(
        _("KAE Code"),
        max_length=40,
        db_index=True,  # Likely filter/group by KAE
    )
    amount = models.DecimalField(
        _("Amount (with VAT)"),
        max_digits=15,  # Adjust as needed
        decimal_places=2,
        validators=[MinValueValidator(decimal.Decimal("0.00"))],  # Usually non-negative
    )
    # Optional: Add currency here ONLY if it can differ per KAE line
    # within the SAME decision, which seems unlikely based on Pydantic.
    # If currency is always the same as the main Decision amount,
    # you don't need it here.

    class Meta:
        verbose_name = _("Decision KAE Amount")
        verbose_name_plural = _("Decision KAE Amounts")
        unique_together = [["decision", "kae"]]
        indexes = [
            # Basic indexes
            models.Index(fields=["kae"]),
            # NEW: Critical for aggregation queries
            models.Index(fields=["decision", "amount"]),  # For Sum operations
            models.Index(fields=["amount"]),  # For general amount queries
        ]

    def __str__(self) -> str:
        return f"KAE {self.kae}: {self.amount} for Decision {self.decision.ada}"
