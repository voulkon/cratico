import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from core.models.document_analysis import DocumentExtraction, ProcessingStatus
from django.db.models.functions import Length
from loguru import logger

from .document_structure_parser import GreekGovernmentDocumentParser, ParseStatus


@dataclass
class TestResult:
    total_documents: int
    successful_parses: int
    failed_parses: int
    success_rate: float
    failure_breakdown: Dict[str, int]
    processing_time_ms: int


class DocumentParserTester:
    """Service to test and validate document parsing rules"""

    def __init__(self):
        self.parser = GreekGovernmentDocumentParser()
        self.results_dir = Path("doc_parsing_test_results")
        self.results_dir.mkdir(exist_ok=True)

    def test_parsing_rules(
        self,
        limit: Optional[int] = None,
        sample_ada_list: Optional[List[str]] = None,
        min_text_length: int = 100,
    ) -> TestResult:
        """Test parsing rules against a sample of documents"""

        # Build query - fix the length filter
        query = (
            DocumentExtraction.objects.filter(
                extraction_status=ProcessingStatus.COMPLETED, raw_text__isnull=False
            )
            .exclude(raw_text__exact="")
            .annotate(text_length=Length("raw_text"))
            .filter(text_length__gte=min_text_length)
        )

        if sample_ada_list:
            query = query.filter(decision__ada__in=sample_ada_list)

        if limit:
            query = query[:limit]

        # Process documents
        results = []
        failure_counts = {}

        logger.info(f"Testing parsing rules on {query.count()} documents...")

        start_time = time.time()

        for extraction in query:
            parse_result = self.parser.parse_document(
                extraction.raw_text, extraction.decision.ada
            )

            results.append(
                {
                    "ada": extraction.decision.ada,
                    "status": parse_result.parse_status.value,
                    "confidence": parse_result.confidence_score,
                    "error_reason": parse_result.error_reason,
                    "text_length": len(extraction.raw_text),
                    "substance_length": (
                        len(parse_result.substance) if parse_result.substance else 0
                    ),
                }
            )

            # Count failures by type
            if parse_result.parse_status != ParseStatus.SUCCESS:
                failure_type = parse_result.parse_status.value
                failure_counts[failure_type] = failure_counts.get(failure_type, 0) + 1

        processing_time = int((time.time() - start_time) * 1000)

        # Calculate metrics
        total = len(results)
        successful = sum(1 for r in results if r["status"] == "success")
        failed = total - successful
        success_rate = (successful / total * 100) if total > 0 else 0

        test_result = TestResult(
            total_documents=total,
            successful_parses=successful,
            failed_parses=failed,
            success_rate=success_rate,
            failure_breakdown=failure_counts,
            processing_time_ms=processing_time,
        )

        # Save detailed results
        self._save_test_results(test_result, results)

        logger.info(f"Parsing test completed: {success_rate:.1f}% success rate")
        return test_result

    def _save_test_results(self, test_result: TestResult, detailed_results: List[Dict]):
        """Save test results to files"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Summary file
        summary_file = self.results_dir / f"test_summary_{timestamp}.json"
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "summary": test_result.__dict__,
                    "rules_version": self.parser.rules_version,
                    "timestamp": timestamp,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

        # Detailed results
        details_file = self.results_dir / f"test_details_{timestamp}.json"
        with open(details_file, "w", encoding="utf-8") as f:
            json.dump(detailed_results, f, ensure_ascii=False, indent=2)

        logger.info(f"Test results saved: {summary_file}")
