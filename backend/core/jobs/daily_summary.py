"""
Daily Document Summary Job

Processes all DocumentExtractions from a specific date and generates
summaries using AI.
"""

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List

from core.ai_services import get_provider
from core.jobs.base import BaseAIJob
from core.models.document_analysis import DocumentAnalysis, DocumentExtraction
from loguru import logger


class DailySummaryJob(BaseAIJob):
    """
    Job to summarize all document extractions from a specific day.

    This job:
    - Finds all completed extractions for a date
    - Generates AI summaries using customized prompts based on decision type
    - Tracks costs per document
    - Can be run as Celery task for background processing

    Usage:
        # Define the job (one-time setup in admin or code)
        job_def = AIJobDefinition.objects.create(
            job_name="daily_summary",
            display_name="Daily Document Summary",
            description="Summarize all documents extracted on a specific date",
            default_provider="AWS_BEDROCK",
            default_model="anthropic.claude-3-haiku-20240307-v1:0",
            analysis_type="summary",
            system_prompt=PROMPT_TEMPLATE,  # See below
            prompt_overhead_percentage=Decimal('0.05'),
            output_estimation_mode="RATIO",
            output_ratio=Decimal('0.20'),
            batch_size=1,
            algorithm_module="core.jobs.daily_summary",
            algorithm_class="DailySummaryJob"
        )

        # Validate implementation
        job = DailySummaryJob(job_def)
        job.validate_implementation()  # Raises error if something wrong

        # Estimate cost
        estimate = job.estimate_cost(
            provider="AWS_BEDROCK",
            model="anthropic.claude-3-haiku-20240307-v1:0",
            target_date=date(2025, 1, 1)
        )

        # Execute synchronously
        execution = job.execute(
            provider="AWS_BEDROCK",
            model="anthropic.claude-3-haiku-20240307-v1:0",
            dry_run=False,
            target_date=date(2025, 1, 1)
        )

        # Or run as Celery task (async)
        task = DailySummaryJob.create_celery_task(job_def)
        result = task.delay(
            provider="AWS_BEDROCK",
            model="anthropic.claude-3-haiku-20240307-v1:0",
            dry_run=False,
            target_date=date(2025, 1, 1)
        )
    """

    # Job metadata
    JOB_NAME = "daily_summary"
    JOB_DISPLAY_NAME = "Daily Document Summary"
    JOB_DESCRIPTION = (
        "Generate AI summaries for all documents extracted on a specific date"
    )

    # Prompt templates by decision type
    PROMPT_TEMPLATES = {
        "default": """
Παρακαλώ δημιουργήστε μια σύντομη περίληψη αυτής της κυβερνητικής απόφασης.
""",
        "Β.2.1": """  # Προσλήψεις
Δημιουργήστε περίληψη για αυτή την απόφαση πρόσληψης.
Συμπεριλάβετε:
- Τον φορέα που προσλαμβάνει
- Τον αριθμό και τις θέσεις προσλήψεων
- Τα προσόντα και απαιτήσεις
- Τις ημερομηνίες σημαντικών προθεσμιών
- Τυχόν οικονομικά στοιχεία (μισθοδοσία)

Κράτησε την περίληψη συνοπτική (2-4 παραγράφους).
""",
        "Β.2.2": """  # Δαπάνες
Δημιουργήστε περίληψη για αυτή την απόφαση δαπάνης.
Επικεντρωθείτε σε:
- Το είδος της δαπάνης
- Το συνολικό ποσό και τον ΚΑΕ
- Τον προμηθευτή ή δικαιούχο
- Τον σκοπό της δαπάνης
- Τη διαδικασία ανάθεσης (εάν υπάρχει)

Δώστε σαφή οικονομική ανάλυση.
""",
        "Β.2.3": """  # Συμβάσεις
Αναλύστε αυτή τη σύμβαση με έμφαση στα:
- Τα συμβαλλόμενα μέρη
- Το αντικείμενο της σύμβασης
- Τη διάρκεια και τους όρους
- Το οικονομικό αντάλλαγμα
- Τις υποχρεώσεις και τα παραδοτέα

Κάντε την περίληψη πρακτική και εύχρηστη.
""",
    }

    def get_items_to_process(
        self, target_date: date = None, **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Get all DocumentExtractions for the target date.

        Args:
            target_date: Date to process (defaults to today)

        Returns:
            List of item dictionaries
        """
        if not target_date:
            target_date = date.today()

        logger.info(f"Fetching extractions for date: {target_date}")

        # Get completed extractions for the date that don't have summaries yet
        extractions = (
            DocumentExtraction.objects.filter(
                extraction_status="COMPLETED",
                extraction_date__date=target_date,
                raw_text__isnull=False,
            )
            .exclude(raw_text="")
            .exclude(
                # Don't re-summarize if already has a summary from this job
                decision__analysis_results__analysis_type="summary"
            )
            .select_related("decision")
        )

        items = []
        for extraction in extractions:
            items.append(
                {
                    "item_type": "DocumentExtraction",
                    "item_id": extraction.id,
                    "item_identifier": extraction.decision.ada,
                    "content": extraction.full_text,  # Use property that gets all pages
                    "extraction": extraction,  # Keep reference for actual processing
                }
            )

        logger.info(f"Found {len(items)} extractions to summarize")
        return items

    def prepare_prompt(self, item: Dict[str, Any], **kwargs) -> str:
        """
        Prepare prompt based on decision type.

        Args:
            item: Item with 'extraction' reference

        Returns:
            Customized prompt for this decision type
        """
        extraction = item.get("extraction")
        if not extraction:
            return self.job_definition.system_prompt or self.PROMPT_TEMPLATES["default"]

        # Get decision type code
        decision_type_code = None
        if extraction.decision.decision_type:
            decision_type_code = extraction.decision.decision_type.uid

        # Use specific template if available, otherwise use default
        prompt_template = self.PROMPT_TEMPLATES.get(
            decision_type_code, self.PROMPT_TEMPLATES["default"]
        )

        # Can also inject variables into prompt
        # For example, if you want to include organization name:
        # prompt = prompt_template.format(
        #     organization=extraction.decision.organization.label
        # )

        return prompt_template

    def should_process_item(self, item: Dict[str, Any]) -> bool:
        """
        Filter out items that shouldn't be processed.

        Args:
            item: Item to check

        Returns:
            True if item should be processed
        """
        extraction = item.get("extraction")
        if not extraction:
            return False

        content = item.get("content") or ""
        identifier = item.get("item_identifier") or item.get("item_id", "unknown")

        # Skip if content too short (likely corrupt)
        if len(content) < 100:
            logger.warning(f"Skipping {identifier}: content too short")
            return False

        # Skip if content too long (over context window)
        # Assuming ~4 chars per token, 200K token window
        if len(content) > 800000:  # 800K chars ~ 200K tokens
            logger.warning(f"Skipping {identifier}: content too long")
            return False

        return True

    def process_item(
        self, item: Dict[str, Any], provider: str, model: str, dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Process a single document extraction - generate summary.

        Args:
            item: Item from get_items_to_process
            provider: AI provider
            model: Model name
            dry_run: If True, only estimate cost

        Returns:
            Processing result with costs and output
        """
        content = item["content"]

        # Estimate tokens and cost
        estimate = self.cost_estimator.estimate_analysis_cost(
            text=content,
            provider=provider,
            model_name=model,
            task_type=self.job_definition.analysis_type,
            custom_overhead=float(
                self.job_definition.prompt_overhead_percentage or 0.05
            ),
            custom_output_ratio=float(self.job_definition.output_ratio or 0.20),
        )

        result = {
            "success": True,
            "input_tokens": estimate["input_tokens_with_overhead"],
            "output_tokens": estimate["output_tokens"],
            "estimated_cost_usd": estimate.get("total_cost_usd", Decimal("0")),
        }

        # If dry run, return just the estimate
        if dry_run:
            return result

        # Actually process with AI using unified provider interface
        try:
            # Get customized prompt for this decision type
            prompt = self.prepare_prompt(item)

            # Get provider instance
            llm_provider = get_provider(provider, model)

            # Invoke the model
            api_result = llm_provider.invoke(
                text=content, prompt=prompt, temperature=0.7, max_tokens=2048
            )

            if not api_result["success"]:
                return {
                    "success": False,
                    "error": api_result.get("error", "Unknown error"),
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "estimated_cost_usd": Decimal("0"),
                }

            # Update with actual costs from provider
            result["output_tokens"] = api_result.get(
                "output_tokens", estimate["output_tokens"]
            )
            result["actual_cost_usd"] = api_result.get(
                "actual_cost_usd", estimate["total_cost_usd"]
            )
            result["result"] = api_result["text"]
            result["latency_ms"] = api_result.get("latency_ms", 0)

            # Save the analysis to the database
            extraction = item["extraction"]
            analysis = DocumentAnalysis.objects.create(
                decision=extraction.decision,
                analysis_type=self.job_definition.analysis_type,
                provider=provider,
                model_name=model,
                content=result["result"],
                input_tokens=result["input_tokens"],
                output_tokens=result["output_tokens"],
                estimated_cost_usd=result["estimated_cost_usd"],
                actual_cost_usd=result.get("actual_cost_usd"),
            )

            result["created_analysis"] = analysis
            logger.info(f"Created summary for {item['item_identifier']}")

            return result

        except Exception as e:
            logger.error(f"Error processing item {item['item_identifier']}: {e}")
            return {
                "success": False,
                "error": str(e),
                "input_tokens": estimate["input_tokens_with_overhead"],
                "output_tokens": 0,
                "estimated_cost_usd": estimate.get("total_cost_usd", Decimal("0")),
            }
