from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _


class AIModelPricing(models.Model):
    """Stores pricing information for AI models and embedding providers"""

    # Provider and model identification
    provider = models.CharField(
        max_length=50,
        db_index=True,
        help_text=_("Provider name (e.g., OPENAI, ANTHROPIC, AWS_BEDROCK)"),
    )
    model_name = models.CharField(
        max_length=200,
        db_index=True,
        help_text=_(
            "Actual model identifier used in API calls (e.g., 'anthropic.claude-3-haiku-20240307-v1:0', 'gpt-4-turbo-2024-04-09')"
        ),
    )
    display_name = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text=_(
            "Human-friendly name (e.g., 'Claude Haiku 3', 'GPT-4 Turbo'). If empty, model_name is used."
        ),
    )

    # Pricing configuration
    pricing_unit = models.CharField(
        max_length=20,
        choices=[
            ("PER_MILLION", "Per Million Tokens"),
            ("PER_THOUSAND", "Per Thousand Tokens"),
        ],
        default="PER_MILLION",
        help_text=_(
            "Unit for pricing (OpenAI/Anthropic use million, AWS Bedrock uses thousand)"
        ),
    )
    input_price = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        help_text=_("Price per unit for input tokens (in USD)"),
    )
    output_price = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        null=True,
        blank=True,
        help_text=_("Price per unit for output tokens (in USD). Null for embeddings."),
    )

    # Model characteristics
    model_type = models.CharField(
        max_length=20,
        choices=[
            ("CHAT", "Chat/Completion"),
            ("EMBEDDING", "Embedding"),
        ],
        default="CHAT",
        db_index=True,
    )
    context_window = models.IntegerField(
        null=True, blank=True, help_text=_("Maximum context window in tokens")
    )

    # Metadata
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text=_("Whether this pricing is currently active"),
    )
    effective_date = models.DateField(
        help_text=_("Date when this pricing became/becomes effective")
    )
    notes = models.TextField(
        null=True,
        blank=True,
        help_text=_("Additional notes about pricing, special rates, etc."),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("AI Model Pricing")
        verbose_name_plural = _("AI Model Pricing")
        ordering = ["-effective_date", "provider", "model_name"]
        indexes = [
            models.Index(fields=["provider", "model_name", "is_active"]),
            models.Index(fields=["model_type", "is_active"]),
            models.Index(fields=["effective_date"]),
        ]
        unique_together = [["provider", "model_name", "effective_date"]]

    def __str__(self):
        name = self.display_name or self.model_name
        return f"{self.provider} - {name} ({self.effective_date})"

    def get_input_price_per_token(self) -> Decimal:
        """Get normalized price per single token for input"""
        if self.pricing_unit == "PER_MILLION":
            return self.input_price / Decimal("1000000")
        else:  # PER_THOUSAND
            return self.input_price / Decimal("1000")

    def get_output_price_per_token(self) -> Decimal:
        """Get normalized price per single token for output"""
        if not self.output_price:
            return Decimal("0")
        if self.pricing_unit == "PER_MILLION":
            return self.output_price / Decimal("1000000")
        else:  # PER_THOUSAND
            return self.output_price / Decimal("1000")

    def calculate_cost(self, input_tokens: int, output_tokens: int = 0) -> Decimal:
        """Calculate total cost for given token counts"""
        input_cost = Decimal(str(input_tokens)) * self.get_input_price_per_token()
        output_cost = Decimal(str(output_tokens)) * self.get_output_price_per_token()
        return input_cost + output_cost

    @classmethod
    def get_active_pricing(cls, provider: str, model_name: str):
        """Get the most recent active pricing for a provider/model combination"""
        return (
            cls.objects.filter(provider=provider, model_name=model_name, is_active=True)
            .order_by("-effective_date")
            .first()
        )


class TaskOutputEstimate(models.Model):
    """
    DEPRECATED: This model is no longer used in the codebase.
    Output estimation is now handled directly in AIJobDefinition via output_ratio field.

    Kept for backward compatibility. Can be removed in future after data migration.
    """

    task_type = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text=_("Type of task (e.g., 'summary', 'entities', 'classification')"),
    )

    # Output estimation as ratio of input
    output_ratio = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        help_text=_(
            "Expected output tokens as ratio of input tokens (e.g., 0.15 for 15%)"
        ),
    )

    # Or fixed output size
    fixed_output_tokens = models.IntegerField(
        null=True,
        blank=True,
        help_text=_("Fixed output token count if not ratio-based"),
    )

    # Overhead percentage for system prompts, etc.
    prompt_overhead_ratio = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal("0.10"),
        help_text=_("Additional tokens added for system prompts (e.g., 0.10 for 10%)"),
    )

    description = models.TextField(
        null=True,
        blank=True,
        help_text=_("Description of what this task type includes"),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Task Output Estimate")
        verbose_name_plural = _("Task Output Estimates")
        ordering = ["task_type"]

    def __str__(self):
        return f"{self.task_type} (output: {self.output_ratio*100}%)"

    def estimate_output_tokens(self, input_tokens: int) -> int:
        """Calculate estimated output tokens based on input"""
        if self.fixed_output_tokens:
            return self.fixed_output_tokens
        return int(input_tokens * float(self.output_ratio))


class AIJobDefinition(models.Model):
    """
    Defines AI processing jobs with specific cost calculation parameters.

    Examples:
    - Daily Summary Job: Summarize all extractions from a day
    - Interest Ranking Job: Rank summaries by user interest
    - Entity Extraction Job: Extract entities from documents
    """

    # Job identification
    job_name = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text=_("Unique name for this job (e.g., 'daily_summary')"),
    )
    display_name = models.CharField(
        max_length=200,
        help_text=_("Human-readable name (e.g., 'Daily Document Summary')"),
    )
    description = models.TextField(
        help_text=_("Detailed description of what this job does")
    )

    # Default AI configuration
    default_provider = models.CharField(
        max_length=50, help_text=_("Default provider (e.g., 'AWS_BEDROCK', 'OPENAI')")
    )
    default_model = models.CharField(max_length=100, help_text=_("Default model name"))

    # Cost calculation parameters
    analysis_type = models.CharField(
        max_length=50,
        help_text=_("Type of analysis (e.g., 'summary', 'classification', 'ranking')"),
    )

    # Prompt configuration
    system_prompt = models.TextField(
        null=True, blank=True, help_text=_("System/instruction prompt template")
    )
    prompt_overhead_tokens = models.IntegerField(
        null=True,
        blank=True,
        help_text=_("Fixed token count for prompts (if not using percentage)"),
    )
    prompt_overhead_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
        help_text=_("Percentage overhead for prompts (e.g., 0.05 for 5%)"),
    )

    # Output estimation
    output_estimation_mode = models.CharField(
        max_length=20,
        choices=[
            ("RATIO", "Ratio of Input"),
            ("FIXED", "Fixed Token Count"),
            ("PER_ITEM", "Fixed per Item"),
        ],
        default="RATIO",
    )
    output_ratio = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
        help_text=_("Output as ratio of input (e.g., 0.20 for 20%)"),
    )
    fixed_output_tokens = models.IntegerField(
        null=True, blank=True, help_text=_("Fixed output token count")
    )

    # Batch processing configuration
    batch_size = models.IntegerField(
        default=1,
        help_text=_("How many items to process per API call (e.g., 3 for ranking)"),
    )
    items_per_batch_context = models.TextField(
        null=True,
        blank=True,
        help_text=_(
            "Description of how batching works (e.g., '3 summaries at a time')"
        ),
    )

    # Job execution settings
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text=_("Whether this job definition is active"),
    )
    max_concurrent_executions = models.IntegerField(
        default=1, help_text=_("Maximum concurrent executions allowed")
    )

    # Additional configuration (JSON for flexibility)
    extra_config = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Additional configuration parameters in JSON format"),
    )

    # Algorithm/Implementation reference
    algorithm_module = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        help_text=_(
            "Python module path for the job implementation (e.g., 'core.jobs.daily_summary')"
        ),
    )
    algorithm_class = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text=_("Class name that implements this job"),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("AI Job Definition")
        verbose_name_plural = _("AI Job Definitions")
        ordering = ["display_name"]

    def __str__(self):
        return f"{self.display_name} ({self.job_name})"

    def calculate_prompt_overhead(self, base_tokens: int) -> int:
        """Calculate the prompt overhead tokens"""
        if self.prompt_overhead_tokens:
            return self.prompt_overhead_tokens
        elif self.prompt_overhead_percentage:
            return int(base_tokens * float(self.prompt_overhead_percentage))
        return 0

    def estimate_output_tokens(self, input_tokens: int, item_count: int = 1) -> int:
        """Estimate output tokens based on mode"""
        if self.output_estimation_mode == "FIXED" and self.fixed_output_tokens:
            return self.fixed_output_tokens
        elif self.output_estimation_mode == "PER_ITEM" and self.fixed_output_tokens:
            return self.fixed_output_tokens * item_count
        elif self.output_estimation_mode == "RATIO" and self.output_ratio:
            return int(input_tokens * float(self.output_ratio))
        return 0


class AIJobExecution(models.Model):
    """
    Tracks actual execution of AI jobs with cost tracking.
    """

    job_definition = models.ForeignKey(
        AIJobDefinition, on_delete=models.CASCADE, related_name="executions"
    )

    # Execution metadata
    execution_id = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text=_("Unique identifier for this execution"),
    )
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=[
            ("PENDING", "Pending"),
            ("RUNNING", "Running"),
            ("COMPLETED", "Completed"),
            ("FAILED", "Failed"),
            ("CANCELLED", "Cancelled"),
        ],
        default="PENDING",
        db_index=True,
    )

    # Configuration used (snapshot at execution time)
    provider_used = models.CharField(max_length=50)
    model_used = models.CharField(max_length=100)

    # Scope of execution
    items_processed = models.IntegerField(
        default=0, help_text=_("Number of items processed (e.g., documents, summaries)")
    )
    items_scope = models.JSONField(
        null=True, blank=True, help_text=_("IDs or identifiers of items in scope")
    )

    # Cost tracking
    estimated_cost_usd = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        null=True,
        blank=True,
        help_text=_("Pre-execution cost estimate"),
    )
    actual_cost_usd = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        null=True,
        blank=True,
        help_text=_("Actual cost based on token usage"),
    )

    total_input_tokens = models.IntegerField(default=0)
    total_output_tokens = models.IntegerField(default=0)

    # Results and errors
    result_summary = models.JSONField(
        null=True, blank=True, help_text=_("Summary of results")
    )
    error_message = models.TextField(null=True, blank=True)

    # Performance metrics
    execution_time_seconds = models.IntegerField(
        null=True, blank=True, help_text=_("Total execution time in seconds")
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("AI Job Execution")
        verbose_name_plural = _("AI Job Executions")
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["job_definition", "status"]),
            models.Index(fields=["started_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"{self.job_definition.job_name} - {self.execution_id} ({self.status})"

    @property
    def cost_variance_percentage(self) -> Decimal:
        """Calculate percentage difference between estimated and actual cost"""
        if (
            self.estimated_cost_usd
            and self.actual_cost_usd
            and self.estimated_cost_usd > 0
        ):
            variance = (
                self.actual_cost_usd - self.estimated_cost_usd
            ) / self.estimated_cost_usd
            return variance * Decimal("100")
        return Decimal("0")

    @property
    def is_complete(self) -> bool:
        """Check if execution is in a terminal state"""
        return self.status in ["COMPLETED", "FAILED", "CANCELLED"]


class AIJobExecutionItem(models.Model):
    """
    Tracks individual items processed within a job execution.
    For example, each DocumentExtraction processed in a daily summary job.
    """

    execution = models.ForeignKey(
        AIJobExecution, on_delete=models.CASCADE, related_name="items"
    )

    # Item identification
    item_type = models.CharField(
        max_length=50,
        help_text=_("Type of item (e.g., 'DocumentExtraction', 'DocumentAnalysis')"),
    )
    item_id = models.IntegerField(help_text=_("ID of the item being processed"))
    item_identifier = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        help_text=_("Human-readable identifier (e.g., ADA number)"),
    )

    # Processing details
    sequence_number = models.IntegerField(
        help_text=_("Order in which this item was processed")
    )
    processed_at = models.DateTimeField(auto_now_add=True)

    # Token usage for this specific item
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    estimated_cost_usd = models.DecimalField(
        max_digits=10, decimal_places=6, null=True, blank=True
    )
    actual_cost_usd = models.DecimalField(
        max_digits=10, decimal_places=6, null=True, blank=True
    )

    # Result for this item
    result_data = models.JSONField(
        null=True,
        blank=True,
        help_text=_("Result data for this item (e.g., generated summary)"),
    )
    success = models.BooleanField(default=True)
    error_message = models.TextField(null=True, blank=True)

    # Link to created analysis if applicable
    created_analysis = models.ForeignKey(
        "DocumentAnalysis",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="job_execution_items",
        help_text=_("Link to DocumentAnalysis created by this job item"),
    )

    class Meta:
        verbose_name = _("AI Job Execution Item")
        verbose_name_plural = _("AI Job Execution Items")
        ordering = ["execution", "sequence_number"]
        indexes = [
            models.Index(fields=["execution", "sequence_number"]),
            models.Index(fields=["item_type", "item_id"]),
        ]

    def __str__(self):
        return f"{self.execution.execution_id} - Item {self.sequence_number} ({self.item_identifier})"

    def cost_variance(self):
        """Calculate variance between estimated and actual cost"""
        if self.estimated_cost_usd and self.actual_cost_usd:
            return float(self.actual_cost_usd - self.estimated_cost_usd)
        return None

    @property
    def cost_variance_percentage(self):
        """Calculate percentage variance"""
        if (
            self.estimated_cost_usd
            and self.actual_cost_usd
            and self.estimated_cost_usd > 0
        ):
            variance = float(self.actual_cost_usd - self.estimated_cost_usd)
            return (variance / float(self.estimated_cost_usd)) * 100
        return None
