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
        ]

    def __str__(self):
        return f"{self.decision.ada} - {self.source_field_name} ({self.amount})"
