"""
Service for classifying decisions as direct assignments (ΑΠΕΥΘΕΙΑΣ ΑΝΑΘΕΣΕΙΣ).

This service encapsulates the classification algorithm that determines whether
a decision qualifies as a direct assignment based on:
1. Decision type (Δ.1)
2. Amount below threshold (€37,200)
3. Text content patterns (keywords indicating direct assignment)

Results are stored in DecisionClassification model for fast querying.
The pipeline orchestrator calls this service during Stage 8.
"""

import re
import unicodedata
from decimal import Decimal
from typing import Dict, Optional

from core.models.decision_classification import (
    DecisionClassification,
    DirectAssignmentDetectionMethod,
)
from core.models.decisions import Decision
from core.services.financial_calculation_service import financial_service
from django.db.models import Q, QuerySet
from loguru import logger


class DirectAssignmentDetectionService:
    """
    Classifies decisions as direct assignments and stores results.

    Business Rules:
    1. Must be decision type Δ.1 (direct assignment type)
    2. Total amount must be below €37,200 threshold
    3. Must have a valid amount

    Uses FinancialCalculationService for accurate amount calculations.
    Some examples:
    9ΔΩΗΩ16-Β2Α
    Ρ5ΟΓΩΕ6-Ι41
    6ΜΚ4ΟΚ91-32Χ
    ΨΠ9446ΨΧΥΙ-ΕΛ3
    Ρ9Ψ4Ω6Ι-ΤΘ8
    62ΡΑΟΡΝ0-0Ξ9

    # TODO
    # Have it detect associated_relationship_id in core_decisionamountfield  -
    # it leaves them null for now
    # ADA ΨΚ29ΟΛ3Υ-0ΤΡ
    # With:
    # {"cpv": ["90513700-3", "90513900-5"], "person": [{"afm": "800410090", "name": "ΒΙΟΣΤΕΡΕΑ ΠΑΡΑΓΩΓΗ ΕΔΑΦΟΒΕΛΤΙΩΤΙΚΩΝ ΑΝΩΝΥΜΟΣ ΕΤΑΙΡΕΙΑ", "afmType": "EL", "enterName": false}], "budgettype": null, "partialead": null, "awardAmount": {"amount": 26040.0, "currency": "EUR"}, "entryNumber": null, "documentType": "ΠΡΑΞΗ", "amountWithKae": null, "amountWithVAT": null, "financialYear": null, "assignmentType": "Υπηρεσίες", "textRelatedADA": null, "relatedDecisions": [], "recalledExpenseDecision": null}
    # TODO

    """

    # Constants
    DIRECT_ASSIGNMENT_TYPE_UID = "Δ.1"
    STANDARD_THRESHOLD = Decimal("37200.00")  # €30,000 + 24% VAT
    CLASSIFIER_VERSION = "v2.0"

    # Text patterns for direct assignment detection
    # These patterns look for Greek phrases indicating direct assignment
    TEXT_PATTERNS = [
        r"απευθείας\s+αν[άα]θεσ[ηή]",  # "απευθείας ανάθεση" or "απευθείας αναθεση"
        r"απ'\s*ευθείας\s+αν[άα]θεσ[ηή]",  # "απ' ευθείας ανάθεση"
        r"άμεσ[ηησ]\s+αν[άα]θεσ[ηή]",  # "άμεση ανάθεση"
        r"ευθεί[αά]\s+αν[άα]θεσ[ηή]",  # "ευθεία ανάθεση"
    ]

    @staticmethod
    def _strip_accents(text: str) -> str:
        """Strip Unicode combining accent marks (e.g. ί→ι, ά→α) for Greek uppercase matching."""
        return "".join(
            c
            for c in unicodedata.normalize("NFD", text)
            if unicodedata.category(c) != "Mn"
        )

    def __init__(self):
        """Initialize service with financial calculation dependency."""
        self.financial_service = financial_service
        # Compile accent-stripped patterns so ALL-CAPS Greek text (which drops accents) matches.
        # e.g. 'ΑΠΕΥΘΕΙΑΣ' has plain Ι (U+0399), not accented Ί (U+038A).
        self.compiled_patterns = [
            re.compile(self._strip_accents(pattern), re.IGNORECASE | re.UNICODE)
            for pattern in self.TEXT_PATTERNS
        ]

    # =============================================================================
    # CORE CLASSIFICATION LOGIC
    # =============================================================================

    def _check_text_content(self, decision: Decision) -> bool:
        """
        Check if decision's text content contains direct assignment keywords.

        Args:
            decision: Decision to check

        Returns:
            True if text contains direct assignment patterns
        """
        # Use getattr for safer access - missing text_extraction is expected
        extraction = getattr(decision, "text_extraction", None)
        if not extraction:
            return False

        text = getattr(extraction, "raw_text", None)
        if not text:
            return False

        # Normalize: strip accent marks so ALL-CAPS Greek (e.g. ΑΠΕΥΘΕΙΑΣ) matches
        # accented lowercase patterns (e.g. απευθείας). In Greek, capitalisation
        # drops accents: ί (U+03AF) → Ι (U+0399), not Ί (U+038A).
        text = self._strip_accents(text)

        # Check each compiled pattern
        for pattern in self.compiled_patterns:
            if pattern.search(text):
                logger.debug(f"Found direct assignment pattern in {decision.ada} text")
                return True

        return False

    def classify_decision(self, decision: Decision) -> Dict[str, any]:
        """
        Apply classification algorithm to determine if decision is a direct assignment.

        This method performs the classification WITHOUT saving to database.
        Use classify_and_save() to persist results.

        Checks both metadata (type & amount) and text content.

        Args:
            decision: Decision object to classify

        Returns:
            Dictionary with classification results:
            - is_direct_assignment: bool
            - confidence: float (0.0 to 1.0)
            - reason: str (explanation)
            - amount: Decimal (amount used for classification)
            - detection_method: DirectAssignmentDetectionMethod enum
        """
        # Check text content first (can work without metadata)
        text_indicates_direct_assignment = self._check_text_content(decision)

        # Rule 1: Must be type Δ.1 (for metadata-based detection)
        if not decision.decision_type:
            # No metadata, rely only on text
            if text_indicates_direct_assignment:
                return {
                    "is_direct_assignment": True,
                    "confidence": 0.8,  # Lower confidence without metadata confirmation
                    "reason": "Text content indicates direct assignment (no decision type to confirm)",
                    "amount": None,
                    "detection_method": DirectAssignmentDetectionMethod.TEXT,
                }
            return {
                "is_direct_assignment": False,
                "confidence": 1.0,
                "reason": "No decision type",
                "amount": None,
                "detection_method": DirectAssignmentDetectionMethod.NONE,
            }

        metadata_correct_type = (
            decision.decision_type.uid == self.DIRECT_ASSIGNMENT_TYPE_UID
        )

        if not metadata_correct_type and not text_indicates_direct_assignment:
            return {
                "is_direct_assignment": False,
                "confidence": 1.0,
                "reason": f"Not Δ.1 type (found: {decision.decision_type.uid}) and no text indicators",
                "amount": decision.amount,
                "detection_method": DirectAssignmentDetectionMethod.NONE,
            }

        # Rule 2: Must have amount (for metadata-based detection)
        # Use FinancialCalculationService for accurate amount calculation
        breakdown = self.financial_service.get_decision_amount_breakdown(decision)
        total_amount = breakdown["total_amount"]

        if total_amount is None or total_amount <= 0:
            # No valid amount, check text
            if text_indicates_direct_assignment:
                return {
                    "is_direct_assignment": True,
                    "confidence": 0.7,  # Lower confidence without amount confirmation
                    "reason": "Text content indicates direct assignment (no valid amount found)",
                    "amount": None,
                    "detection_method": DirectAssignmentDetectionMethod.TEXT,
                }
            return {
                "is_direct_assignment": False,
                "confidence": 0.5,  # Low confidence - it's Δ.1 but no amount
                "reason": "No valid amount found",
                "amount": None,
                "detection_method": DirectAssignmentDetectionMethod.NONE,
            }

        # Rule 3: Amount must be below threshold (for metadata-based detection)
        metadata_below_threshold = total_amount < self.STANDARD_THRESHOLD

        # Determine result based on metadata AND text
        if metadata_correct_type and metadata_below_threshold:
            # Metadata confirms direct assignment
            if text_indicates_direct_assignment:
                detection_method = DirectAssignmentDetectionMethod.BOTH
                confidence = 1.0
                reason = f"Δ.1 type with amount €{total_amount} < €{self.STANDARD_THRESHOLD} + text confirmation"
            else:
                detection_method = DirectAssignmentDetectionMethod.METADATA
                confidence = 1.0
                reason = (
                    f"Δ.1 type with amount €{total_amount} < €{self.STANDARD_THRESHOLD}"
                )

            return {
                "is_direct_assignment": True,
                "confidence": confidence,
                "reason": reason,
                "amount": total_amount,
                "detection_method": detection_method,
            }

        elif text_indicates_direct_assignment:
            # Text indicates direct assignment but metadata doesn't
            # This could be a misclassified decision or wrong amount
            return {
                "is_direct_assignment": True,
                "confidence": 0.6,  # Lower confidence when text and metadata conflict
                "reason": f"Text indicates direct assignment but metadata shows amount €{total_amount} >= €{self.STANDARD_THRESHOLD}",
                "amount": total_amount,
                "detection_method": DirectAssignmentDetectionMethod.TEXT,
            }

        else:
            # Neither metadata nor text indicate direct assignment
            return {
                "is_direct_assignment": False,
                "confidence": 1.0,
                "reason": f"Amount €{total_amount} >= threshold €{self.STANDARD_THRESHOLD}",
                "amount": total_amount,
                "detection_method": DirectAssignmentDetectionMethod.NONE,
            }

    def classify_and_save(self, decision: Decision) -> DecisionClassification:
        """
        Classify decision and save results to DecisionClassification table.

        This method is called by the pipeline orchestrator (Stage 8).
        Uses update_or_create for idempotency.

        Args:
            decision: Decision to classify

        Returns:
            DecisionClassification object (created or updated)
        """
        result = self.classify_decision(decision)

        classification, created = DecisionClassification.objects.update_or_create(
            decision=decision,
            defaults={
                "is_direct_assignment": result["is_direct_assignment"],
                "detection_method": result["detection_method"],
                "classifier_version": self.CLASSIFIER_VERSION,
            },
        )

        action = "Created" if created else "Updated"
        logger.debug(
            f"{action} classification for {decision.ada}: "
            f"is_direct_assignment={result['is_direct_assignment']} "
            f"via {result['detection_method']} "
            f"({result['reason']})"
        )

        return classification

    # =============================================================================
    # BULK CLASSIFICATION
    # =============================================================================

    def bulk_classify(
        self, decisions, batch_size: int = 1000, update_existing: bool = False
    ) -> Dict[str, int]:
        """
        Efficiently classify multiple decisions in bulk.

        Used by:
        - Management command for backfilling existing decisions
        - Scheduled task for catching unclassified decisions
        - Background classification jobs

        Args:
            decisions: QuerySet or list of Decision objects to classify
            batch_size: Number of decisions to process per batch
            update_existing: If True, update existing classifications (default: False)

        Returns:
            Statistics dictionary with counts
        """
        stats = {
            "total_processed": 0,
            "direct_assignments": 0,
            "non_direct_assignments": 0,
            "created": 0,
            "updated": 0,
            "errors": 0,
        }

        classifications_to_create = []
        classifications_to_update = []

        # Get existing classifications to determine create vs update
        existing_classifications = {
            c.decision_id: c
            for c in DecisionClassification.objects.filter(
                decision__in=decisions
            ).select_related("decision")
        }

        # Handle both QuerySet and list inputs
        from django.db.models import QuerySet

        if isinstance(decisions, QuerySet):
            decision_count = decisions.count()
            # Process QuerySet in batches using slicing to avoid named cursor issues
            decisions_with_prefetch = decisions.select_related(
                "decision_type"
            ).prefetch_related("text_extraction")
        else:
            # It's a list
            decision_count = len(decisions)
            decisions_with_prefetch = decisions

        logger.info(f"Starting bulk classification of {decision_count} decisions")

        # Process in batches
        offset = 0
        while offset < decision_count:
            # Fetch batch (for QuerySet, slice creates new query; for list, just slice)
            if isinstance(decisions_with_prefetch, QuerySet):
                batch = list(decisions_with_prefetch[offset : offset + batch_size])
            else:
                batch = decisions_with_prefetch[offset : offset + batch_size]

            if not batch:
                break

            offset += batch_size

            for decision in batch:
                try:
                    result = self.classify_decision(decision)
                    stats["total_processed"] += 1

                    if result["is_direct_assignment"]:
                        stats["direct_assignments"] += 1
                    else:
                        stats["non_direct_assignments"] += 1

                    # Check if classification exists
                    if decision.id in existing_classifications:
                        # Update existing (only if update_existing is True)
                        if update_existing:
                            existing = existing_classifications[decision.id]
                            existing.is_direct_assignment = result[
                                "is_direct_assignment"
                            ]
                            existing.detection_method = result["detection_method"]
                            existing.classifier_version = self.CLASSIFIER_VERSION
                            classifications_to_update.append(existing)
                            stats["updated"] += 1
                        # Skip if not updating existing
                    else:
                        # Create new
                        classifications_to_create.append(
                            DecisionClassification(
                                decision=decision,
                                is_direct_assignment=result["is_direct_assignment"],
                                detection_method=result["detection_method"],
                                classifier_version=self.CLASSIFIER_VERSION,
                            )
                        )
                        stats["created"] += 1

                    # Batch save when reaching batch_size
                    if len(classifications_to_create) >= batch_size:
                        DecisionClassification.objects.bulk_create(
                            classifications_to_create,
                            batch_size=batch_size,
                            ignore_conflicts=True,
                        )
                        classifications_to_create = []

                    if len(classifications_to_update) >= batch_size:
                        DecisionClassification.objects.bulk_update(
                            classifications_to_update,
                            [
                                "is_direct_assignment",
                                "detection_method",
                                "classifier_version",
                                "classified_at",
                            ],
                            batch_size=batch_size,
                        )
                        classifications_to_update = []

                except Exception as e:
                    logger.error(f"Error classifying decision {decision.ada}: {e}")
                    stats["errors"] += 1
                    continue

        # Save remaining
        if classifications_to_create:
            DecisionClassification.objects.bulk_create(
                classifications_to_create, batch_size=batch_size, ignore_conflicts=True
            )

        if classifications_to_update:
            DecisionClassification.objects.bulk_update(
                classifications_to_update,
                [
                    "is_direct_assignment",
                    "detection_method",
                    "classifier_version",
                    "classified_at",
                ],
                batch_size=batch_size,
            )

        logger.success(
            f"Bulk classification complete: {stats['total_processed']} processed, "
            f"{stats['direct_assignments']} direct assignments found, "
            f"{stats['created']} created, {stats['updated']} updated, "
            f"{stats['errors']} errors"
        )

        return stats

    # =============================================================================
    # QUERY HELPERS (for finding unclassified decisions)
    # =============================================================================

    def get_unclassified_decisions(self, limit: Optional[int] = None) -> QuerySet:
        """
        Get decisions that haven't been classified yet.

        Uses partial index for efficient querying.
        Orders by most recent first.

        Args:
            limit: Optional limit on number of results

        Returns:
            QuerySet of unclassified Decision objects
        """
        qs = (
            Decision.objects.filter(classification__isnull=True)
            .select_related("decision_type")
            .order_by("-issue_date")
        )

        if limit:
            qs = qs[:limit]

        return qs

    def get_outdated_classifications(self, limit: Optional[int] = None) -> QuerySet:
        """
        Get decisions with outdated classifier version.

        Use this for re-classification when algorithm changes.

        Args:
            limit: Optional limit on number of results

        Returns:
            QuerySet of Decision objects needing reclassification
        """
        qs = (
            Decision.objects.filter(
                Q(classification__classifier_version__lt=self.CLASSIFIER_VERSION)
                | Q(classification__classifier_version__isnull=True)
            )
            .select_related("decision_type", "classification")
            .order_by("-issue_date")
        )

        if limit:
            qs = qs[:limit]

        return qs


# Singleton instance for easy importing
classification_service = DirectAssignmentDetectionService()
