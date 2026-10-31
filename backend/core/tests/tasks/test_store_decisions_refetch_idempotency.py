"""
Refetch idempotency for the import path (docs/en/AUTO_IMPORT_FLAG_MATRIX.md §5.5).

Hourly imports deliberately overlap the previous window, and the nightly daily
sweep re-fetches the whole day, so every decision is seen again.  Re-seeing a
decision must be cheap and side-effect free:

  * one Decision row, with ``created_at`` unchanged (it is in
    ``do_not_update_fields``),
  * no duplicate attachments or KAE amount rows,
  * no second heavy-pipeline dispatch when the decision is HEALTHY,
  * duplicate discovery tags are ignored.

WARNING/ERROR decisions ARE re-dispatched on every refetch.  That is the known
cost pinned by §4.4, so the test below makes a future policy change deliberate.
"""

import pytest
from conftest import OrganizationFactory, SignerFactory, UnitFactory
from core.importers.decisions import DecisionImporter
from core.models.decision_health import DecisionHealthCheck, HealthStatus
from core.models.decisions import Attachment, Decision, DecisionAmountKAE
from core.models.import_jobs import ImportJob, ImportJobStatus
from core.tasks.tasks_decisions_import import store_decisions_from_redis
from core.tests.utils import create_decision_dto
from core.utils.discovery_tracking import (
    DiscoverySource,
    add_discovery_source_to_decision,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def import_org():
    return OrganizationFactory()


@pytest.fixture
def import_dto(import_org):
    def _make(ada="REFETCH-1", num_attachments=1, num_kae=1):
        signers = [SignerFactory(organization=import_org) for _ in range(2)]
        units = [UnitFactory(organization=import_org) for _ in range(2)]
        return create_decision_dto(
            ada=ada,
            org_id=import_org.uid,
            signer_ids=[s.uid for s in signers],
            unit_ids=[u.uid for u in units],
            num_attachments=num_attachments,
            extra_fields_config={"has_amount": True, "num_kae": num_kae},
        )

    return _make


class TestImporterRefetch:
    def test_same_dto_twice_keeps_one_decision_and_created_at(self, import_dto):
        dto = import_dto()
        importer = DecisionImporter()

        assert importer.import_many([dto]) == 1
        first = Decision.objects.get(ada=dto.ada)
        created_at = first.created_at

        assert importer.import_many([dto]) == 0
        second = Decision.objects.get(ada=dto.ada)

        assert Decision.objects.filter(ada=dto.ada).count() == 1
        assert second.id == first.id
        assert second.created_at == created_at

    def test_overlapping_refetch_does_not_duplicate_children(self, import_dto):
        shared = import_dto(ada="REFETCH-SHARED", num_attachments=2, num_kae=2)
        new_one = import_dto(ada="REFETCH-NEW", num_attachments=1, num_kae=0)
        importer = DecisionImporter()

        importer.import_many([shared, new_one])
        decision = Decision.objects.get(ada=shared.ada)
        attachments = Attachment.objects.filter(decision=decision).count()
        kae_rows = DecisionAmountKAE.objects.filter(decision=decision).count()
        assert attachments > 0
        assert kae_rows > 0

        # The next hourly window overlaps and hands back the same DTO.
        importer.import_many([shared])

        assert Decision.objects.filter(ada=shared.ada).count() == 1
        assert Attachment.objects.filter(decision=decision).count() == attachments
        assert DecisionAmountKAE.objects.filter(decision=decision).count() == kae_rows


class TestDiscoveryTagIdempotency:
    def test_same_source_twice_does_not_grow_the_list(self, import_dto):
        importer = DecisionImporter()
        importer.import_many([import_dto(ada="REFETCH-DISC")])
        decision = Decision.objects.get(ada="REFETCH-DISC")

        add_discovery_source_to_decision(
            decision, DiscoverySource.DEFAULT_SEARCH, notes="run 1"
        )
        decision.refresh_from_db()
        first_count = len(decision.discovery_sources)

        add_discovery_source_to_decision(
            decision, DiscoverySource.DEFAULT_SEARCH, notes="run 2"
        )
        decision.refresh_from_db()

        assert len(decision.discovery_sources) == first_count
        assert first_count == 1


class TestStoreHealthGuard:
    """The ``store_decisions_from_redis`` health-check gate (tasks_decisions_import.py)."""

    @staticmethod
    def _run_store(dto, job):
        from unittest.mock import MagicMock, patch

        chunk = {"decisions": [dto.model_dump(mode="json")], "metadata": {}}
        cache = MagicMock()
        cache.get_chunk.return_value = chunk
        cache.redis_client = MagicMock()

        with (
            patch(
                "core.tasks.tasks_decisions_import.RedisDecisionCache",
                return_value=cache,
            ),
            patch(
                "core.tasks.tasks_documents.run_decision_pipeline_task.delay"
            ) as mock_delay,
        ):
            result = store_decisions_from_redis.apply(
                kwargs={"chunk_id": "chunk-1", "job_id": job.id}
            ).get()

        return result, mock_delay

    def test_healthy_decision_is_not_re_dispatched(self, import_dto):
        dto = import_dto(ada="REFETCH-HEALTHY")
        job = ImportJob.objects.create(
            start_date=dto.issueDate,
            end_date=dto.issueDate,
            status=ImportJobStatus.FETCHING,
        )

        first, delay = self._run_store(dto, job)
        assert first["status"] == "success"
        assert delay.call_count == 1

        decision = Decision.objects.get(ada=dto.ada)
        DecisionHealthCheck.objects.create(
            decision=decision, overall_status=HealthStatus.HEALTHY
        )

        second, delay = self._run_store(dto, job)
        assert second["status"] == "success"
        delay.assert_not_called()
        assert Decision.objects.filter(ada=dto.ada).count() == 1

    @pytest.mark.parametrize(
        "status", [HealthStatus.WARNING, HealthStatus.ERROR]
    )
    def test_warning_and_error_are_re_dispatched(self, import_dto, status):
        """Pins §4.4: non-healthy decisions are re-processed on every refetch."""
        dto = import_dto(ada=f"REFETCH-{status.value}")
        job = ImportJob.objects.create(
            start_date=dto.issueDate,
            end_date=dto.issueDate,
            status=ImportJobStatus.FETCHING,
        )

        self._run_store(dto, job)
        decision = Decision.objects.get(ada=dto.ada)
        DecisionHealthCheck.objects.create(decision=decision, overall_status=status)

        _, delay = self._run_store(dto, job)
        delay.assert_called_once()
