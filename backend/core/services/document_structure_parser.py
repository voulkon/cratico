import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from loguru import logger


class ParseStatus(Enum):
    SUCCESS = "success"
    FAILED_HEADER = "failed_header"
    FAILED_SUBSTANCE = "failed_substance"
    FAILED_FOOTER = "failed_footer"
    MALFORMED = "malformed"


@dataclass
class DocumentStructure:
    header: Optional[str] = None
    substance: Optional[str] = None
    footer: Optional[str] = None
    parse_status: ParseStatus = ParseStatus.MALFORMED
    confidence_score: float = 0.0
    error_reason: Optional[str] = None
    matched_patterns: List[str] = field(default_factory=list)


class GreekGovernmentDocumentParser:
    """Rule-based parser for Greek government decision documents"""

    def __init__(self):
        self.rules_version = "1.0"
        self.debug_mode = True
        self.failed_samples_dir = Path("debug_samples")
        self.failed_samples_dir.mkdir(exist_ok=True)

        # Initialize parsing patterns
        self._init_patterns()

    def _init_patterns(self):
        """Initialize regex patterns for document sections"""
        # Substance start patterns - based on your example
        self.substance_start_patterns = [
            r"ΑΠΟΦΑΣΙΖΟΥΜΕ\s*\n",  # The main decision verb
            r"ΑΠΟΦΑΣΙΖΩ\s*\n",
            r"ΕΓΚΡΙΝΟΥΜΕ\s*\n",
            r"ΕΓΚΡΙΝΩ\s*\n",
            r"ΔΙΑΤΑΓΩ\s*\n",
            r"ΑΠΟΦΑΣΗ\s*\n\s*Έχοντας\s+υπόψη",  # Decision with "Having in mind"
            r"Α\s*Π\s*Ο\s*Φ\s*Α\s*Σ\s*Η\s*\n\s*Έχοντας\s+υπόψη",  # Spaced out ΑΠΟΦΑΣΗ
        ]

        # Footer patterns - signatures and administrative info
        self.footer_patterns = [
            r"Ο\s+(?:ΥΠΟΥΡΓΟΣ|ΓΕΝΙΚΟΣ\s+ΓΡΑΜΜΑΤΕΑΣ|ΔΙΕΥΘΥΝΤΗΣ|ΠΡΟΪΣΤΑΜΕΝΟΣ)",
            r"Η\s+(?:ΥΠΟΥΡΓΟΣ|ΓΕΝΙΚΗ\s+ΓΡΑΜΜΑΤΕΑΣ|ΔΙΕΥΘΥΝΤΡΙΑ|ΠΡΟΪΣΤΑΜΕΝΗ)",
            r"(?:Συντάκτης|Τμηματάρχης|Διευθυντής)\s*\n",
            r"ΚΟΙΝΟΠΟΙΗΣΗ\s*\n",
            r"ΑΔΑ:\s*[A-Z0-9Α-Ω-]+\s*\n",  # Administrative Decision Number
            r"Ministry\s+of\s+Digital\s+Governance",  # Digital signature
            r"Digitally\s+signed\s+by",
        ]

    def _normalize_whitespace(self, text: str) -> str:
        """Normalize excessive whitespace while preserving structure"""
        # Replace multiple consecutive whitespace chars with single space
        # But preserve line breaks for structure
        lines = text.split("\n")
        normalized_lines = []

        for line in lines:
            # Remove excessive spaces within lines but keep the line
            normalized_line = re.sub(r"\s+", " ", line.strip())
            normalized_lines.append(normalized_line)

        # Remove empty lines but keep some structure
        filtered_lines = []
        prev_empty = False

        for line in normalized_lines:
            if line:  # Non-empty line
                filtered_lines.append(line)
                prev_empty = False
            elif not prev_empty:  # Empty line, but previous wasn't empty
                filtered_lines.append("")  # Keep one empty line
                prev_empty = True

        return "\n".join(filtered_lines)

    def parse_document(self, text: str, ada: str = None) -> DocumentStructure:
        """Parse a document into its structural components"""
        if not text or len(text.strip()) < 50:
            return DocumentStructure(
                parse_status=ParseStatus.MALFORMED,
                error_reason="Document too short or empty",
            )

        # Normalize whitespace first
        normalized_text = self._normalize_whitespace(text)

        result = DocumentStructure()
        result.matched_patterns = []

        try:
            # Step 1: Try to identify substance start
            substance_start, matched_pattern = self._find_substance_start(
                normalized_text
            )
            if substance_start == -1:
                result.parse_status = ParseStatus.FAILED_SUBSTANCE
                result.error_reason = "Could not identify substance start"
                self._save_failed_sample(normalized_text, ada, result)
                return result

            result.matched_patterns.append(f"substance_start_found:{matched_pattern}")

            # Step 2: Try to identify footer start
            footer_start, footer_pattern = self._find_footer_start(
                normalized_text, substance_start
            )

            # Step 3: Extract sections
            result.header = normalized_text[:substance_start].strip()

            if footer_start != -1:
                result.substance = normalized_text[substance_start:footer_start].strip()
                result.footer = normalized_text[footer_start:].strip()
                result.matched_patterns.append(f"footer_found:{footer_pattern}")
            else:
                # If no footer found, substance goes to end
                result.substance = normalized_text[substance_start:].strip()
                result.matched_patterns.append("no_footer_pattern")

            # Step 4: Validate extraction quality
            result.confidence_score = self._calculate_confidence(result)

            if result.confidence_score > 0.6:  # Lowered threshold for initial testing
                result.parse_status = ParseStatus.SUCCESS
            else:
                result.parse_status = ParseStatus.FAILED_SUBSTANCE
                result.error_reason = f"Low confidence: {result.confidence_score:.2f}"
                self._save_failed_sample(normalized_text, ada, result)

            return result

        except Exception as e:
            logger.error(f"Error parsing document {ada}: {str(e)}")
            result.parse_status = ParseStatus.MALFORMED
            result.error_reason = str(e)
            self._save_failed_sample(normalized_text, ada, result)
            return result

    def _find_substance_start(self, text: str) -> Tuple[int, str]:
        """Find where the main substance begins"""
        for i, pattern in enumerate(self.substance_start_patterns):
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                return match.start(), f"pattern_{i}"

        # Fallback: look for common decision content indicators
        fallback_patterns = [
            r"Εγκρίνουμε\s+τη\s+δέσμευση",  # "We approve the commitment" - from your example
            r"Εγκρίνω\s+τη\s+δέσμευση",
            r"Εγκρίνουμε\s+την?\s+",
            r"ΘΕΜΑ:\s*[Α-ΩΆΈΉΊΌΎΏ]",  # Subject line
        ]

        for i, pattern in enumerate(fallback_patterns):
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                return match.start(), f"fallback_{i}"

        return -1, "none"

    def _find_footer_start(self, text: str, substance_start: int) -> Tuple[int, str]:
        """Find where the footer begins"""
        # Look for footer patterns after substance start
        search_text = text[substance_start:]

        for i, pattern in enumerate(self.footer_patterns):
            match = re.search(pattern, search_text, re.IGNORECASE | re.MULTILINE)
            if match:
                return substance_start + match.start(), f"pattern_{i}"

        return -1, "none"

    def _calculate_confidence(self, result: DocumentStructure) -> float:
        """Calculate confidence score for the parsing result"""
        score = 0.0

        # Basic structure checks
        if (
            result.header and len(result.header) > 50
        ):  # Header should have ministry info
            score += 0.25

        if (
            result.substance and len(result.substance) > 100
        ):  # Substance should be substantial
            score += 0.5

            # Check if substance contains decision-like content
            if re.search(
                r"εγκρίνουμε|εγκρίνω|αποφασίζουμε|αποφασίζω",
                result.substance,
                re.IGNORECASE,
            ):
                score += 0.15

        if result.footer and len(result.footer) > 20:
            score += 0.1

        # Pattern matching bonus
        if any("substance_start_found" in p for p in result.matched_patterns):
            score += 0.1

        if any("footer_found" in p for p in result.matched_patterns):
            score += 0.05

        return min(score, 1.0)

    def _save_failed_sample(self, text: str, ada: str, result: DocumentStructure):
        """Save failed parsing samples for analysis"""
        if not self.debug_mode:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = (
            f"failed_{result.parse_status.value}_{ada or 'unknown'}_{timestamp}.json"
        )

        # Create sections for analysis
        sections_analysis = self._analyze_document_sections(text)

        sample_data = {
            "ada": ada,
            "timestamp": timestamp,
            "parse_status": result.parse_status.value,
            "error_reason": result.error_reason,
            "matched_patterns": result.matched_patterns,
            "confidence_score": result.confidence_score,
            "text_length": len(text),
            "sections_analysis": sections_analysis,
            "text_preview": text[:800] + "..." if len(text) > 800 else text,
            "full_text": text,
            "rules_version": self.rules_version,
        }

        sample_file = self.failed_samples_dir / filename
        with open(sample_file, "w", encoding="utf-8") as f:
            json.dump(sample_data, f, ensure_ascii=False, indent=2)

        logger.debug(f"Saved failed sample: {sample_file}")

    def _analyze_document_sections(self, text: str) -> Dict:
        """Analyze document to help identify patterns"""
        lines = text.split("\n")

        return {
            "total_lines": len(lines),
            "first_10_lines": lines[:10],
            "last_10_lines": lines[-10:],
            "lines_with_caps": [
                i for i, line in enumerate(lines) if line.isupper() and len(line) > 5
            ],
            "potential_decisions": [
                i
                for i, line in enumerate(lines)
                if re.search(r"αποφασ|εγκριν|διαταγ", line, re.IGNORECASE)
            ],
            "potential_signatures": [
                i
                for i, line in enumerate(lines)
                if re.search(r"υπουργ|γραμματε|διευθυντ", line, re.IGNORECASE)
            ],
            "ada_mentions": [
                i
                for i, line in enumerate(lines)
                if re.search(r"αδα:", line, re.IGNORECASE)
            ],
        }
