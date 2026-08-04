from core.models.decisions import Decision
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.utils.translation import gettext_lazy as _


class ProcessingStatus(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    PROCESSING = "PROCESSING", _("Processing")
    COMPLETED = "COMPLETED", _("Completed")
    FAILED = "FAILED", _("Failed")
    NEEDS_VISION = "NEEDS_VISION", _("Needs Vision Processing")
    CORRUPTED_CONTENT = "CORRUPTED_CONTENT", _("Corrupted Content Detected")


class ProcessingProvider(models.TextChoices):
    # Text extraction providers
    PYMUPDF = "PYMUPDF", _("PyMuPDF")
    PLAINTEXT = "PLAINTEXT", _("Plain Text")
    DOCLING = "DOCLING", _("Docling")
    PYPDF = "PYPDF", _("PyPDF")
    PDFMINER = "PDFMINER", _("PDF Miner")
    TESSERACT = "TESSERACT", _("Tesseract OCR")
    GOOGLE_VISION = "GOOGLE_VISION", _("Google Vision API")
    AZURE_OCR = "AZURE_OCR", _("Azure OCR")
    # Analysis providers
    OPENAI = "OPENAI", _("OpenAI")
    ANTHROPIC = "ANTHROPIC", _("Anthropic Claude")
    GOOGLE_VERTEX = "GOOGLE_VERTEX", _("Google Vertex AI")
    AWS_BEDROCK = "AWS_BEDROCK", _("AWS Bedrock")
    MISTRAL = "MISTRAL", _("Mistral AI")
    OLLAMA = "OLLAMA", _("Ollama Local Models")
    OPENROUTER = "OPENROUTER", _("OpenRouter")

    # Embedding providers
    OPENAI_EMBED = "OPENAI_EMBED", _("OpenAI Embeddings")
    GOOGLE_EMBED = "GOOGLE_EMBED", _("Google Embeddings")
    SENTENCE_TRANSFORMERS = "SENTENCE_TRANSFORMERS", _("Sentence Transformers")


class DocumentExtraction(models.Model):
    """Stores the raw text extracted from a document"""

    decision = models.OneToOneField(
        Decision, on_delete=models.CASCADE, related_name="text_extraction"
    )

    # Extraction info
    extraction_status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
        db_index=True,
    )
    extraction_provider = models.CharField(
        max_length=30, choices=ProcessingProvider.choices, null=True, blank=True
    )
    extraction_date = models.DateTimeField(null=True, blank=True)

    # Document metadata
    raw_text = models.TextField(null=True, blank=True)
    page_count = models.IntegerField(null=True, blank=True)
    character_count = models.IntegerField(null=True, blank=True)
    is_scanned_document = models.BooleanField(null=True, blank=True)
    # language = models.CharField(max_length=10, null=True, blank=True)

    # Full-text search field
    search_vector = SearchVectorField(null=True, blank=True)

    # Error handling
    error_message = models.TextField(null=True, blank=True)
    retry_count = models.IntegerField(default=0)
    processing_time_ms = models.IntegerField(null=True, blank=True)

    task_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    preprocessing_metadata = models.JSONField(
        null=True,
        blank=True,
        help_text="Metadata from text preprocessing including corruption detection",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Document Extraction")
        verbose_name_plural = _("Document Extractions")
        indexes = [
            models.Index(fields=["extraction_status"]),
            models.Index(fields=["extraction_provider"]),
            models.Index(fields=["is_scanned_document"]),
            GinIndex(fields=["search_vector"]),  # Add GIN index for FTS
        ]

    @property
    def full_text(self):
        """Get the complete document text"""
        return self.raw_text or ""

    def __str__(self):
        return f"Extraction for {self.decision.ada}"


class DocumentAnalysis(models.Model):
    """Stores AI analysis results including summaries"""

    decision = models.ForeignKey(
        Decision, on_delete=models.CASCADE, related_name="analysis_results"
    )

    # Analysis metadata
    analysis_type = models.CharField(
        max_length=50
    )  # e.g., "summary", "entities", "classifications"
    provider = models.CharField(max_length=30, choices=ProcessingProvider.choices)
    model_name = models.CharField(
        max_length=100
    )  # e.g., "gpt-4", "claude-3-opus", etc.

    # Analysis content
    content = models.TextField()

    # For tracking analysis quality/versions
    version = models.CharField(max_length=20, default="1.0")
    confidence_score = models.FloatField(null=True, blank=True)

    # Cost tracking
    input_tokens = models.IntegerField(
        null=True, blank=True, help_text=_("Actual or estimated input tokens used")
    )
    output_tokens = models.IntegerField(
        null=True,
        blank=True,
        help_text=_("Actual or estimated output tokens generated"),
    )
    estimated_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        null=True,
        blank=True,
        help_text=_("Estimated total cost in USD"),
    )
    actual_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        null=True,
        blank=True,
        help_text=_("Actual cost if reported by API in USD"),
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Document Analysis")
        verbose_name_plural = _("Document Analyses")
        indexes = [
            models.Index(fields=["analysis_type"]),
            models.Index(fields=["provider"]),
        ]
        unique_together = [["decision", "analysis_type", "provider", "version"]]

    def __str__(self):
        return f"{self.analysis_type} for {self.decision.ada} by {self.provider}"


class DocumentEmbedding(models.Model):
    """Stores vector embeddings for document chunks"""

    decision = models.ForeignKey(
        Decision, on_delete=models.CASCADE, related_name="embeddings"
    )

    # Chunk information
    chunk_index = models.IntegerField()
    chunk_text = models.TextField()

    # Embedding information
    embedding_provider = models.CharField(
        max_length=30, choices=ProcessingProvider.choices
    )
    embedding_model = models.CharField(max_length=100)
    embedding_dimensions = models.IntegerField()

    # The actual vector - stored as PostgreSQL array or JSONB
    # For PostgreSQL with pgvector extension:
    # vector = models.Vector(dimensions=1536)  # Adjust dimensions as needed
    # For regular databases:
    vector_json = models.JSONField()

    # Cost tracking for embeddings
    input_tokens = models.IntegerField(
        null=True, blank=True, help_text=_("Tokens used for embedding generation")
    )
    estimated_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        null=True,
        blank=True,
        help_text=_("Estimated cost for this embedding in USD"),
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Document Embedding")
        verbose_name_plural = _("Document Embeddings")
        indexes = [
            models.Index(fields=["embedding_provider"]),
            models.Index(fields=["decision", "chunk_index"]),
        ]

    def __str__(self):
        return f"Embedding chunk {self.chunk_index} for {self.decision.ada}"


class DocumentPage(models.Model):
    """Stores page-level metadata (text moved to DocumentExtraction.raw_text)"""

    extraction = models.ForeignKey(
        DocumentExtraction, on_delete=models.CASCADE, related_name="pages"
    )

    page_number = models.IntegerField()
    character_count = models.IntegerField(null=True, blank=True)

    # Optional: page-specific metadata
    has_images = models.BooleanField(default=False)
    has_tables = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Document Page")
        verbose_name_plural = _("Document Pages")
        unique_together = [["extraction", "page_number"]]
        indexes = [
            models.Index(fields=["page_number"]),
        ]

    def __str__(self):
        return f"Page {self.page_number} of {self.extraction.decision.ada}"


class ExtractorComparison(models.Model):
    """Simple table to compare extraction results side by side"""

    decision = models.ForeignKey(
        Decision, on_delete=models.CASCADE, related_name="extractor_comparisons"
    )

    # The two texts to compare
    text_before = models.TextField(
        null=True, blank=True, help_text="PYMUPDF extraction"
    )
    text_after = models.TextField(null=True, blank=True, help_text="DOCLING extraction")

    # Metadata
    chars_before = models.IntegerField(null=True, blank=True)
    chars_after = models.IntegerField(null=True, blank=True)
    chars_diff = models.IntegerField(null=True, blank=True)

    # Store the PDF locally for inspection
    pdf_path = models.CharField(
        max_length=500, null=True, blank=True, help_text="Local path to downloaded PDF"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Extractor Comparison")
        verbose_name_plural = _("Extractor Comparisons")

    def __str__(self):
        return f"Comparison for {self.decision.ada}"


class AmountVerificationStatus(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    TEXT_EXTRACTING = "TEXT_EXTRACTING", _("Extracting Text")
    AI_ANALYZING = "AI_ANALYZING", _("AI Analyzing")
    COMPLETED = "COMPLETED", _("Completed")
    FAILED = "FAILED", _("Failed")
    SKIPPED = "SKIPPED", _("Skipped – No Text Available")


class AmountVerificationRun(models.Model):
    """
    A single amount-verification pass over one document extraction.

    One row per (extraction, method, provider, model, version), so the regex
    heuristic and AI results (and different LLMs) can be stored side-by-side
    and compared.  The raw amounts found in the text are stored as
    ``TextAmountCandidate`` children; the decision-level verdict lives in
    ``AmountVerificationResolution``.
    """

    extraction = models.ForeignKey(
        DocumentExtraction,
        on_delete=models.CASCADE,
        related_name="amount_verification_runs",
        help_text=_("The exact document text this run was verified against"),
    )

    # --- Method identity ---
    method = models.CharField(
        max_length=20,
        choices=[("regex", _("Regex / Heuristics")), ("ai", _("AI / LLM"))],
        default="regex",
        help_text=_("Detection method used for this run"),
    )
    provider = models.CharField(
        max_length=30,
        null=True,
        blank=True,
        help_text=_("Provider: 'REGEX' for regex runs, else the AI provider"),
    )
    model = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text=_("Model: 'greek-amount-v1' for regex runs, else the LLM name"),
    )
    version = models.CharField(max_length=20, default="1.0")

    # --- Status ---
    status = models.CharField(
        max_length=20,
        choices=AmountVerificationStatus.choices,
        default=AmountVerificationStatus.PENDING,
        db_index=True,
    )

    # --- Amounts (three-way comparison) ---
    raw_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("The decision.amount field from Diavgeia (may be inaccurate)"),
    )
    calculated_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_(
            "Accurate total from DecisionAmountField (FinancialCalculationService)"
        ),
    )
    ai_verified_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("The amount this run decided on from the document text"),
    )

    # --- Result ---
    has_discrepancy = models.BooleanField(
        default=False,
        help_text=_("True if this run's chosen amount contradicts the DB amounts"),
    )
    discrepancy_note = models.TextField(
        null=True,
        blank=True,
        help_text=_("Human-readable explanation of the discrepancy"),
    )
    ai_raw_response = models.TextField(
        null=True,
        blank=True,
        help_text=_("Full method response / audit trail for this run"),
    )
    error_message = models.TextField(null=True, blank=True)

    # --- Cost tracking ---
    input_tokens = models.IntegerField(null=True, blank=True)
    output_tokens = models.IntegerField(null=True, blank=True)
    cost_usd = models.DecimalField(
        max_digits=10, decimal_places=6, null=True, blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Amount Verification Run")
        verbose_name_plural = _("Amount Verification Runs")
        unique_together = [
            ["extraction", "method", "provider", "model", "version"]
        ]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["extraction", "status"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return f"{self.extraction.decision.ada} [{self.method}/{self.provider}]"


class TextAmountCandidate(models.Model):
    """
    A distinct monetary amount detected in the document text by a run.

    One row per unique (run, amount) value, with how many times it appeared
    (``occurrence_count``) and context about the first occurrence.  These are
    the raw observations — stored *before* any decision about which one is the
    correct amount.
    """

    run = models.ForeignKey(
        AmountVerificationRun,
        on_delete=models.CASCADE,
        related_name="text_candidates",
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    raw = models.CharField(
        max_length=50, help_text=_("Matched token, e.g. '10.000,00'")
    )
    position = models.IntegerField(
        help_text=_("Char offset of the first occurrence in the text")
    )
    near_keyword = models.BooleanField(
        default=False,
        help_text=_("True if the occurrence is near a financial keyword"),
    )
    occurrence_count = models.PositiveIntegerField(
        default=1, help_text=_("How many times this amount appears in the text")
    )

    class Meta:
        verbose_name = _("Text Amount Candidate")
        verbose_name_plural = _("Text Amount Candidates")
        unique_together = [["run", "amount"]]
        indexes = [
            models.Index(fields=["run", "amount"]),
        ]

    def __str__(self):
        return f"{self.raw} (x{self.occurrence_count})"


class AmountVerificationResolution(models.Model):
    """
    Decision-level verdict for amount verification.

    Points at the winning run and the amount that run chose.  This is the
    record queries/UI read to answer 'is this decision's amount trustworthy?'.
    """

    decision = models.OneToOneField(
        Decision,
        on_delete=models.CASCADE,
        related_name="amount_verification",
    )
    winning_run = models.ForeignKey(
        AmountVerificationRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolutions",
    )
    chosen_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("The final amount believed correct for this decision"),
    )
    chosen_candidate = models.ForeignKey(
        TextAmountCandidate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text=_("The text candidate that corresponds to the chosen amount"),
    )
    has_discrepancy = models.BooleanField(
        default=False,
        db_index=True,
        help_text=_("True if the winning run found a discrepancy"),
    )
    discrepancy_note = models.TextField(
        null=True, blank=True, help_text=_("Explanation copied from the winning run")
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Amount Verification Resolution")
        verbose_name_plural = _("Amount Verification Resolutions")
        indexes = [
            models.Index(fields=["-updated_at"]),
        ]

    def __str__(self):
        return f"Amount resolution for {self.decision.ada}"

    @property
    def discrepancy_ratio(self) -> float | None:
        """How far the chosen amount is from the calculated amount (0–1)."""
        if (
            self.chosen_amount
            and self.winning_run
            and self.winning_run.calculated_amount
            and self.winning_run.calculated_amount > 0
        ):
            return float(
                abs(self.chosen_amount - self.winning_run.calculated_amount)
                / self.winning_run.calculated_amount
            )
        return None
