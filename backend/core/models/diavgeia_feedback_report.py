"""
Model for tracking per-decision Diavgeia feedback reports.

The ``Decision`` model is a faithful mirror of what Diavgeia sent (the
original).  The amount-correction pipeline detects wrong metadata amounts
(``DecisionAmountField.verified_amount``) and reports them back to the
Diavgeia admins via the public feedback endpoint
(``POST /luminapi/api/feedback/new``).  That reporting state is *derived*
from our correction work, so it lives here — one row per decision — rather
than bloating the high-write ``Decision`` table (which gets a large daily
import volume).

A ``DiavgeiaFeedbackReport`` row is created only when a decision is actually
reported (or attempted), so the daily import path pays zero write overhead.
"""

from django.db import models
from django.utils import timezone


class DiavgeiaFeedbackReport(models.Model):
    """
    Tracks a single report sent to the Diavgeia feedback API for a decision.

    At most one row per decision (``decision`` is unique).  If a decision is
    re-reported (e.g. after a correction update), the existing row is updated
    rather than a new one being created — keeping the table compact.
    """

    decision = models.OneToOneField(
        "core.Decision",
        on_delete=models.CASCADE,
        related_name="diavgeia_feedback_report",
        help_text="The decision that was reported to Diavgeia.",
    )
    reported = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether the feedback report was accepted by the API.",
    )
    reported_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the decision was reported to Diavgeia.",
    )
    reference = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text=(
            "Reference number returned by the Diavgeia feedback API "
            "(e.g. 6a78b06a4ab4cce30ab3fd6b)."
        ),
    )
    response = models.TextField(
        null=True,
        blank=True,
        help_text="Raw JSON response from the Diavgeia feedback API, for debugging.",
    )
    reporter_email = models.EmailField(
        blank=True,
        default="",
        help_text="The reporterEmail that was sent to the Diavgeia feedback API.",
    )
    feedback_errors = models.JSONField(
        default=list,
        blank=True,
        help_text="The feedBackErrors codes that were sent (e.g. ['FE_1']).",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Diavgeia Feedback Report"
        verbose_name_plural = "Diavgeia Feedback Reports"
        indexes = [
            models.Index(fields=["reported", "-reported_at"]),
        ]

    def __str__(self):
        status = "reported" if self.reported else "pending"
        return f"{self.decision.ada}: {status}"

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def mark_reported(
        self,
        *,
        reference: str | None,
        response: str,
        reporter_email: str = "",
        feedback_errors: list | None = None,
    ) -> None:
        """Record a successful report."""
        self.reported = True
        self.reported_at = timezone.now()
        self.reference = reference or None
        self.response = response
        self.reporter_email = reporter_email
        self.feedback_errors = feedback_errors or []
        self.save(
            update_fields=[
                "reported", "reported_at", "reference", "response",
                "reporter_email", "feedback_errors", "updated_at",
            ]
        )

    def mark_failed(self, *, response: str = "", reporter_email: str = "") -> None:
        """Record a failed report attempt."""
        self.reported = False
        self.reported_at = None
        self.reference = None
        self.response = response
        self.reporter_email = reporter_email
        self.save(
            update_fields=[
                "reported", "reported_at", "reference", "response",
                "reporter_email", "updated_at",
            ]
        )
