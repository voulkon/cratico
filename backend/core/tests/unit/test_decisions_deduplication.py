from datetime import date
from unittest.mock import MagicMock

from core.services.decision_ingestion_service import DecisionIngestionService
from core.tests.utils import create_decision_dto as create_decision


def test_deduplication_across_increments():
    # Create two overlapping decision sets with same ADAs
    decisions1 = [create_decision(f"ada{i}") for i in range(10)]
    decisions2 = [create_decision(f"ada{i}") for i in range(5, 15)]  # Overlap from 5-9

    service = DecisionIngestionService(MagicMock())

    # Mock the internal method
    service._fetch_for_single_increment = MagicMock()
    service._fetch_for_single_increment.side_effect = [decisions1, decisions2]

    # Call the method
    results = service.fetch_decisions_for_period(
        date(2024, 1, 1), date(2024, 1, 10), date_increment_days=5
    )

    # Should have 15 unique decisions (0-14)
    assert len(results) == 15
    adas = sorted([d.ada for d in results])
    assert adas == sorted([f"ada{i}" for i in range(15)])
