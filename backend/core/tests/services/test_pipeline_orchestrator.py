import pytest
from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.models.decision_health import HealthStatus
from core.models.decisions import Decision
from core.services.pipeline_orchestrator import DecisionPipelineOrchestrator

# ════════════════════════════════════════════════════════════════════════════
# PROBLEMATIC DECISION ADAs - Add more as you discover them
# ════════════════════════════════════════════════════════════════════════════
PROBLEMATIC_DECISION_ADAS = [
    "Ε46Υ469Β7Λ-ΑΝΡ",  # Failed: value too long for varchar(255) - 2026-01-31
    "95ΖΩ469Β7Λ-ΗΡΙ",  # Failed: value too long for varchar(255) - 2026-01-31
    # Add more problematic ADAs here as you discover them
]


@pytest.fixture
def orchestrator():
    """Provide a fresh orchestrator instance for each test."""
    return DecisionPipelineOrchestrator()


@pytest.fixture
def fetcher():
    """Provide a DiavgeiaFetcher instance for fetching real decisions."""
    return DiavgeiaFetcher()


@pytest.mark.django_db
class TestPipelineOrchestratorLongFields:
    """
    Tests for decisions with field values exceeding database limits (varchar 255).

    WORKFLOW:
    1. Run tests to reproduce the error and identify problematic fields
    2. Use debugger to develop your fix (truncation or field widening)
    3. After implementing fix, tests should pass

    Uses VCR to record/replay API responses (cassettes in fixtures/vcr_cassettes/).
    """

    @pytest.mark.vcr()
    @pytest.mark.parametrize("ada", PROBLEMATIC_DECISION_ADAS)
    def test_decision_with_long_fields(self, ada, orchestrator, fetcher):
        """
        Test decision import with fields exceeding varchar(255) limit.

        CURRENT: Will FAIL with DataError until you implement fix.
        AFTER FIX: Should pass and import successfully.

        Fetches real decision from API (or VCR cassette) and attempts full pipeline.
        """
        # Fetch real decision from API (VCR records/replays)
        decision_dto = fetcher.fetch_a_decision(ada)
        assert decision_dto is not None, f"Failed to fetch decision {ada}"

        # Run through pipeline - will currently fail with DataError
        health_check = orchestrator.run_pipeline(
            decision_ada=decision_dto.ada,
            decision_dto=decision_dto,
            skip_opensearch=True,
        )

        # After fix: verify decision imported successfully
        decision = Decision.objects.get(ada=ada)
        assert decision is not None
        assert health_check.import_status == HealthStatus.HEALTHY

    @pytest.mark.vcr()
    def test_identify_problematic_fields(self, fetcher):
        """
        Diagnostic test: identify which fields exceed varchar(255) limit.

        Run this first to see exactly which fields are causing the error.
        Use this info to decide on truncation vs field widening.
        """
        ada = PROBLEMATIC_DECISION_ADAS[0]
        decision_dto = fetcher.fetch_a_decision(ada)
        assert decision_dto is not None

        # Analyze field lengths
        print(f"\n{'='*80}")
        print(f"FIELD LENGTH ANALYSIS: {ada}")
        print(f"{'='*80}")

        # Check main decision fields
        fields_to_check = {
            "protocolNumber": decision_dto.protocolNumber,
            "versionId": decision_dto.versionId,
            "correctedVersionId": decision_dto.correctedVersionId,
            "documentChecksum": decision_dto.documentChecksum,
        }

        print("\nDecision Fields:")
        for field, value in fields_to_check.items():
            if value:
                length = len(value)
                status = "[ERROR] TOO LONG" if length > 255 else "[OK] OK"
                print(f"  {field:25s}: {length:4d} chars {status}")

        # Check attachments
        if decision_dto.attachments:
            print("\nAttachments:")
            for i, att in enumerate(decision_dto.attachments):
                if att.id and len(att.id) > 255:
                    print(f"  [ERROR] Attachment[{i}].id: {len(att.id)} chars")
                if att.filename and len(att.filename) > 255:
                    print(
                        f"  [ERROR] Attachment[{i}].filename: {len(att.filename)} chars"
                    )

        print(f"{'='*80}\n")


# ════════════════════════════════════════════════════════════════════════════
# REFERENCE: Original errors from production logs
# ════════════════════════════════════════════════════════════════════════════
# 2026-01-31 20:26:01.164 | ERROR | core.importers.decisions:import_many:735
#   Failed to import decision ADA 'Ε46Υ469Β7Λ-ΑΝΡ': value too long for type character varying(255)
#
# 2026-01-31 20:26:01.499 | ERROR | core.importers.decisions:import_many:735
#   Failed to import decision ADA '95ΖΩ469Β7Λ-ΗΡΙ': value too long for type character varying(255)
