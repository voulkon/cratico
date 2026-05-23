import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from core.models.decisions import Decision
from core.models.document_analysis import DocumentExtraction
from django.utils import timezone
from loguru import logger


class DecompositionResult:
    def __init__(
        self,
        success: bool,
        data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ):
        self.success = success
        self.data = data or {}
        self.error = error


class DecompositionStrategy(ABC):
    """
    Abstract base class for decision decomposition strategies.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name of the strategy."""

    @abstractmethod
    def decompose(self, decision: Decision, text: str) -> DecompositionResult:
        """
        Attempt to decompose the decision text into structured data.

        Args:
            decision: The Decision object.
            text: The raw text of the decision.

        Returns:
            DecompositionResult object.
        """


class StrategyRunner:
    """
    Helper to run strategies on datasets and persist results to database.
    """

    def __init__(self, strategy: DecompositionStrategy, version: str = "1.0"):
        self.strategy = strategy
        self.version = version

    def run_on_queryset(
        self, queryset, notes: str = "", config: dict = None
    ) -> "ExperimentRun":
        """
        Run strategy on queryset and save results to database.
        Returns the ExperimentRun object for analysis.
        """
        from experiments.models import ExperimentResult, ExperimentRun

        # Determine decision_type if all decisions are same type
        decision_type = None
        if queryset.exists():
            types = queryset.values_list("decision_type", flat=True).distinct()
            if len(types) == 1:
                from core.models.types import ActType

                decision_type = ActType.objects.filter(uid=types[0]).first()

        # Create experiment run
        run = ExperimentRun.objects.create(
            strategy_name=self.strategy.name,
            strategy_version=self.version,
            decision_type=decision_type,
            dataset_filter={"queryset": str(queryset.query)},
            total_decisions=queryset.count(),
            notes=notes,
            config=config or {},
        )

        start_time = time.time()

        for decision in queryset:
            # Get text
            try:
                extraction = DocumentExtraction.objects.get(decision=decision)
                text = extraction.raw_text or ""
            except DocumentExtraction.DoesNotExist:
                ExperimentResult.objects.create(
                    run=run,
                    decision=decision,
                    success=False,
                    error_message="No extraction found",
                )
                continue

            # Run strategy
            result_start = time.time()
            try:
                result = self.strategy.decompose(decision, text)
                processing_ms = int((time.time() - result_start) * 1000)

                ExperimentResult.objects.create(
                    run=run,
                    decision=decision,
                    success=result.success,
                    error_message=result.error,
                    extracted_data=result.data,
                    processing_time_ms=processing_ms,
                    confidence_score=(
                        result.data.get("confidence_score") if result.success else None
                    ),
                )

            except Exception as e:
                processing_ms = int((time.time() - result_start) * 1000)
                logger.exception(
                    f"Strategy {self.strategy.name} crashed on {decision.ada}"
                )

                ExperimentResult.objects.create(
                    run=run,
                    decision=decision,
                    success=False,
                    error_message=str(e),
                    processing_time_ms=processing_ms,
                )

        # Finalize run
        run.completed_at = timezone.now()
        run.duration_seconds = time.time() - start_time
        run.calculate_metrics()

        logger.info(
            f"Experiment completed: {run.strategy_name} - {run.success_rate:.1f}% success rate"
        )
        return run
