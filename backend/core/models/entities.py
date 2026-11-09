from core.models.decisions import Decision
from django.contrib.postgres.search import SearchVectorField
from django.core.validators import RegexValidator
from django.db import models


class EntityType(models.TextChoices):
    PERSON = "person", "Person"
    COMPANY = "company", "Company"
    ORGANIZATION = "organization", "Organization"
    UNKNOWN = "unknown", "Unknown"


class EntityRole(models.TextChoices):
    SPONSOR = "sponsorAFMName", "Sponsor"
    ORGANIZATION = "org", "Organization"
    PERSON = "person", "Person"
    GRANTOR = "grantor", "Grantor"
    GRANTEE = "grantee", "Grantee"
    DONATION_GIVER = "donationGiver", "Donation Giver"
    DONATION_RECEIVER = "donationReceiver", "Donation Receiver"
    CONTRACTOR = "contractor", "Contractor"
    OTHER = "other", "Other"


class MetadataSource(models.TextChoices):
    """Where the relationship's counterpart AFM came from."""

    DIAVGEIA = "DIAVGEIA", "Diavgeia metadata"
    OCR_AFM = "OCR_AFM", "Recovered from OCR text"
    AI_TEXT = "AI_TEXT", "Recovered by AI from text"
    MANUAL = "MANUAL", "Manual"


class AFMEntity(models.Model):
    """Stores unique AFM entities found in decisions."""

    afm = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        validators=[RegexValidator(r"^\d{9}$", "AFM must be exactly 9 digits")],
        help_text="Tax identification number (AFM)",
    )
    entity_type = models.CharField(
        max_length=20,
        choices=EntityType.choices,
        default=EntityType.UNKNOWN,
        help_text="Type of entity",
    )
    name = models.TextField(blank=True, null=True, help_text="Entity name if available")

    # Metadata
    first_seen = models.DateTimeField(
        auto_now_add=True, help_text="First time this AFM was seen"
    )
    last_seen = models.DateTimeField(
        auto_now=True, help_text="Last time this AFM was seen"
    )
    total_appearances = models.PositiveIntegerField(
        default=0, help_text="Total number of times this AFM has appeared"
    )

    # GEMI data status
    gemi_lookup_attempted = models.DateTimeField(
        null=True, blank=True, help_text="Timestamp of the last GEMI lookup attempt"
    )
    gemi_lookup_success = models.BooleanField(
        default=False, help_text="Whether the last GEMI lookup was successful"
    )
    gemi_companies_count = models.PositiveIntegerField(
        default=0, help_text="Number of companies found with this AFM"
    )

    # Add error tracking
    last_error = models.TextField(
        null=True, blank=True, help_text="Last error encountered during GEMI lookup"
    )
    error_count = models.PositiveIntegerField(
        default=0, help_text="Number of failed lookup attempts"
    )

    # PostgreSQL Full-Text Search
    search_vector = SearchVectorField(null=True, blank=True)

    class Meta:
        verbose_name = "AFM Entity"
        verbose_name_plural = "AFM Entities"
        indexes = [
            models.Index(fields=["afm"]),
            models.Index(fields=["entity_type"]),
            models.Index(fields=["gemi_lookup_attempted", "gemi_lookup_success"]),
        ]

    def __str__(self):
        return f"AFM: {self.afm} ({self.entity_type})"


class DecisionEntityRelationship(models.Model):
    """Links decisions to entities with their roles."""

    decision = models.ForeignKey(
        Decision, on_delete=models.CASCADE, related_name="entity_relationships"
    )
    entity = models.ForeignKey(
        AFMEntity, on_delete=models.CASCADE, related_name="decision_relationships"
    )
    role = models.CharField(max_length=30, choices=EntityRole.choices)

    # Context data from the decision
    parent_key_path = models.CharField(
        max_length=200
    )  # e.g., "sponsorAFMName", "person[0]"
    source_field_name = models.CharField(max_length=100, blank=True, null=True)
    raw_context = models.JSONField(blank=True, null=True)  # The full data structure

    # Metadata
    extracted_at = models.DateTimeField(auto_now_add=True)
    confidence_score = models.FloatField(
        default=1.0
    )  # How confident are we in this extraction

    # ------------------------------------------------------------------
    # Counterpart-recovery provenance
    # ------------------------------------------------------------------
    # The row always represents the CURRENT counterpart.  When the recovery
    # pipeline replaces a self-referential Diavgeia AFM with the AFM read from
    # the document, these fields record that the value was inferred and where
    # the evidence came from.  The replaced state lives in
    # ``CounterpartRecoveryAttempt`` — deliberately no ``is_active`` flag or
    # multi-row history here, so every existing relationship query keeps
    # working unchanged.
    is_inferred = models.BooleanField(
        default=False,
        help_text="True when this relationship was recovered from document text.",
    )
    metadata_source = models.CharField(
        max_length=20,
        choices=MetadataSource.choices,
        default=MetadataSource.DIAVGEIA,
        help_text="Origin of the counterpart AFM.",
    )
    source_extraction = models.ForeignKey(
        "core.DocumentExtraction",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recovered_relationships",
        help_text="Extraction whose text produced the recovered counterpart.",
    )
    source_span = models.ForeignKey(
        "core.TextSpan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recovered_relationships",
        help_text="Text span that supplied the recovered counterpart AFM.",
    )

    class Meta:
        unique_together = ["decision", "entity", "role", "parent_key_path"]
        indexes = [
            models.Index(fields=["decision", "role"]),
            models.Index(fields=["entity", "role"]),
            # Additional index for decision lookups
            models.Index(fields=["decision"]),
            models.Index(fields=["entity"]),
        ]

    def __str__(self):
        return f"{self.decision.ada} -> {self.entity.afm} ({self.role})"


class DecisionAmountField(models.Model):
    """Stores all extracted amounts from a decision, regardless of entity association."""

    decision = models.ForeignKey(
        Decision, on_delete=models.CASCADE, related_name="amount_fields"
    )
    parent_key_path = models.CharField(
        max_length=200,
        help_text="JSON path where amount was found, e.g., 'sponsor[0].expenseAmount'",
    )
    source_field_name = models.CharField(
        max_length=100, help_text="Field name, e.g., 'expenseAmount'"
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=10, default="EUR")
    structure_type = models.CharField(
        max_length=20,
        choices=[
            ("nested_object", "Nested Object"),
            ("plain_numeric", "Plain Numeric"),
            ("other", "Other"),
        ],
        blank=True,
        null=True,
    )
    raw_context = models.JSONField(
        blank=True, null=True, help_text="Full JSON snippet for context"
    )
    extracted_at = models.DateTimeField(auto_now_add=True)

    associated_relationship = models.ForeignKey(
        DecisionEntityRelationship,
        on_delete=models.SET_NULL,  # If relationship deleted, keep amount but unlink
        related_name="linked_amounts",
        null=True,
        blank=True,
        help_text="Associated entity relationship if this amount is tied to an entity",
    )

    # ------------------------------------------------------------------
    # Amount verification — corrected value from document text
    # ------------------------------------------------------------------
    # When the cents-based detector finds a ×100/÷100 decimal-shift typo
    # in this specific amount field, the corrected value is stored here.
    # Sum(Coalesce('verified_amount', 'amount')) then produces the true
    # total — no Decision-model bloat needed.
    verified_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Corrected amount as detected from the document text. "
            "When set, this overrides 'amount' for all aggregations."
        ),
    )
    amount_verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this field's amount was last verified/corrected.",
    )

    # ------------------------------------------------------------------
    # Amount validity guard — the recorded value cannot be used as money
    # ------------------------------------------------------------------
    # Some rows hold a value that actually belongs to a DIFFERENT, non-monetary
    # numeric field of the same Diavgeia response — a counterpart VAT number
    # (ΑΦΜ) or a budget classification code (ΚΑΕ) — e.g. sponsor AFM
    # 099370337 recorded as amount 9.9370337E7 (€99,370,337).
    #
    # A second reason is ``amount_not_in_text``: the recorded value is not
    # present in the document at all (and is not a ×100/÷100 clone of a text
    # amount).  It may be monetary, but it is unconfirmed.
    #
    # Unlike ``verified_amount`` (where we KNOW the correct value), here we
    # know only that this amount must not be trusted as recorded.  So we never
    # write a monetary value; we only mark the row invalid so it is excluded
    # from every monetary aggregation (see ``core.services.decision_facets``)
    # and surfaced for review/feedback.
    invalid_amount_reason = models.CharField(
        max_length=32,
        null=True,
        blank=True,
        help_text=(
            "Set when the amount is known to be a non-monetary value "
            "(e.g. 'afm_as_amount', 'kae_as_amount'). "
            "Excludes the field from all monetary aggregations."
        ),
    )
    invalid_amount_value = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text=(
            "The non-monetary value the amount matched, for audit/display "
            "(e.g. the AFM '099370337' or the KAE digits '706273001')."
        ),
    )
    invalid_amount_flagged_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this field was flagged as a non-monetary value.",
    )

    class Meta:
        unique_together = ["decision", "parent_key_path", "source_field_name"]
        indexes = [
            # KEEP: Decision-level aggregations
            models.Index(fields=["decision", "amount"]),
            # NEW: Entity-linked aggregations (most critical for new system)
            models.Index(fields=["associated_relationship", "amount"]),
            # NEW: JOIN optimization
            models.Index(fields=["decision", "associated_relationship"]),
            # NEW: Amount range queries
            models.Index(fields=["amount"]),
            # PostgreSQL partial index for linked amounts only (highly recommended)
            models.Index(
                fields=["associated_relationship", "amount"],
                condition=models.Q(associated_relationship__isnull=False),
                name="idx_linked_amounts_only",
            ),
            # Partial index for corrected (verified) amounts: powers the admin
            # "corrected amounts" counts (and the admin list filter) as an
            # index-only scan instead of scanning the whole table on millions
            # of rows.
            models.Index(
                fields=["decision", "verified_amount"],
                condition=models.Q(verified_amount__isnull=False),
                name="idx_daf_verified_amounts",
            ),
            # Partial index for amounts flagged as non-monetary values
            # (AFM/KAE): powers the feedback pool and admin filters as an
            # index-only scan.  Mirrors idx_daf_verified_amounts.
            models.Index(
                fields=["decision", "invalid_amount_reason"],
                condition=models.Q(invalid_amount_reason__isnull=False),
                name="idx_daf_invalid_amounts",
            ),
        ]

    def __str__(self):
        return f"{self.decision.ada} - {self.source_field_name} ({self.amount})"
