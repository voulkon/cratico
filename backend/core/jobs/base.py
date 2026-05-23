"""
Base class for AI job implementations with Celery integration.
"""

import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Type

from core.models.ai_pricing import AIJobDefinition, AIJobExecution, AIJobExecutionItem
from core.utils.ai_cost_estimator import AICostEstimator
from django.db import transaction
from loguru import logger


class JobValidationError(Exception):
    """Raised when job implementation fails validation"""


class BaseAIJob(ABC):
    """
    Base class for AI job implementations.

    Provides:
    - Standardized interface for job implementations
    - Dry run estimation
    - Actual execution with cost tracking
    - Progress tracking
    - Error handling
    - Validation methods
    - Celery task integration

    Required methods to implement:
    - get_items_to_process(**kwargs) -> List[Dict[str, Any]]
    - process_item(item, provider, model, dry_run) -> Dict[str, Any]

    Optional methods to override:
    - prepare_prompt(item, **kwargs) -> str
    - validate_implementation() -> bool
    - should_process_item(item) -> bool
    """

    # Job metadata (override in subclasses)
    JOB_NAME: str = None  # e.g., "daily_summary"
    JOB_DISPLAY_NAME: str = None  # e.g., "Daily Document Summary"
    JOB_DESCRIPTION: str = None

    # Expected item structure (for validation)
    REQUIRED_ITEM_KEYS = ["item_type", "item_id", "item_identifier", "content"]

    # Expected result structure (for validation)
    REQUIRED_RESULT_KEYS = [
        "success",
        "input_tokens",
        "output_tokens",
        "estimated_cost_usd",
    ]

    def __init__(self, job_definition: AIJobDefinition):
        """
        Initialize the job with its definition.

        Args:
            job_definition: The AIJobDefinition instance
        """
        self.job_definition = job_definition
        self.cost_estimator = AICostEstimator()
        self.execution: Optional[AIJobExecution] = None

    @abstractmethod
    def get_items_to_process(self, **kwargs) -> List[Dict[str, Any]]:
        """
        Get the list of items to process.

        Returns:
            List of dicts with item information:
            [
                {
                    'item_type': 'DocumentExtraction',
                    'item_id': 123,
                    'item_identifier': 'ADA123',
                    'content': 'text to process...'
                },
                ...
            ]
        """

    @abstractmethod
    def process_item(
        self, item: Dict[str, Any], provider: str, model: str, dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Process a single item.

        Args:
            item: Item dictionary from get_items_to_process
            provider: AI provider to use
            model: Model name to use
            dry_run: If True, only estimate cost without calling API

        Returns:
            Dict with REQUIRED keys:
            {
                'success': bool,
                'input_tokens': int,
                'output_tokens': int,
                'estimated_cost_usd': Decimal,
                'actual_cost_usd': Decimal (only if not dry_run and success),
                'result': Any (the actual result, only if not dry_run and success),
                'error': str (if success=False),
                'created_analysis': DocumentAnalysis (optional, if analysis created)
            }
        """

    def prepare_prompt(self, item: Dict[str, Any], **kwargs) -> str:
        """
        Prepare the prompt for processing an item.
        Override this to customize prompts based on item properties.

        Args:
            item: Item to process
            **kwargs: Additional context

        Returns:
            Formatted prompt string
        """
        # Default: return system prompt from job definition
        return self.job_definition.system_prompt or ""

    def should_process_item(self, item: Dict[str, Any]) -> bool:
        """
        Determine if an item should be processed.
        Override this to add custom filtering logic.

        Args:
            item: Item to check

        Returns:
            True if item should be processed
        """
        return True

    def validate_implementation(self) -> bool:
        """
        Validate that the job implementation is correct.
        Override to add custom validation.

        Returns:
            True if valid

        Raises:
            JobValidationError if validation fails
        """
        # Check class metadata
        if not self.JOB_NAME:
            raise JobValidationError(f"{self.__class__.__name__} must set JOB_NAME")

        # Test with sample items
        try:
            items = self.get_items_to_process()
            if items:
                # Validate item structure
                sample_item = items[0]
                for key in self.REQUIRED_ITEM_KEYS:
                    if key not in sample_item:
                        raise JobValidationError(
                            f"Items from get_items_to_process() must include key: {key}"
                        )

                # Test process_item in dry run
                result = self.process_item(
                    item=sample_item,
                    provider=self.job_definition.default_provider,
                    model=self.job_definition.default_model,
                    dry_run=True,
                )

                # Validate result structure
                for key in self.REQUIRED_RESULT_KEYS:
                    if key not in result:
                        raise JobValidationError(
                            f"process_item() must return key: {key}"
                        )

                if not isinstance(result["success"], bool):
                    raise JobValidationError("process_item()['success'] must be bool")

                if not isinstance(result["input_tokens"], int):
                    raise JobValidationError(
                        "process_item()['input_tokens'] must be int"
                    )

                logger.info(f"[OK] Job {self.JOB_NAME} validation passed")
                return True
        except Exception as e:
            raise JobValidationError(f"Validation failed: {e}")

        return True

    def estimate_cost(self, provider: str, model: str, **kwargs) -> Dict[str, Any]:
        """
        Perform dry run to estimate total cost.

        Args:
            provider: AI provider to use
            model: Model name
            **kwargs: Additional arguments for get_items_to_process

        Returns:
            Dict with estimation results
        """
        logger.info(f"Starting cost estimation for job: {self.job_definition.job_name}")
        logger.info(f"Provider: {provider}, Model: {model}")

        # Get items to process
        items = self.get_items_to_process(**kwargs)

        # Filter items using should_process_item
        items = [item for item in items if self.should_process_item(item)]

        logger.info(f"Found {len(items)} items to process (after filtering)")

        if not items:
            return {"total_items": 0, "total_cost_usd": Decimal("0"), "items": []}

        total_cost = Decimal("0")
        total_input_tokens = 0
        total_output_tokens = 0
        item_estimates = []

        # Process each item in dry-run mode
        for idx, item in enumerate(items, 1):
            try:
                result = self.process_item(
                    item=item, provider=provider, model=model, dry_run=True
                )

                if result["success"]:
                    total_cost += result["estimated_cost_usd"]
                    total_input_tokens += result["input_tokens"]
                    total_output_tokens += result["output_tokens"]

                    item_estimates.append(
                        {
                            "sequence": idx,
                            "item_id": item["item_id"],
                            "item_identifier": item.get("item_identifier"),
                            "input_tokens": result["input_tokens"],
                            "output_tokens": result["output_tokens"],
                            "cost_usd": result["estimated_cost_usd"],
                        }
                    )
                else:
                    logger.warning(
                        f"Failed to estimate item {idx}: {result.get('error')}"
                    )

            except Exception as e:
                logger.error(f"Error estimating item {idx}: {e}")

        avg_cost_per_item = total_cost / len(items) if items else Decimal("0")

        result = {
            "job_name": self.job_definition.job_name,
            "provider": provider,
            "model": model,
            "total_items": len(items),
            "successfully_estimated": len(item_estimates),
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_cost_usd": total_cost,
            "average_cost_per_item_usd": avg_cost_per_item,
            "items": item_estimates,
        }

        logger.info(f"Estimation complete: ${total_cost:.6f} for {len(items)} items")
        return result

    @transaction.atomic
    def execute(
        self,
        provider: str,
        model: str,
        dry_run: bool = False,
        execution_id: Optional[str] = None,
        **kwargs,
    ) -> AIJobExecution:
        """
        Execute the job (or dry run).

        Args:
            provider: AI provider to use
            model: Model name
            dry_run: If True, only estimate without actual API calls
            execution_id: Optional custom execution ID
            **kwargs: Additional arguments for get_items_to_process

        Returns:
            AIJobExecution instance
        """
        # Generate execution ID
        if not execution_id:
            execution_id = f"{self.job_definition.job_name}-{uuid.uuid4().hex[:8]}"

        # Get items to process
        items = self.get_items_to_process(**kwargs)
        logger.info(f"Starting execution {execution_id} with {len(items)} items")

        # Create execution record
        self.execution = AIJobExecution.objects.create(
            job_definition=self.job_definition,
            execution_id=execution_id,
            status="RUNNING",
            provider_used=provider,
            model_used=model,
            items_scope={
                "item_ids": [item["item_id"] for item in items],
                "total_count": len(items),
                "kwargs": kwargs,
            },
        )

        try:
            total_input_tokens = 0
            total_output_tokens = 0
            total_cost = Decimal("0")
            successful_items = 0

            # Process each item
            for idx, item in enumerate(items, 1):
                try:
                    result = self.process_item(
                        item=item, provider=provider, model=model, dry_run=dry_run
                    )

                    # Create execution item record
                    AIJobExecutionItem.objects.create(
                        execution=self.execution,
                        item_type=item["item_type"],
                        item_id=item["item_id"],
                        item_identifier=item.get("item_identifier"),
                        sequence_number=idx,
                        input_tokens=result["input_tokens"],
                        output_tokens=result["output_tokens"],
                        estimated_cost_usd=result.get("estimated_cost_usd"),
                        actual_cost_usd=result.get("actual_cost_usd"),
                        result_data=result.get("result") if not dry_run else None,
                        success=result["success"],
                        error_message=result.get("error"),
                        created_analysis=result.get(
                            "created_analysis"
                        ),  # If analysis was created
                    )

                    if result["success"]:
                        successful_items += 1
                        total_input_tokens += result["input_tokens"]
                        total_output_tokens += result["output_tokens"]

                        if dry_run:
                            total_cost += result["estimated_cost_usd"]
                        else:
                            total_cost += result.get(
                                "actual_cost_usd", result["estimated_cost_usd"]
                            )

                    logger.info(
                        f"Processed item {idx}/{len(items)}: {item.get('item_identifier')}"
                    )

                except Exception as e:
                    logger.error(f"Error processing item {idx}: {e}")
                    AIJobExecutionItem.objects.create(
                        execution=self.execution,
                        item_type=item["item_type"],
                        item_id=item["item_id"],
                        item_identifier=item.get("item_identifier"),
                        sequence_number=idx,
                        success=False,
                        error_message=str(e),
                    )

            # Update execution record
            self.execution.status = "COMPLETED"
            self.execution.completed_at = datetime.now()
            self.execution.items_processed = successful_items
            self.execution.total_input_tokens = total_input_tokens
            self.execution.total_output_tokens = total_output_tokens

            if dry_run:
                self.execution.estimated_cost_usd = total_cost
            else:
                self.execution.actual_cost_usd = total_cost

            self.execution.result_summary = {
                "total_items": len(items),
                "successful": successful_items,
                "failed": len(items) - successful_items,
                "dry_run": dry_run,
            }

            execution_time = (
                datetime.now() - self.execution.started_at
            ).total_seconds()
            self.execution.execution_time_seconds = int(execution_time)
            self.execution.save()

            logger.info(f"Execution {execution_id} completed successfully")
            logger.info(f"Processed: {successful_items}/{len(items)} items")
            logger.info(f"Total cost: ${total_cost:.6f}")

            return self.execution

        except Exception as e:
            logger.error(f"Execution {execution_id} failed: {e}")
            self.execution.status = "FAILED"
            self.execution.error_message = str(e)
            self.execution.completed_at = datetime.now()
            self.execution.save()
            raise

    @classmethod
    def create_celery_task(cls, job_definition: AIJobDefinition):
        """
        Create a Celery task for this job class.

        Returns:
            Celery task function
        """
        from celery import shared_task

        @shared_task(
            name=f"ai_job.{job_definition.job_name}",
            bind=True,
            max_retries=3,
            default_retry_delay=60,
        )
        def execute_job_task(
            self, provider: str, model: str, dry_run: bool = False, **kwargs
        ):
            """
            Celery task to execute the AI job.

            Args:
                provider: AI provider to use
                model: Model name
                dry_run: If True, only estimate costs
                **kwargs: Additional arguments for get_items_to_process

            Returns:
                Dict with execution results
            """
            try:
                job = cls(job_definition)
                execution = job.execute(
                    provider=provider,
                    model=model,
                    dry_run=dry_run,
                    execution_id=self.request.id,  # Use Celery task ID
                    **kwargs,
                )

                return {
                    "execution_id": execution.execution_id,
                    "status": execution.status,
                    "items_processed": execution.items_processed,
                    "total_cost_usd": float(
                        execution.actual_cost_usd or execution.estimated_cost_usd or 0
                    ),
                    "dry_run": dry_run,
                }

            except Exception as e:
                logger.error(f"Celery task failed: {e}")
                # Retry on certain errors
                self.retry(exc=e)

        return execute_job_task


# Helper function to load job class dynamically
def load_job_class(job_definition: AIJobDefinition) -> Type[BaseAIJob]:
    """
    Dynamically load a job class from its module path.

    Args:
        job_definition: AIJobDefinition with algorithm_module and algorithm_class

    Returns:
        Job class

    Raises:
        ImportError if module or class not found
    """
    import importlib

    if not job_definition.algorithm_module or not job_definition.algorithm_class:
        raise ValueError(
            f"Job {job_definition.job_name} missing algorithm_module or algorithm_class"
        )

    try:
        module = importlib.import_module(job_definition.algorithm_module)
        job_class = getattr(module, job_definition.algorithm_class)

        if not issubclass(job_class, BaseAIJob):
            raise TypeError(f"{job_class} must inherit from BaseAIJob")

        return job_class

    except ImportError as e:
        raise ImportError(f"Could not import {job_definition.algorithm_module}: {e}")
    except AttributeError:
        raise AttributeError(
            f"Module {job_definition.algorithm_module} has no class {job_definition.algorithm_class}"
        )
