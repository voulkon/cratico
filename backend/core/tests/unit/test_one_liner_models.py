"""
Unit tests for the one-liner cache models: ``OneLinerConfig`` and
``DecisionOneLiner`` (attempt numbering, lineage helpers, defaults).
"""

from decimal import Decimal

import pytest
from django.db import transaction

from core.models.decision_one_liner import DecisionOneLiner, OneLinerStatus
from core.models.one_liner_config import OneLinerConfig, one_liner_config_key

pytestmark = pytest.mark.django_db


CONFIG_KWARGS = dict(
    prompt_kind="batch_one_liner",
    system_prompt="Be brief.",
    prompt_template="Summarize: {{ text }}",
    provider="OPENROUTER",
    model="test/model",
    temperature=0.3,
    max_tokens=3000,
)


class TestOneLinerConfig:
    def test_same_circumstances_yield_same_row(self):
        first = OneLinerConfig.get_or_create_for(**CONFIG_KWARGS)
        second = OneLinerConfig.get_or_create_for(**CONFIG_KWARGS)
        assert first.pk == second.pk
        assert OneLinerConfig.objects.count() == 1

    def test_changed_prompt_mints_new_row(self):
        first = OneLinerConfig.get_or_create_for(**CONFIG_KWARGS)
        changed = dict(CONFIG_KWARGS, system_prompt="Be different.")
        second = OneLinerConfig.get_or_create_for(**changed)
        assert first.pk != second.pk
        assert OneLinerConfig.objects.count() == 2

    @pytest.mark.parametrize(
        "field,value",
        [
            ("model", "other/model"),
            ("provider", "OTHER"),
            ("temperature", 0.7),
            ("max_tokens", 500),
            ("prompt_kind", "other_kind"),
            ("prompt_template", "Different: {{ text }}"),
        ],
    )
    def test_each_circumstance_is_a_cache_dimension(self, field, value):
        first = OneLinerConfig.get_or_create_for(**CONFIG_KWARGS)
        second = OneLinerConfig.get_or_create_for(**dict(CONFIG_KWARGS, **{field: value}))
        assert first.pk != second.pk

    def test_key_is_deterministic(self):
        key1 = one_liner_config_key(**CONFIG_KWARGS)
        key2 = one_liner_config_key(**CONFIG_KWARGS)
        assert key1 == key2
        assert len(key1) == 64

    def test_temperature_normalization_ignores_float_wobble(self):
        """0.3 float vs Decimal("0.30") vs 0.3000001 → same row."""
        a = OneLinerConfig.get_or_create_for(**CONFIG_KWARGS)
        b = OneLinerConfig.get_or_create_for(
            **dict(CONFIG_KWARGS, temperature=Decimal("0.30"))
        )
        c = OneLinerConfig.get_or_create_for(
            **dict(CONFIG_KWARGS, temperature=0.3000001)
        )
        assert a.pk == b.pk == c.pk
        assert a.temperature == Decimal("0.30")

    def test_max_tokens_none_is_a_dimension(self):
        a = OneLinerConfig.get_or_create_for(**dict(CONFIG_KWARGS, max_tokens=None))
        b = OneLinerConfig.get_or_create_for(**CONFIG_KWARGS)
        assert a.pk != b.pk


class TestDecisionOneLiner:
    def _make_lineage(self, decision, extraction, **overrides):
        config = OneLinerConfig.get_or_create_for(**overrides or CONFIG_KWARGS)
        return config

    def test_first_attempt_is_one(self, decision_type):
        from conftest import DecisionFactory, DocumentExtractionFactory

        decision = DecisionFactory(ada="ADA_AT1", decision_type=decision_type)
        extraction = DocumentExtractionFactory(decision=decision, raw_text="T.")
        config = self._make_lineage(decision, extraction)

        row = DecisionOneLiner.new_attempt(
            decision=decision, config=config, extraction_id=extraction.id
        )
        assert row.attempt == 1
        assert row.status == OneLinerStatus.PENDING

    def test_new_attempt_increments_within_lineage(self, decision_type):
        from conftest import DecisionFactory, DocumentExtractionFactory

        decision = DecisionFactory(ada="ADA_AT2", decision_type=decision_type)
        extraction = DocumentExtractionFactory(decision=decision, raw_text="T.")
        config = self._make_lineage(decision, extraction)

        DecisionOneLiner.new_attempt(
            decision=decision, config=config, extraction_id=extraction.id
        )
        second = DecisionOneLiner.new_attempt(
            decision=decision, config=config, extraction_id=extraction.id
        )
        assert second.attempt == 2

    def test_attempt_numbering_scopes_per_lineage(self, decision_type):
        """A different config starts its own lineage at 1.  (Extractions are
        OneToOne per decision today — a second extraction row cannot exist
        yet; extraction-lineage separation activates automatically when the
        model becomes one-to-many.)"""
        from conftest import DecisionFactory, DocumentExtractionFactory

        decision = DecisionFactory(ada="ADA_LIN", decision_type=decision_type)
        extraction = DocumentExtractionFactory(decision=decision, raw_text="A.")
        config = self._make_lineage(decision, extraction)
        other_config = OneLinerConfig.get_or_create_for(
            **dict(CONFIG_KWARGS, model="other/model")
        )

        DecisionOneLiner.new_attempt(
            decision=decision, config=config, extraction_id=extraction.id
        )
        other_lineage = DecisionOneLiner.new_attempt(
            decision=decision, config=other_config, extraction_id=extraction.id
        )
        assert other_lineage.attempt == 1

    def test_latest_completed_prefers_max_attempt(self, decision_type):
        from conftest import DecisionFactory, DocumentExtractionFactory

        decision = DecisionFactory(ada="ADA_LAT", decision_type=decision_type)
        extraction = DocumentExtractionFactory(decision=decision, raw_text="T.")
        config = self._make_lineage(decision, extraction)

        first = DecisionOneLiner.new_attempt(
            decision=decision, config=config, extraction_id=extraction.id
        )
        first.status = OneLinerStatus.COMPLETED
        first.one_liner = "First."
        first.save()
        second = DecisionOneLiner.new_attempt(
            decision=decision, config=config, extraction_id=extraction.id,
            status=OneLinerStatus.COMPLETED,
        )
        second.one_liner = "Second."
        second.save()

        latest = DecisionOneLiner.latest_completed(
            decision=decision, config=config, extraction_id=extraction.id
        )
        assert latest.pk == second.pk
        assert latest.one_liner == "Second."

    def test_latest_completed_ignores_newer_failed(self, decision_type):
        """A newer FAILED attempt never hides an older COMPLETED one."""
        from conftest import DecisionFactory, DocumentExtractionFactory

        decision = DecisionFactory(ada="ADA_FAIL", decision_type=decision_type)
        extraction = DocumentExtractionFactory(decision=decision, raw_text="T.")
        config = self._make_lineage(decision, extraction)

        completed = DecisionOneLiner.new_attempt(
            decision=decision, config=config, extraction_id=extraction.id,
            status=OneLinerStatus.COMPLETED,
        )
        completed.one_liner = "Good."
        completed.save()
        DecisionOneLiner.new_attempt(
            decision=decision, config=config, extraction_id=extraction.id,
            status=OneLinerStatus.FAILED,
        )

        latest = DecisionOneLiner.latest_completed(
            decision=decision, config=config, extraction_id=extraction.id
        )
        assert latest.pk == completed.pk

    def test_default_for_decision_spans_lineages(self, decision_type):
        """Display default = latest COMPLETED across all lineages (configs)."""
        from conftest import DecisionFactory, DocumentExtractionFactory

        decision = DecisionFactory(ada="ADA_DEF", decision_type=decision_type)
        extraction = DocumentExtractionFactory(decision=decision, raw_text="A.")
        config = self._make_lineage(decision, extraction)
        other_config = OneLinerConfig.get_or_create_for(
            **dict(CONFIG_KWARGS, model="other/model")
        )

        older = DecisionOneLiner.new_attempt(
            decision=decision, config=config, extraction_id=extraction.id,
            status=OneLinerStatus.COMPLETED,
        )
        older.one_liner = "Older."
        older.save()
        newer = DecisionOneLiner.new_attempt(
            decision=decision, config=other_config, extraction_id=extraction.id,
            status=OneLinerStatus.COMPLETED,
        )
        newer.one_liner = "Newer."
        newer.save()

        default = DecisionOneLiner.default_for_decision(decision.id)
        assert default.pk == newer.pk

    def test_default_for_decision_none_when_empty(self, decision_type):
        from conftest import DecisionFactory

        decision = DecisionFactory(ada="ADA_NONE", decision_type=decision_type)
        assert DecisionOneLiner.default_for_decision(decision.id) is None

    def test_claim_pending_flips_to_running(self, decision_type):
        from conftest import DecisionFactory, DocumentExtractionFactory

        decision = DecisionFactory(ada="ADA_CLAIM", decision_type=decision_type)
        extraction = DocumentExtractionFactory(decision=decision, raw_text="T.")
        config = self._make_lineage(decision, extraction)
        pending = DecisionOneLiner.new_attempt(
            decision=decision, config=config, extraction_id=extraction.id
        )

        claimed = DecisionOneLiner.claim_pending(
            decision=decision, config=config, extraction_id=extraction.id
        )
        claimed.refresh_from_db()
        assert claimed.pk == pending.pk
        assert claimed.status == OneLinerStatus.RUNNING

    def test_claim_pending_returns_none_when_no_pending(self, decision_type):
        from conftest import DecisionFactory, DocumentExtractionFactory

        decision = DecisionFactory(ada="ADA_CLAIM2", decision_type=decision_type)
        extraction = DocumentExtractionFactory(decision=decision, raw_text="T.")
        config = self._make_lineage(decision, extraction)
        # RUNNING row — not claimable
        DecisionOneLiner.new_attempt(
            decision=decision, config=config, extraction_id=extraction.id,
            status=OneLinerStatus.RUNNING,
        )
        assert (
            DecisionOneLiner.claim_pending(
                decision=decision, config=config, extraction_id=extraction.id
            )
            is None
        )

    def test_nulls_distinct_constraint(self, decision_type):
        """Subject-fallback lineage (extraction NULL): with
        ``nulls_distinct=False`` NULL extraction rows count as equal, so the
        (decision, NULL, config, attempt) tuple is still unique."""
        from conftest import DecisionFactory
        from django.db import IntegrityError

        decision = DecisionFactory(ada="ADA_NULL", decision_type=decision_type)
        config = self._make_lineage(decision, None)

        DecisionOneLiner.objects.create(
            decision=decision, config=config, extraction_id=None, attempt=1
        )
        # Nested atomic: the constraint violation aborts the surrounding
        # transaction — roll back to the savepoint so the test can continue.
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DecisionOneLiner.objects.create(
                    decision=decision, config=config, extraction_id=None, attempt=1
                )
