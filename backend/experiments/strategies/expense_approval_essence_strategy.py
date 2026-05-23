"""
ESSENCE-ONLY Strategy for ΕΓΚΡΙΣΗ ΔΑΠΑΝΗΣ.

Extracts ONLY the semantic content NOT available from the API:
- Purpose/reason (the key searchable content)
- Budget code descriptions (if useful for search)

Skips redundant fields that come from the API:
- document_id (ADA) [FAIL] Already have it
- organization [FAIL] Already in Decision.organization
- afm [FAIL] Already tracked via entities
- amounts [FAIL] Already in Decision.amount
- dates [FAIL] Already in Decision.issue_date
- references [FAIL] Not useful for search

This is the LEAN version focused purely on adding search value.
"""

import re
from typing import List, Optional

from core.models.decisions import Decision
from loguru import logger
from pydantic import BaseModel, Field

from .base import DecompositionResult, DecompositionStrategy

# ============================================================================
# Pydantic Schemas
# ============================================================================


class BudgetCodeEssence(BaseModel):
    """Just the searchable part of budget codes."""

    code: str
    description: Optional[str] = None  # The human-readable part we care about


class ExpenseApprovalEssence(BaseModel):
    """
    ESSENCE ONLY - Just what we can't get from the API.

    This is what we'll index in OpenSearch for semantic search.
    """

    # THE GOLD - The only thing we really need
    purpose: Optional[str] = Field(
        None, description="Payment purpose/reason - THE semantic content for search!"
    )

    # OPTIONAL - Only if useful for enriching search
    budget_descriptions: List[str] = Field(
        default_factory=list, description="Human-readable budget code descriptions"
    )

    # Quality metric
    confidence_score: Optional[float] = Field(
        None, description="Extraction confidence (0-1)"
    )


# ============================================================================
# Strategy Implementation
# ============================================================================


class ExpenseApprovalEssenceStrategy(DecompositionStrategy):
    """
    LEAN decomposition strategy - extracts ONLY the essence.

    Philosophy: Don't waste compute on extracting what we already have.
    Focus on the ONE thing that matters: semantic search content.
    """

    @property
    def name(self) -> str:
        return "expense_approval_essence"

    def __init__(self):
        self.debug_mode = False

    def decompose(self, decision: Decision, text: str) -> DecompositionResult:
        """Extract ONLY the essence - the searchable semantic content."""
        ada = getattr(decision, "ada", "UNKNOWN")

        if self.debug_mode:
            logger.info(f"[{ada}] Extracting ESSENCE ONLY")

        try:
            # Extract THE GOLD
            purpose = self._extract_purpose(text, ada)

            # Optional: Extract budget descriptions if they add search value
            budget_descriptions = self._extract_budget_descriptions(text, ada)

            # Calculate confidence
            confidence = self._calculate_confidence(purpose, budget_descriptions)

            data = ExpenseApprovalEssence(
                purpose=purpose,
                budget_descriptions=budget_descriptions,
                confidence_score=confidence,
            )

            if self.debug_mode:
                logger.info(f"[{ada}] Purpose: {purpose[:80] if purpose else 'NONE'}")
                logger.info(f"[{ada}] Budget descriptions: {len(budget_descriptions)}")
                logger.info(f"[{ada}] Confidence: {confidence}")

            result_dict = data.model_dump()

            # Success if we got the purpose (the critical piece)
            if purpose:
                return DecompositionResult(success=True, data=result_dict)
            else:
                return DecompositionResult(
                    success=False,
                    error="No purpose extracted (the one field we actually need)",
                    data=result_dict,
                )

        except Exception as e:
            error_msg = f"Extraction failed: {str(e)}"
            logger.exception(f"[{ada}] {error_msg}")
            return DecompositionResult(success=False, error=error_msg)

    def _extract_purpose(self, text: str, ada: str = "UNKNOWN") -> Optional[str]:
        """
        Extract the purpose - THE ONLY THING THAT MATTERS.
        This is what makes documents searchable beyond just metadata.
        """
        if self.debug_mode:
            logger.debug(f"[{ada}] Extracting purpose...")

        # Strategy 1: ΕΝΤΕΛΛΟΜΕΝΟ ΠΟΣΟ section (most reliable)
        match = re.search(
            r"ΕΝΤΕΛΛΟΜΕΝΟ ΠΟΣΟ[\s\n]+(.+?)(?:Ταμειακή|Χρηματοδότηση|A/A\s+ΚΑ|Κωδικός|\d{2}\.\d{2})",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if match:
            purpose = self._clean_purpose(match.group(1).strip())
            if purpose and len(purpose) > 15:
                if self.debug_mode:
                    logger.debug(f"[{ada}] Found (ΕΝΤΕΛΛΟΜΕΝΟ): {purpose[:80]}")
                return purpose

        # Strategy 2: ΑΙΤΙΑ ΠΛΗΡΩΜΗΣ section
        match = re.search(
            r"ΑΙΤΙΑ ΠΛΗΡΩΜΗΣ[:\s]*\n+(.+?)(?:\n\s*[Α-Ω]+\s+[Α-Ω]+\s+(?:του|ΤΟΥ)|Κωδικός|Δ\.Ο\.Υ\.|Α\.Φ\.Μ\.|ΤΗΛ:|Αρ\.Παρ\.|Α\.Α\.Υ\.)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if match:
            purpose = self._clean_purpose(match.group(1).strip())
            # Only use if substantial (not just reference numbers)
            if (
                purpose
                and len(purpose) > 20
                and not re.match(r"^[\d\s\-/()]+$", purpose)
            ):
                if self.debug_mode:
                    logger.debug(f"[{ada}] Found (ΑΙΤΙΑ): {purpose[:80]}")
                return purpose

        # Strategy 3: After "πληρώσατε" phrase
        match = re.search(
            r"(?:πληρώσατε|ΠΛΗΡΩΜΗΣ)[^\n]*\n+(.+?)(?:\n\s*\n|[Α-Ω]{3,}\s+[Α-Ω]{3,})",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if match:
            purpose = self._clean_purpose(match.group(1).strip())
            if purpose and len(purpose) > 25:
                if self.debug_mode:
                    logger.debug(f"[{ada}] Found (after πληρώσατε): {purpose[:80]}")
                return purpose

        # Strategy 4: Extract from budget code descriptions (last resort)
        descriptions = self._extract_budget_descriptions(text, ada)
        if descriptions:
            # Use the longest, most descriptive one
            best = max(descriptions, key=len) if descriptions else None
            if best and len(best) > 20:
                if self.debug_mode:
                    logger.debug(f"[{ada}] Found (budget desc): {best[:80]}")
                return best

        if self.debug_mode:
            logger.warning(f"[{ada}] NO PURPOSE FOUND")
        return None

    def _extract_budget_descriptions(
        self, text: str, ada: str = "UNKNOWN"
    ) -> List[str]:
        """Extract human-readable budget code descriptions."""
        descriptions = []

        # Match budget codes with descriptions
        # Pattern: KA code, then text, then amount
        pattern = r"\d{2}\.\d{2,4}(?:\.\d{2,4}){1,2}\s+([^\d\n]{20,}?)\s+[\d.,]+"

        for match in re.finditer(pattern, text, re.MULTILINE):
            desc = match.group(1).strip()
            # Clean it up
            desc = re.sub(r"^\d+\s+", "", desc)  # Remove leading numbers
            desc = re.sub(r"\s+", " ", desc)  # Normalize whitespace
            desc = desc.strip()

            # Only keep substantial descriptions
            if len(desc) > 20 and not re.match(r"^[\d\s\-/()]+$", desc):
                descriptions.append(desc)

        if self.debug_mode and descriptions:
            logger.debug(f"[{ada}] Found {len(descriptions)} budget descriptions")

        return descriptions

    def _clean_purpose(self, text: str) -> str:
        """Clean up extracted purpose text."""
        # Remove excessive whitespace
        text = re.sub(r"\s+", " ", text)

        # Remove numbers at start (from lists)
        text = re.sub(r"^\d+\.?\s*", "", text)

        # Remove common boilerplate
        text = re.sub(r"Πληρ\.\s*Κρατ\.\s*Συν\.", "", text, re.IGNORECASE)
        text = re.sub(r"ΠΟΣΟ", "", text, re.IGNORECASE)
        text = re.sub(r"\d+[.,]\d{2}\s*€?", "", text)  # Remove amounts

        # Trim
        text = text.strip(" :-\n")

        return text

    def _calculate_confidence(
        self, purpose: Optional[str], budget_descriptions: List[str]
    ) -> float:
        """Calculate extraction confidence (0-1)."""
        score = 0.0

        # Purpose is THE critical field
        if purpose:
            # Score based on length/quality
            if len(purpose) > 50:
                score = 1.0
            elif len(purpose) > 30:
                score = 0.8
            elif len(purpose) > 15:
                score = 0.6
            else:
                score = 0.4

        # Budget descriptions add a small bonus
        if budget_descriptions:
            score = min(1.0, score + 0.1)

        return round(score, 3)
