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


class TextProcessStatus(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    RUNNING = "RUNNING", _("Running")
    COMPLETED = "COMPLETED", _("Completed")
    FAILED = "FAILED", _("Failed")
    SKIPPED = "SKIPPED", _("Skipped")


class TextProcessRun(models.Model):
    """
    A single execution of a text process over one document extraction.

    A *text process* is any algorithm that scans ``DocumentExtraction.raw_text``
    and emits labeled spans (``TextSpan``) — e.g. amount detection, date
    detection, boilerplate breakdown, entity detection.  One row per
    (extraction, process, method, provider, model, version), so regex
    heuristics and any number of AI models can coexist per text and be
    compared.  Processes that produce a decision-level verdict (e.g. the
    chosen amount) persist it in ``TextProcessResolution``.
    """

    extraction = models.ForeignKey(
        DocumentExtraction,
        on_delete=models.CASCADE,
        related_name="text_process_runs",
        help_text=_("The exact document text snapshot this run was executed on"),
    )

    # --- Process identity ---
    process = models.CharField(
        max_length=50,
        db_index=True,
        help_text=_("Process slug: 'amount', 'dates', 'boilerplate', ..."),
    )
    method = models.CharField(
        max_length=20,
        choices=[("regex", _("Regex / Heuristics")), ("ai", _("AI / LLM"))],
        default="regex",
        help_text=_("Execution method used for this run"),
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
        help_text=_("Model name for AI runs, else the algorithm tag"),
    )
    version = models.CharField(max_length=20, default="1.0")

    # --- Status ---
    status = models.CharField(
        max_length=20,
        choices=TextProcessStatus.choices,
        default=TextProcessStatus.PENDING,
        db_index=True,
    )

    # --- Run-level metadata / params / audit trail ---
    meta = models.JSONField(
        default=dict,
        blank=True,
        help_text=_(
            "Run-level inputs & outputs: params, raw response, computed totals, ..."
        ),
    )
    error_message = models.TextField(null=True, blank=True)

    # --- Cost tracking (null for regex runs) ---
    input_tokens = models.IntegerField(null=True, blank=True)
    output_tokens = models.IntegerField(null=True, blank=True)
    cost_usd = models.DecimalField(
        max_digits=10, decimal_places=6, null=True, blank=True
    )

    triggered_by = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="text_process_runs",
    )
    pipeline_run = models.ForeignKey(
        "core.PipelineRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="text_process_runs",
        help_text=_("Set when this process ran as part of a pipeline"),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Text Process Run")
        verbose_name_plural = _("Text Process Runs")
        unique_together = [
            ["extraction", "process", "method", "provider", "model", "version"]
        ]
        indexes = [
            models.Index(fields=["process", "status"]),
            models.Index(fields=["extraction", "process"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return (
            f"{self.extraction.decision.ada} [{self.process}/"
            f"{self.method}/{self.provider}]"
        )


class TextSpan(models.Model):
    """
    A labeled region of text produced by a ``TextProcessRun``.

    ``start``/``end`` are char offsets into the run's extraction
    ``raw_text`` (inclusive/exclusive) — including any markdown characters
    the extractor emitted.  ``value`` holds the process-specific payload
    (e.g. ``{"amount": "30000.00"}`` or ``{"date": "2026-08-05"}``).
    """

    run = models.ForeignKey(
        TextProcessRun,
        on_delete=models.CASCADE,
        related_name="spans",
    )
    label = models.CharField(
        max_length=50,
        db_index=True,
        help_text=_(
            "Span type: 'amount', 'date', 'boilerplate', 'signer', "
            "'subject', 'main_point', 'useless', 'entity', ..."
        ),
    )
    start = models.IntegerField(help_text=_("Char offset, inclusive"))
    end = models.IntegerField(help_text=_("Char offset, exclusive"))
    text_snippet = models.CharField(
        max_length=500,
        help_text=_("The matched text (for quick preview / debugging)"),
    )
    value = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Process-specific payload for this span"),
    )
    confidence = models.FloatField(null=True, blank=True)
    occurrence_count = models.PositiveIntegerField(
        default=1,
        help_text=_("How many times this span's value appears in the text"),
    )

    class Meta:
        verbose_name = _("Text Span")
        verbose_name_plural = _("Text Spans")
        ordering = ["start"]
        indexes = [
            models.Index(fields=["run", "label"]),
            models.Index(fields=["run", "start"]),
        ]

    def __str__(self):
        return f"{self.label} [{self.start}:{self.end}] {self.text_snippet[:40]!r}"


class TextProcessResolution(models.Model):
    """
    Decision-level verdict for a text process (optional).

    Only processes that pick a *winner* among their spans need one (e.g. the
    amount process resolves which detected amount is the correct one).
    One row per (decision, process) — the record queries/UI read.
    """

    decision = models.ForeignKey(
        Decision,
        on_delete=models.CASCADE,
        related_name="text_process_resolutions",
    )
    process = models.CharField(max_length=50, db_index=True)
    winning_run = models.ForeignKey(
        TextProcessRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolutions",
    )
    chosen_span = models.ForeignKey(
        TextSpan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text=_("The span that corresponds to the resolved value"),
    )
    value = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("The final resolved value, e.g. {'amount': '30000.00'}"),
    )
    has_discrepancy = models.BooleanField(
        default=False,
        db_index=True,
        help_text=_("True if the winning run found a discrepancy"),
    )
    note = models.TextField(
        null=True, blank=True, help_text=_("Explanation copied from the winning run")
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Text Process Resolution")
        verbose_name_plural = _("Text Process Resolutions")
        unique_together = [["decision", "process"]]
        indexes = [
            models.Index(fields=["-updated_at"]),
        ]

    def __str__(self):
        return f"{self.process} resolution for {self.decision.ada}"
