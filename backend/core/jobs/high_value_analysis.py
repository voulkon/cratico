"""
High-Value Decision Analysis Job

Analyzes decisions with significant financial amounts (entity amounts > threshold).
This job demonstrates custom filtering logic using entity amounts.
"""

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List

from core.ai_services import get_provider
from core.jobs.base import BaseAIJob
from core.models.document_analysis import Decision, DocumentAnalysis
from core.models.entities import DecisionEntityRelationship
from core.services.decision_facets import effective_linked_amount_sum
from django.db.models import DecimalField, OuterRef, Q, Subquery
from loguru import logger


class HighValueAnalysisJob(BaseAIJob):
    """
    Analyzes high-value decisions (entity amounts > threshold).

    This job demonstrates:
    - Custom database queries with entity amount filtering
    - Using should_process_item() for fine-grained control
    - Working with entity relationships and amounts
    - Flexible threshold configuration via kwargs

    Usage:
        # Create job definition in admin with:
        job_name="high_value_analysis"
        algorithm_module="core.jobs.high_value_analysis"
        algorithm_class="HighValueAnalysisJob"

        # Run with custom threshold
        job = HighValueAnalysisJob(job_def)
        execution = job.execute(
            provider="AWS_BEDROCK",
            model="anthropic.claude-3-haiku-20240307-v1:0",
            dry_run=False,
            min_amount=50000,  # Custom threshold
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31)
        )
    """

    # Job metadata
    JOB_NAME = "high_value_analysis"
    JOB_DISPLAY_NAME = "High-Value Decision Analysis"
    JOB_DESCRIPTION = (
        "Analyze decisions with significant entity amounts for financial insights"
    )

    # Default threshold (can be overridden in kwargs)
    DEFAULT_MIN_AMOUNT = Decimal("10000.00")

    # Analysis prompt
    ANALYSIS_PROMPT = """
Αναλύστε αυτή την υψηλής αξίας κυβερνητική απόφαση με έμφαση στα οικονομικά στοιχεία.

Παρακαλώ δώστε:
1. **Οικονομική Ανάλυση**: Συνολικά ποσά, κατανομή, ΚΑΕ
2. **Εμπλεκόμενες Οντότητες**: Προμηθευτές, ανάδοχοι, δικαιούχοι με ποσά
3. **Διαδικασία Ανάθεσης**: Τύπος διαγωνισμού, κριτήρια επιλογής
4. **Χρονοδιάγραμμα**: Ημερομηνίες υπογραφής, παράδοσης, πληρωμής
5. **Παρατηρήσεις**: Τυχόν ασυνήθιστα στοιχεία ή σημεία προσοχής

Κρατήστε την ανάλυση λεπτομερή αλλά σαφή (4-6 παραγράφους).
"""

    def get_items_to_process(
        self,
        min_amount: float = None,
        start_date: date = None,
        end_date: date = None,
        decision_types: List[str] = None,
        organization_ids: List[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Get all decisions with entity amounts above threshold.

        Args:
            min_amount: Minimum total entity amount (defaults to DEFAULT_MIN_AMOUNT)
            start_date: Start date filter (optional)
            end_date: End date filter (optional)
            decision_types: List of decision type UIDs to filter (optional)
            organization_ids: List of organization UIDs to filter (optional)

        Returns:
            List of item dictionaries with entity amount data
        """
        if min_amount is None:
            min_amount = float(self.DEFAULT_MIN_AMOUNT)

        logger.info(f"Fetching decisions with entity amounts >= {min_amount}")

        # Start with all decisions that have extractions
        decisions_qs = (
            Decision.objects.filter(
                text_extraction__extraction_status="COMPLETED",
                text_extraction__raw_text__isnull=False,
            )
            .exclude(text_extraction__raw_text="")
            .exclude(
                # Don't re-analyze if already has analysis from this job
                analysis_results__analysis_type=self.job_definition.analysis_type
            )
        )

        # Apply date filters if provided
        if start_date:
            decisions_qs = decisions_qs.filter(issue_date__gte=start_date)
        if end_date:
            decisions_qs = decisions_qs.filter(issue_date__lte=end_date)

        # Apply type and organization filters
        if decision_types:
            decisions_qs = decisions_qs.filter(decision_type__uid__in=decision_types)
        if organization_ids:
            decisions_qs = decisions_qs.filter(organization__uid__in=organization_ids)

        # Annotate with entity amounts (excluding 'org' role)
        # This is the key logic from your view
        entity_amounts_subquery = (
            DecisionEntityRelationship.objects.filter(decision_id=OuterRef("pk"))
            .exclude(role__iexact="org")
            .values("decision_id")
            .annotate(total=effective_linked_amount_sum())
            .values("total")
        )

        decisions_qs = decisions_qs.annotate(
            entity_total_amount=Subquery(
                entity_amounts_subquery, output_field=DecimalField()
            )
        )

        # Filter by minimum amount
        # Use Q to handle both entity amounts and direct decision amounts
        decisions_qs = decisions_qs.filter(
            Q(entity_total_amount__gte=min_amount)
            | Q(entity_total_amount__isnull=True, amount__gte=min_amount)
        )

        # Order by amount (highest first)
        decisions_qs = decisions_qs.order_by(
            "-entity_total_amount", "-amount", "-issue_date"
        )

        # Optimize queries
        decisions_qs = decisions_qs.select_related(
            "decision_type", "organization", "text_extraction"
        ).prefetch_related("kae_amounts", "signers")

        # Build items list with entity data
        items = []
        for decision in decisions_qs:
            # Get entity relationships for this decision
            entity_relationships = (
                DecisionEntityRelationship.objects.filter(decision=decision)
                .exclude(role__iexact="org")
                .select_related("entity")
                .annotate(total_amount=effective_linked_amount_sum())
            )

            # Serialize entity data
            entities_data = []
            total_entity_amount = Decimal("0")

            for rel in entity_relationships:
                entity_amount = rel.total_amount or Decimal("0")
                total_entity_amount += entity_amount

                entities_data.append(
                    {
                        "role": rel.role,
                        "afm": rel.entity.afm,
                        "name": rel.entity.name,
                        "entity_type": rel.entity.entity_type,
                        "amount": float(entity_amount),
                    }
                )

            # Use entity amount if available, otherwise decision amount
            final_amount = (
                total_entity_amount
                if total_entity_amount > 0
                else (decision.amount or Decimal("0"))
            )

            items.append(
                {
                    "item_type": "Decision",
                    "item_id": decision.id,
                    "item_identifier": decision.ada,
                    "content": decision.text_extraction.full_text,
                    "decision": decision,  # Keep reference
                    "entities": entities_data,
                    "total_amount": float(final_amount),
                    "decision_type": (
                        decision.decision_type.uid if decision.decision_type else None
                    ),
                    "organization": (
                        decision.organization.label if decision.organization else None
                    ),
                }
            )

        logger.info(f"Found {len(items)} high-value decisions to analyze")
        return items

    def should_process_item(self, item: Dict[str, Any]) -> bool:
        """
        Additional filtering logic per item.

        This is where you can add fine-grained checks that are expensive
        to do in the database query.

        Args:
            item: Item to check

        Returns:
            True if item should be processed
        """
        # Check amount threshold (double-check even though we filtered in query)
        min_amount = float(self.DEFAULT_MIN_AMOUNT)
        if item.get("total_amount", 0) < min_amount:
            logger.warning(
                f"Skipping {item['item_identifier']}: amount {item['total_amount']} below threshold"
            )
            return False

        # Skip if no entities (we want to analyze entity relationships)
        if not item.get("entities"):
            logger.warning(f"Skipping {item['item_identifier']}: no entities found")
            return False

        # Skip if content too short
        if len(item["content"]) < 200:
            logger.warning(f"Skipping {item['item_identifier']}: content too short")
            return False

        # Skip if content too long (context window limit)
        if len(item["content"]) > 800000:  # ~200K tokens
            logger.warning(f"Skipping {item['item_identifier']}: content too long")
            return False

        # Could add more custom logic here:
        # - Check if certain entity types are present
        # - Validate entity AFMs
        # - Check for specific decision types
        # - Early stopping conditions based on previous results

        return True

    def prepare_prompt(self, item: Dict[str, Any], **kwargs) -> str:
        """
        Customize prompt with entity amount context.

        Args:
            item: Item with entity data

        Returns:
            Enhanced prompt with context
        """
        base_prompt = self.job_definition.system_prompt or self.ANALYSIS_PROMPT

        # Add context about entities and amounts
        entities_context = "\n\n**Πληροφορίες Οντοτήτων:**\n"
        for entity in item.get("entities", [])[:5]:  # Top 5 entities
            entities_context += f"- {entity['name']} ({entity['afm']}): {entity['role']} - €{entity['amount']:,.2f}\n"

        entities_context += f"\n**Συνολικό Ποσό:** €{item['total_amount']:,.2f}"

        return base_prompt + entities_context

    def process_item(
        self, item: Dict[str, Any], provider: str, model: str, dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Process a single high-value decision.

        Args:
            item: Item from get_items_to_process
            provider: AI provider
            model: Model name
            dry_run: If True, only estimate cost

        Returns:
            Processing result with costs and analysis
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
            custom_output_ratio=float(
                self.job_definition.output_ratio or 0.25
            ),  # More detailed output
        )

        result = {
            "success": True,
            "input_tokens": estimate["input_tokens_with_overhead"],
            "output_tokens": estimate["output_tokens"],
            "estimated_cost_usd": estimate.get("total_cost_usd", Decimal("0")),
            "metadata": {
                "total_amount": item["total_amount"],
                "entity_count": len(item.get("entities", [])),
                "decision_type": item.get("decision_type"),
                "organization": item.get("organization"),
            },
        }

        # If dry run, return estimate only
        if dry_run:
            return result

        # Actually process with AI using unified provider interface
        try:
            # Get enhanced prompt with entity context
            prompt = self.prepare_prompt(item)

            # Get provider instance
            llm_provider = get_provider(provider, model)

            # Invoke the model
            api_result = llm_provider.invoke(
                text=content,
                prompt=prompt,
                temperature=0.7,
                max_tokens=4096,  # Higher for detailed financial analysis
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

            # Save analysis to database
            decision = item["decision"]
            analysis = DocumentAnalysis.objects.create(
                decision=decision,
                analysis_type=self.job_definition.analysis_type,
                provider=provider,
                model_name=model,
                content=result["result"],
                input_tokens=result["input_tokens"],
                output_tokens=result["output_tokens"],
                estimated_cost_usd=result["estimated_cost_usd"],
                actual_cost_usd=result.get("actual_cost_usd"),
                metadata={
                    "job_name": self.JOB_NAME,
                    "total_amount": item["total_amount"],
                    "entity_count": len(item.get("entities", [])),
                    "entities": item.get("entities", [])[:10],  # Store top 10 entities
                },
            )

            result["created_analysis"] = analysis
            logger.info(
                f"Analyzed high-value decision {item['item_identifier']} "
                f"(€{item['total_amount']:,.2f}, {len(item.get('entities', []))} entities)"
            )

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
