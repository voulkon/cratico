"""
AFM Entity Stats - Simple aggregated statistics per entity.

Stores plain totals derived from foreign-key relationships:
- Number of decisions the entity appears in
- Total amount across all decisions
- Number of distinct counterpart organizations
- Direct assignment breakdowns
- Etc.

These are intentionally simple raw numbers (no complex scoring/weighting).
"""

from django.db import models

from .entities import AFMEntity


class AFMEntityStats(models.Model):
    """
    One-to-one stats snapshot for an AFM entity.

    All values are plain totals computed via bulk aggregation queries,
    so they can be refreshed anytime without expensive per-entity lookups.
    """

    entity = models.OneToOneField(
        AFMEntity,
        on_delete=models.CASCADE,
        related_name="stats",
        primary_key=True,
        help_text="The AFM entity these stats belong to",
    )

    # ---- Core counts ----
    total_decisions = models.PositiveIntegerField(
        default=0,
        help_text="Number of distinct decisions this entity appears in",
    )
    distinct_roles = models.PositiveIntegerField(
        default=0,
        help_text="Number of distinct roles this entity has (e.g. sponsor, grantee)",
    )

    # ---- Financials ----
    total_amount = models.DecimalField(
        max_digits=18, decimal_places=2, default=0.00,
        help_text="Sum of all linked amounts (EUR)",
    )
    average_amount_per_decision = models.DecimalField(
        max_digits=15, decimal_places=2, default=0.00,
        help_text="Average amount per decision with amounts",
    )
    max_single_amount = models.DecimalField(
        max_digits=15, decimal_places=2, default=0.00,
        help_text="Largest single amount linked to this entity",
    )

    # ---- Counterparts ----
    distinct_organizations = models.PositiveIntegerField(
        default=0,
        help_text="Number of distinct organizations the entity has done business with",
    )
    distinct_counterpart_entities = models.PositiveIntegerField(
        default=0,
        help_text="Number of other distinct AFM entities (co-participants in same decisions)",
    )

    # ---- Direct assignments ----
    direct_assignment_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of decisions classified as direct assignments",
    )
    direct_assignment_percentage = models.FloatField(
        default=0.0,
        help_text="Percentage of total decisions that are direct assignments (0-100)",
    )
    direct_assignment_30k_38k = models.PositiveIntegerField(
        default=0,
        help_text="Number of direct-assignment decisions with total amount €30k-€38k"
        " (the maximum threshold for direct awards)",
    )
    payment_30k_38k = models.PositiveIntegerField(
        default=0,
        help_text="Number of decisions where the entity received €30k-€38k"
        " (money-receiving roles only)",
    )

    # ---- Metadata ----
    computed_at = models.DateTimeField(
        auto_now=True,
        help_text="When these stats were last computed",
    )

    class Meta:
        verbose_name = "AFM Entity Stats"
        verbose_name_plural = "AFM Entity Stats"
        ordering = ["-total_amount"]

    def __str__(self):
        return (
            f"Stats for {self.entity.afm}: "
            f"{self.total_decisions} decisions, €{self.total_amount:,.2f}"
        )
