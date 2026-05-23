import re

from core.models.decisions import Decision

from .base import DecompositionResult, DecompositionStrategy


class KeySectionsStrategy(DecompositionStrategy):
    """
    Extract key structured sections from payment decisions.
    Targets: beneficiary, amounts, KA codes, invoice numbers, descriptions.
    """

    @property
    def name(self) -> str:
        return "key_sections_extractor"

    def decompose(self, decision: Decision, text: str) -> DecompositionResult:
        data = {}

        # Extract beneficiary (ΑΦΜ pattern)
        beneficiary_match = re.search(r"με ΑΦΜ\s+(\d{9})", text)
        if beneficiary_match:
            data["afm"] = beneficiary_match.group(1)

        # Extract beneficiary name (before ΑΦΜ)
        name_match = re.search(r":\s*([^:]+?)\s+με ΑΦΜ", text)
        if name_match:
            data["beneficiary"] = name_match.group(1).strip()

        # Extract KA (Κ.Α. εξόδου)
        ka_match = re.search(r"Κ\.Α\.\s+εξόδου[\s\n]+(\d+\.\d+\.\d+)", text)
        if ka_match:
            data["ka_code"] = ka_match.group(1)

        # Extract description (Περιγραφή λογ/μου)
        desc_match = re.search(
            r"Περιγραφή λογ/μου[\s\n]+Ποσό[\s\n]+[\d.]+[\s\n]+([^\d]+?)\s+[\d,]+",
            text,
            re.DOTALL,
        )
        if desc_match:
            data["description"] = desc_match.group(1).strip()

        # Extract total amount (ΣΥΝΟΛΟ)
        total_match = re.search(r"ΣΥΝΟΛΟ\s*:\s*([\d,.]+)", text)
        if total_match:
            amount_str = total_match.group(1).replace(",", ".")
            try:
                data["total_amount"] = float(amount_str)
            except ValueError:
                pass

        # Extract payable amount (Καθαρό Υπόλοιπο Πληρωτέο)
        payable_match = re.search(r"Καθαρό Υπόλοιπο Πληρωτέο\s*:\s*([\d,.]+)", text)
        if payable_match:
            amount_str = payable_match.group(1).replace(",", ".")
            try:
                data["payable_amount"] = float(amount_str)
            except ValueError:
                pass

        # Extract invoice number
        invoice_match = re.search(r"Τιμολόγιο:\s*(\d+/\d+)", text)
        if invoice_match:
            data["invoice_number"] = invoice_match.group(1)

        # Extract payment reason (ΑΙΤΙΑ ΠΛΗΡΩΜΗΣ)
        reason_match = re.search(
            r"ΑΙΤΙΑ ΠΛΗΡΩΜΗΣ[\s\n]+(.+?)(?:Κράτηση|ΣΥΝΟΔΕΥΤΙΚΑ)", text, re.DOTALL
        )
        if reason_match:
            data["payment_reason"] = reason_match.group(1).strip()

        # Success if we extracted at least 3 key fields
        extracted_count = len(data)
        if extracted_count >= 3:
            data["extracted_fields_count"] = extracted_count
            return DecompositionResult(success=True, data=data)
        else:
            return DecompositionResult(
                success=False,
                error=f"Only extracted {extracted_count} fields (need at least 3)",
                data=data,
            )


class ContentFilterStrategy(DecompositionStrategy):
    """
    Identify searchable content vs boilerplate/technical sections.
    Goal: Extract parts worth indexing in OpenSearch.
    """

    @property
    def name(self) -> str:
        return "searchable_content_filter"

    def decompose(self, decision: Decision, text: str) -> DecompositionResult:
        data = {
            "searchable_sections": [],
            "technical_markers_found": [],
            "content_quality": "unknown",
        }

        # Sections worth indexing (high-value content)
        searchable_patterns = [
            (
                r"Περιγραφή λογ/μου[\s\n]+Ποσό[\s\n]+[\d.]+[\s\n]+([^\d]+?)\s+[\d,]+",
                "description",
            ),
            (r"ΑΙΤΙΑ ΠΛΗΡΩΜΗΣ[\s\n]+(.+?)(?:Κράτηση|ΣΥΝΟΔΕΥΤΙΚΑ)", "payment_reason"),
            (r":\s*([^:]+?)\s+με ΑΦΜ", "beneficiary"),
        ]

        for pattern, section_name in searchable_patterns:
            matches = re.finditer(pattern, text, re.DOTALL)
            for match in matches:
                content = match.group(1).strip()
                if len(content) > 10:  # Skip very short matches
                    data["searchable_sections"].append(
                        {
                            "type": section_name,
                            "content": content,
                            "length": len(content),
                        }
                    )

        # Technical/boilerplate markers (low search value)
        technical_patterns = [
            r"Α/Α Έκδοσης",
            r"Σειρά Εντ\.",
            r"Καθαρό Υπόλοιπο Πληρωτέο",
            r"Ministry of Digital Governance",
            r"Digitally signed by",
            r"ΣΥΝΟΔΕΥΤΙΚΑ ΧΡΗΜΑΤΙΚΟΥ ΕΝΤΑΛΜΑΤΟΣ",
        ]

        for pattern in technical_patterns:
            if re.search(pattern, text):
                data["technical_markers_found"].append(pattern)

        # Calculate content quality score
        searchable_chars = sum(s["length"] for s in data["searchable_sections"])
        total_chars = len(text)

        if total_chars > 0:
            quality_ratio = searchable_chars / total_chars
            data["quality_ratio"] = round(quality_ratio, 3)
            data["searchable_chars"] = searchable_chars
            data["total_chars"] = total_chars

            if quality_ratio > 0.3:
                data["content_quality"] = "high"
            elif quality_ratio > 0.1:
                data["content_quality"] = "medium"
            else:
                data["content_quality"] = "low"

        # Combine searchable content
        combined_searchable = " ".join(
            s["content"] for s in data["searchable_sections"]
        )
        data["combined_searchable_text"] = combined_searchable

        # Success if we found any searchable content
        if data["searchable_sections"]:
            return DecompositionResult(success=True, data=data)
        else:
            return DecompositionResult(
                success=False, error="No searchable content sections identified"
            )
