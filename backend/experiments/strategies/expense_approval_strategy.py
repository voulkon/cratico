"""
Strategy for decomposing ΕΓΚΡΙΣΗ ΔΑΠΑΝΗΣ (Expense Approval) decisions.
Extracts structured metadata and high-value semantic content.
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


class BudgetCode(BaseModel):
    """Budget code (ΚΑΕ) with associated data."""

    code: str = Field(..., description="Budget code (e.g., 02.30.15.6041.04)")
    description: Optional[str] = Field(None, description="Human-readable description")
    amount: Optional[float] = Field(None, description="Amount allocated to this code")


class ExpenseApprovalData(BaseModel):
    """Structured data extracted from expense approval documents."""

    # High-value semantic content (for weighted search indexing)
    purpose: Optional[str] = Field(
        None, description="Payment purpose/reason - THE GOLD!"
    )
    beneficiary_name: Optional[str] = Field(None, description="Recipient name")

    # Structured metadata (filterable fields)
    document_id: Optional[str] = Field(None, description="ADA code")
    document_number: Optional[str] = Field(None, description="Payment order number")
    year: Optional[int] = Field(None, description="Fiscal year")
    total_amount: Optional[float] = Field(None, description="Total amount")
    deductions: Optional[float] = Field(None, description="Tax/fee deductions")
    net_amount: Optional[float] = Field(None, description="Net payable amount")

    # Organization info
    organization: Optional[str] = Field(None, description="Municipality (ΔΗΜΟΣ)")
    region: Optional[str] = Field(None, description="Region (ΠΕΡΙΦΕΡΕΙΑ)")
    department: Optional[str] = Field(None, description="Department (ΔΙΕΥΘΥΝΣΗ)")

    # Beneficiary details
    afm: Optional[str] = Field(None, description="Tax ID (ΑΦΜ)")
    doy: Optional[str] = Field(None, description="Tax office (ΔΟΥ)")
    beneficiary_address: Optional[str] = Field(None, description="Address")

    # Budget codes (secondary searchable)
    budget_codes: List[BudgetCode] = Field(default_factory=list)

    # References
    references: List[str] = Field(
        default_factory=list, description="ΑΑΥ, Αρ.Παρ., etc."
    )

    # Funding info
    funding_source: Optional[str] = Field(None, description="Funding source")
    account_type: Optional[str] = Field(
        None, description="Account type (ΤΑΚΤΙΚΑ, etc.)"
    )

    # Date
    date: Optional[str] = Field(None, description="Document date")

    # Quality metrics
    confidence_score: Optional[float] = Field(
        None, description="Extraction confidence (0-1)"
    )


# ============================================================================
# Strategy Implementation
# ============================================================================


class ExpenseApprovalStrategy(DecompositionStrategy):
    """
    Decomposition strategy for ΕΓΚΡΙΣΗ ΔΑΠΑΝΗΣ documents.

    Extracts:
    - High-value semantic content (purpose, beneficiary)
    - Structured metadata (amounts, dates, codes)
    - Organization info
    - Budget codes and references
    """

    # Regex patterns
    PATTERNS = {
        "document_number": r"Αριθμός Εντάλματος[:\s]+([^\n]+)",
        "year": r"Οικονομικό Έτος[:\s]+(\d{4})",
        "total_amount": r"Σύνολο\s+(?:Εντάλματος)?[:\s]+([0-9.,]+)",
        "deductions": r"Κρατήσεις[:\s]+([0-9.,]+)",
        "net_amount": r"Στο(?:ν)?\s+[Δδ]ικαιούχο[:\s]+([0-9.,]+)",
        "afm": r"Α\.?Φ\.?Μ\.?[:\s]+(\d{9})",
        "doy": r"Δ\.?Ο\.?Υ\.?[:\s]+([^\n]+)",
        "ada_code": r":\s*([Α-ΩA-Z0-9]{4}[Α-ΩA-Z]{4}-[Α-ΩA-Z0-9]{3})",
        "budget_code": r"(\d{2}\.\d{2,4}(?:\.\d{2,4}){1,2})",
        "aay": r"Α\.?Α\.?Υ\.?:\s*([^\n]+)",
        "ar_par": r"Αρ\.?Παρ\.?:\s*([^\n]+)",
        "funding": r"Χρηματοδότηση[:\s]+([^\n]+)",
        "account_type": r"(ΤΑΚΤΙΚΑ|ΕΚΤΑΚΤΑ|ΙΔΙΑ ΕΣΟΔΑ)",
        "date": r"(\d{1,2}/\d{1,2}/\d{4})",
    }

    @property
    def name(self) -> str:
        return "expense_approval_decomposer"

    def __init__(self):
        self.compiled_patterns = {
            key: re.compile(pattern, re.IGNORECASE | re.MULTILINE)
            for key, pattern in self.PATTERNS.items()
        }
        self.debug_mode = False  # Set to True for verbose logging

    def decompose(self, decision: Decision, text: str) -> DecompositionResult:
        """
        Decompose expense approval document into structured components.
        """
        ada = getattr(decision, "ada", "UNKNOWN")

        if self.debug_mode:
            logger.info(f"[{ada}] Starting decomposition")

        try:
            # Extract all fields
            data = ExpenseApprovalData(
                # Basic metadata
                document_number=self._extract_single(text, "document_number", ada),
                year=self._extract_year(text, ada),
                total_amount=self._extract_amount(text, "total_amount", ada),
                deductions=self._extract_amount(text, "deductions", ada),
                net_amount=self._extract_amount(text, "net_amount", ada),
                # Identifiers
                afm=self._extract_single(text, "afm", ada),
                doy=self._extract_single(text, "doy", ada),
                document_id=self._extract_ada_code(text, ada),
                # Funding
                funding_source=self._extract_single(text, "funding", ada),
                account_type=self._extract_single(text, "account_type", ada),
                # Organization
                organization=self._extract_organization(text, ada),
                region=self._extract_region(text, ada),
                department=self._extract_department(text, ada),
                # THE GOLD
                purpose=self._extract_purpose(text, ada),
                beneficiary_name=self._extract_beneficiary(text, ada),
                beneficiary_address=self._extract_beneficiary_address(text, ada),
                # Budget codes
                budget_codes=self._extract_budget_codes(text, ada),
                # References
                references=self._extract_references(text, ada),
                # Date
                date=self._extract_date(text, ada),
            )

            # Calculate confidence score
            data.confidence_score = self._calculate_confidence(data)

            if self.debug_mode:
                logger.info(f"[{ada}] Extraction summary:")
                logger.info(
                    f"  Purpose: {data.purpose[:50] if data.purpose else 'NONE'}"
                )
                logger.info(f"  Beneficiary: {data.beneficiary_name or 'NONE'}")
                logger.info(f"  Amount: {data.total_amount or 'NONE'}")
                logger.info(f"  Confidence: {data.confidence_score}")

            # Convert to dict for storage
            result_dict = data.model_dump()

            # Success if we extracted meaningful content
            if data.purpose or data.beneficiary_name or data.total_amount:
                return DecompositionResult(success=True, data=result_dict)
            else:
                error_msg = "No key content extracted (purpose, beneficiary, or amount)"
                if self.debug_mode:
                    logger.warning(f"[{ada}] {error_msg}")
                return DecompositionResult(
                    success=False, error=error_msg, data=result_dict
                )

        except Exception as e:
            error_msg = f"Extraction failed: {str(e)}"
            logger.exception(f"[{ada}] {error_msg}")
            return DecompositionResult(success=False, error=error_msg)

    # ========================================================================
    # Extraction Methods
    # ========================================================================

    def _extract_single(
        self, text: str, pattern_key: str, ada: str = "UNKNOWN"
    ) -> Optional[str]:
        """Extract a single value using a regex pattern."""
        match = self.compiled_patterns[pattern_key].search(text)
        if match:
            value = match.group(1).strip()
            if self.debug_mode:
                logger.debug(
                    f"[{ada}] {pattern_key}: {value[:50] if value else 'EMPTY'}"
                )
            return value if value else None
        if self.debug_mode:
            logger.debug(f"[{ada}] {pattern_key}: NOT FOUND")
        return None

    def _extract_year(self, text: str, ada: str = "UNKNOWN") -> Optional[int]:
        """Extract year as integer."""
        year_str = self._extract_single(text, "year", ada)
        if year_str:
            try:
                return int(year_str)
            except ValueError:
                pass
        return None

    def _extract_amount(
        self, text: str, pattern_key: str, ada: str = "UNKNOWN"
    ) -> Optional[float]:
        """Extract monetary amount and convert to float."""
        amount_str = self._extract_single(text, pattern_key, ada)
        if amount_str:
            # Remove thousand separators and convert comma to dot
            amount_str = amount_str.replace(".", "").replace(",", ".")
            try:
                return float(amount_str)
            except ValueError:
                if self.debug_mode:
                    logger.warning(
                        f"[{ada}] Failed to parse {pattern_key}: {amount_str}"
                    )
        return None

    def _extract_ada_code(self, text: str, ada: str = "UNKNOWN") -> Optional[str]:
        """Extract ADA code (document ID)."""
        match = self.compiled_patterns["ada_code"].search(text)
        if match:
            code = match.group(1)
            if self.debug_mode:
                logger.debug(f"[{ada}] ADA code: {code}")
            return code
        return None

    def _extract_organization(self, text: str, ada: str = "UNKNOWN") -> Optional[str]:
        """Extract organization name (ΔΗΜΟΣ)."""
        header = text[:300]
        match = re.search(r"ΔΗΜΟΣ\s+([^\n]+)", header, re.IGNORECASE)
        if match:
            org = match.group(1).strip()
            org = re.sub(r"\s+Α\.?Φ\.?Μ\.?.*", "", org)
            if self.debug_mode:
                logger.debug(f"[{ada}] Organization: {org}")
            return org
        return None

    def _extract_region(self, text: str, ada: str = "UNKNOWN") -> Optional[str]:
        """Extract region name (ΠΕΡΙΦΕΡΕΙΑ)."""
        header = text[:300]
        match = re.search(
            r"(ΠΕΡΙΦΕΡΕΙΑ[^\n]+|[^\n]+ΜΑΚΕΔΟΝΙΑΣ|[^\n]+ΗΠΕΙΡΟΥ|[^\n]+ΘΕΣΣΑΛΙΑΣ)",
            header,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()
        return None

    def _extract_department(self, text: str, ada: str = "UNKNOWN") -> Optional[str]:
        """Extract department name (ΔΙΕΥΘΥΝΣΗ)."""
        header = text[:300]
        match = re.search(r"ΔΙΕΥΘΥΝΣΗ[:\s]+([^\n]+)", header, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    def _extract_purpose(self, text: str, ada: str = "UNKNOWN") -> Optional[str]:
        """
        Extract the purpose/reason - THE GOLD!
        This is the most important field for semantic search.
        """
        if self.debug_mode:
            logger.debug(f"[{ada}] Attempting purpose extraction...")

        # Strategy 1: Look for text between "ΕΝΤΕΛΛΟΜΕΝΟ ΠΟΣΟ" and budget codes
        # This works for documents where purpose is in a labeled section
        match = re.search(
            r"ΕΝΤΕΛΛΟΜΕΝΟ ΠΟΣΟ[\s\n]+(.+?)(?:Ταμειακή|Χρηματοδότηση|A/A\s+ΚΑ|Κωδικός|\d{2}\.\d{2})",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if match:
            purpose = self._clean_purpose(match.group(1).strip())
            if purpose and len(purpose) > 15:
                if self.debug_mode:
                    logger.debug(f"[{ada}] Purpose (ΕΝΤΕΛΛΟΜΕΝΟ): {purpose[:80]}")
                return purpose

        # Strategy 2: Look for explicit "ΑΙΤΙΑ ΠΛΗΡΩΜΗΣ" section (but skip if followed immediately by refs)
        match = re.search(
            r"ΑΙΤΙΑ ΠΛΗΡΩΜΗΣ[:\s]*\n+(.+?)(?:\n\s*[Α-Ω]+\s+[Α-Ω]+\s+(?:του|ΤΟΥ)|Κωδικός|Δ\.Ο\.Υ\.|Α\.Φ\.Μ\.|ΤΗΛ:|Αρ\.Παρ\.|Α\.Α\.Υ\.)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if match:
            purpose = self._clean_purpose(match.group(1).strip())
            # Only use if it's substantial (not just a reference number)
            if (
                purpose
                and len(purpose) > 20
                and not re.match(r"^[\d\s\-/()]+$", purpose)
            ):
                if self.debug_mode:
                    logger.debug(f"[{ada}] Purpose (ΑΙΤΙΑ): {purpose[:80]}")
                return purpose

        # Strategy 3: Look for descriptive phrases after amounts
        match = re.search(
            r"(?:πληρώσατε|ΠΛΗΡΩΜΗΣ)[^\n]*\n+(.+?)(?:\n\s*\n|[Α-Ω]{3,}\s+[Α-Ω]{3,})",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if match:
            purpose = self._clean_purpose(match.group(1).strip())
            if purpose and len(purpose) > 25:
                if self.debug_mode:
                    logger.debug(f"[{ada}] Purpose (after πληρώσατε): {purpose[:80]}")
                return purpose

        # Strategy 4: Look for budget code descriptions
        budget_codes = self._extract_budget_codes(text, ada)
        if budget_codes:
            descriptions = [
                bc.description
                for bc in budget_codes
                if bc.description and len(bc.description) > 20
            ]
            if descriptions:
                if self.debug_mode:
                    logger.debug(
                        f"[{ada}] Purpose (budget desc): {descriptions[0][:80]}"
                    )
                return descriptions[0]

        if self.debug_mode:
            logger.warning(f"[{ada}] Purpose: NOT FOUND")
        return None

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

    def _extract_beneficiary(self, text: str, ada: str = "UNKNOWN") -> Optional[str]:
        """Extract beneficiary name."""
        if self.debug_mode:
            logger.debug(f"[{ada}] Attempting beneficiary extraction...")

        # Strategy 1: Look near "Στον Δικαιούχο" or "Δικαιούχο"
        match = re.search(
            r"(?:Στον\s+)?[Δδ]ικαιούχο[:\s]*[^\n]*\n+([Α-ΩΆ-ΏA-Z][^\n]+?)(?:\n|Α\.Φ\.Μ|ΑΙΑΝΗ|ΘΟΥΚΙΔΙΔΗ|ΜΑΚΡΥ|ΚΟΖΑΝΗ)",
            text,
            re.IGNORECASE,
        )
        if match:
            name = match.group(1).strip()
            # Clean up
            name = re.sub(r"\s*Α\.?Φ\.?Μ\.?.*", "", name)
            name = re.sub(r"\s*\d{9}.*", "", name)
            name = re.sub(r"\s*Σύνολο.*", "", name)
            name = re.sub(r"\s*Κρατήσεις.*", "", name)
            name = re.sub(r"\s*\d+[.,]\d+.*", "", name)
            if len(name) > 5:
                if self.debug_mode:
                    logger.debug(f"[{ada}] Beneficiary (near Δικαιούχο): {name}")
                return name

        # Strategy 2: Look for name in signature section
        match = re.search(
            r"υπογεγραμμένος\s+([Α-ΩΆ-ΏA-Z][^\n]+?)(?:\s+με\s+Α\.Δ\.Τ|ΚΛΠ)",
            text,
            re.IGNORECASE,
        )
        if match:
            name = match.group(1).strip()
            if len(name) > 5:
                if self.debug_mode:
                    logger.debug(f"[{ada}] Beneficiary (signature): {name}")
                return name

        if self.debug_mode:
            logger.warning(f"[{ada}] Beneficiary: NOT FOUND")
        return None

    def _extract_beneficiary_address(
        self, text: str, ada: str = "UNKNOWN"
    ) -> Optional[str]:
        """Extract beneficiary address."""
        match = re.search(
            r"(?:Δικαιούχο|beneficiary)[^\n]*\n[^\n]+\n([Α-ΩΆ-Ώ\s\d]+(?:ΚΟΖΑΝΗΣ|ΙΩΑΝΝΙΝΑ|ΑΘΗΝΑ|ΛΑΡΙΣΑ)[^\n]*)",
            text,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()
        return None

    def _extract_budget_codes(
        self, text: str, ada: str = "UNKNOWN"
    ) -> List[BudgetCode]:
        """Extract budget codes (ΚΑΕ) with amounts and descriptions."""
        codes = []

        # Look for budget code sections
        sections = re.finditer(
            r"(\d{2}\.\d{2,4}(?:\.\d{2,4}){1,2})\s*([^\n]*?)\s*([0-9.,]+)",
            text,
            re.MULTILINE,
        )

        for match in sections:
            code = match.group(1)
            description = match.group(2).strip()
            amount_str = match.group(3)

            # Parse amount
            amount = None
            try:
                amount = float(amount_str.replace(".", "").replace(",", "."))
            except ValueError:
                pass

            # Clean description
            description = re.sub(r"^\d+\s+", "", description)
            description = description.strip() or None

            codes.append(BudgetCode(code=code, description=description, amount=amount))

        if self.debug_mode and codes:
            logger.debug(f"[{ada}] Found {len(codes)} budget codes")

        return codes

    def _extract_references(self, text: str, ada: str = "UNKNOWN") -> List[str]:
        """Extract reference numbers (ΑΑΥ, Αρ.Παρ., etc.)."""
        refs = []

        # Extract AAY references
        for match in self.compiled_patterns["aay"].finditer(text):
            ref = match.group(1).strip()
            if ref:
                refs.append(f"ΑΑΥ: {ref}")

        # Extract Ar.Par references
        for match in self.compiled_patterns["ar_par"].finditer(text):
            ref = match.group(1).strip()
            if ref:
                refs.append(f"Αρ.Παρ.: {ref}")

        return refs

    def _extract_date(self, text: str, ada: str = "UNKNOWN") -> Optional[str]:
        """Extract document date."""
        dates = self.compiled_patterns["date"].findall(text)
        if dates:
            # Return the last date found (usually signature date)
            return dates[-1]
        return None

    def _calculate_confidence(self, data: ExpenseApprovalData) -> float:
        """Calculate extraction confidence score (0-1)."""
        score = 0.0
        max_score = 0.0

        # Critical fields (higher weight)
        critical_fields = [
            ("purpose", 0.25),
            ("beneficiary_name", 0.20),
            ("total_amount", 0.15),
            ("document_id", 0.10),
        ]

        # Important fields (medium weight)
        important_fields = [
            ("afm", 0.05),
            ("doy", 0.05),
            ("organization", 0.05),
        ]

        # Secondary fields (lower weight)
        secondary_fields = [
            ("year", 0.03),
            ("net_amount", 0.03),
            ("funding_source", 0.02),
            ("date", 0.02),
            ("budget_codes", 0.05),
        ]

        # Score critical fields
        for field, weight in critical_fields:
            max_score += weight
            value = getattr(data, field)
            if value:
                if isinstance(value, list):
                    if len(value) > 0:
                        score += weight
                else:
                    score += weight

        # Score important fields
        for field, weight in important_fields:
            max_score += weight
            value = getattr(data, field)
            if value:
                score += weight

        # Score secondary fields
        for field, weight in secondary_fields:
            max_score += weight
            value = getattr(data, field)
            if value:
                if isinstance(value, list):
                    if len(value) > 0:
                        score += weight
                else:
                    score += weight

        return round(score / max_score if max_score > 0 else 0.0, 3)
