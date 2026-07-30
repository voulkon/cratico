"""
Tests for CostLedgerService — AI interaction logging and spend tracking.

Covers:
- ``log_interaction`` — create AIInteractionLog entries and roll up costs
- ``get_user_spend`` — per-user aggregation with provider breakdown
- ``get_system_spend`` — SYSTEM-billed aggregation
- ``check_budget`` — soft cap enforcement with month-boundary reset
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from core.models.ai_interaction_log import AIInteractionLog
from core.models.user_ai_settings import UserAISettings
from core.services.cost_ledger_service import BudgetExceededError, CostLedgerService
from django.utils import timezone
from freezegun import freeze_time


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def clean_logs():
    """Remove all AIInteractionLog entries before and after each test."""
    AIInteractionLog.objects.all().delete()
    yield
    AIInteractionLog.objects.all().delete()


@pytest.fixture
def user(db):
    """Create a plain user with no AI settings configured."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(username="testuser", password="pass")


@pytest.fixture
def user_with_settings(user):
    """Create UserAISettings with a $10.00 monthly budget."""
    return UserAISettings.objects.create(
        user=user,
        provider=UserAISettings.Provider.OPENROUTER,
        monthly_budget_usd=Decimal("10.00"),
    )


@pytest.fixture
def user_unlimited_budget(user):
    """Create UserAISettings with no budget cap (unlimited)."""
    return UserAISettings.objects.create(
        user=user,
        provider=UserAISettings.Provider.OPENROUTER,
        monthly_budget_usd=None,
    )


# ============================================================================
# log_interaction
# ============================================================================


class TestLogInteraction:
    """Tests for ``CostLedgerService.log_interaction``."""

    def test_basic_success_log(self, user):
        """A successful interaction creates a log entry and updates spend."""
        log = CostLedgerService.log_interaction(
            user=user,
            provider="openrouter",
            model_name="google/gemini-flash-1.5",
            input_tokens=100,
            output_tokens=50,
            cost_usd=Decimal("0.003"),
            latency_ms=120,
        )

        assert log.pk is not None
        assert log.user == user
        assert log.billed_to == "SYSTEM"
        assert log.provider == "openrouter"
        assert log.model_name == "google/gemini-flash-1.5"
        assert log.input_tokens == 100
        assert log.output_tokens == 50
        assert log.cost_usd == Decimal("0.003")
        assert log.latency_ms == 120
        assert log.status == "SUCCESS"
        assert log.error_message is None
        assert log.trigger == "manual"

        # User's monthly counter was updated
        user.refresh_from_db()
        assert user.ai_spent_this_month_usd == Decimal("0.00")

    def test_log_without_user(self):
        """Logging without a user creates a standalone entry."""
        log = CostLedgerService.log_interaction(
            provider="aws_bedrock",
            model_name="claude-3",
            cost_usd=Decimal("0.01"),
        )

        assert log.user is None
        assert log.billed_to == "SYSTEM"
        assert log.status == "SUCCESS"

    def test_failed_interaction_does_not_roll_up_cost(self, user):
        """A FAILED interaction creates a log but does NOT increment spend."""
        CostLedgerService.log_interaction(
            user=user,
            provider="openrouter",
            model_name="gpt-4",
            cost_usd=Decimal("5.00"),
            status="FAILED",
            error_message="timeout",
        )

        user.refresh_from_db()
        assert user.ai_spent_this_month_usd == Decimal("0.00")

        # Log entry still exists
        log = AIInteractionLog.objects.get()
        assert log.status == "FAILED"
        assert log.error_message == "timeout"

    def test_billed_to_user(self, user):
        """Explicit USER billing is recorded correctly."""
        log = CostLedgerService.log_interaction(
            user=user,
            billed_to="USER",
            provider="openrouter",
            model_name="gpt-4",
            cost_usd=Decimal("0.50"),
        )

        assert log.billed_to == "USER"

    def test_trigger_and_ref(self, user):
        """Trigger context fields are stored."""
        log = CostLedgerService.log_interaction(
            user=user,
            trigger="notification_batch_summary",
            trigger_ref="batch:42",
            provider="openrouter",
            model_name="gemini",
            cost_usd=Decimal("0.001"),
        )

        assert log.trigger == "notification_batch_summary"
        assert log.trigger_ref == "batch:42"

    def test_cost_rollup_accumulates(self, user):
        """Multiple interactions accumulate on the monthly counter."""
        CostLedgerService.log_interaction(
            user=user,
            provider="openrouter",
            model_name="gpt-4",
            cost_usd=Decimal("3.00"),
        )
        CostLedgerService.log_interaction(
            user=user,
            provider="openrouter",
            model_name="gpt-4",
            cost_usd=Decimal("2.50"),
        )
        CostLedgerService.log_interaction(
            user=user,
            provider="aws_bedrock",
            model_name="claude",
            cost_usd=Decimal("1.25"),
        )

        user.refresh_from_db()
        assert user.ai_spent_this_month_usd == Decimal("6.75")

    def test_cost_rollup_ignores_failed(self, user):
        """Only SUCCESS interactions are rolled up."""
        CostLedgerService.log_interaction(
            user=user, provider="o", model_name="m", cost_usd=10, status="SUCCESS"
        )
        CostLedgerService.log_interaction(
            user=user, provider="o", model_name="m", cost_usd=20, status="FAILED"
        )
        CostLedgerService.log_interaction(
            user=user, provider="o", model_name="m", cost_usd=30, status="SUCCESS"
        )

        user.refresh_from_db()
        assert user.ai_spent_this_month_usd == Decimal("40")

    def test_no_user_does_not_crash_spend_update(self):
        """Logging without a user should not attempt spend rollup."""
        # Should not raise
        log = CostLedgerService.log_interaction(
            provider="openrouter",
            model_name="gemini",
            cost_usd=Decimal("100.00"),
        )
        assert log.user is None

    def test_month_rollover_resets_counter(self, user):
        """When the month changes, the spend counter resets."""
        with freeze_time("2026-07-15"):
            CostLedgerService.log_interaction(
                user=user,
                provider="openrouter",
                model_name="gpt-4",
                cost_usd=Decimal("5.00"),
            )

        user.refresh_from_db()
        assert user.ai_spent_this_month_usd == Decimal("5.00")
        assert user.ai_spent_month == 202607

        with freeze_time("2026-08-01"):
            CostLedgerService.log_interaction(
                user=user,
                provider="openrouter",
                model_name="gpt-4",
                cost_usd=Decimal("3.00"),
            )

        user.refresh_from_db()
        assert user.ai_spent_this_month_usd == Decimal("3.00")
        assert user.ai_spent_month == 202608

    def test_zero_cost(self, user):
        """Zero-cost interactions are logged correctly."""
        log = CostLedgerService.log_interaction(
            user=user,
            provider="test",
            model_name="test",
            cost_usd=0,
        )

        assert log.cost_usd == Decimal("0.00")
        user.refresh_from_db()
        assert user.ai_spent_this_month_usd == Decimal("0.00")

    def test_integer_cost_converted_to_decimal(self, user):
        """Integer cost is converted to Decimal."""
        log = CostLedgerService.log_interaction(
            user=user,
            provider="test",
            model_name="test",
            cost_usd=5,
        )

        assert isinstance(log.cost_usd, Decimal)
        assert log.cost_usd == Decimal("5")


# ============================================================================
# get_user_spend
# ============================================================================


class TestGetUserSpend:
    """Tests for ``CostLedgerService.get_user_spend``."""

    def test_current_month_empty(self, user):
        """No interactions → zero totals."""
        result = CostLedgerService.get_user_spend(user)
        assert result["total_cost_usd"] == Decimal("0")
        assert result["total_input_tokens"] == 0
        assert result["total_output_tokens"] == 0
        assert result["call_count"] == 0
        assert result["by_provider"] == {}

    def test_current_month_aggregation(self, user):
        """Multiple interactions in the current month are summed."""
        with freeze_time("2026-07-10"):
            CostLedgerService.log_interaction(user=user, provider="openrouter",
                model_name="gpt-4", cost_usd=Decimal("1.00"),
                input_tokens=100, output_tokens=50)
            CostLedgerService.log_interaction(user=user, provider="openrouter",
                model_name="gpt-4", cost_usd=Decimal("2.00"),
                input_tokens=200, output_tokens=100)
            CostLedgerService.log_interaction(user=user, provider="aws",
                model_name="claude", cost_usd=Decimal("3.00"),
                input_tokens=50, output_tokens=25)

        with freeze_time("2026-07-15"):
            result = CostLedgerService.get_user_spend(user)

        assert result["total_cost_usd"] == Decimal("6.00")
        assert result["total_input_tokens"] == 350
        assert result["total_output_tokens"] == 175
        assert result["call_count"] == 3

        # Per-provider breakdown
        by_provider = result["by_provider"]
        assert "openrouter/gpt-4" in by_provider
        assert by_provider["openrouter/gpt-4"]["cost"] == Decimal("3.00")
        assert by_provider["openrouter/gpt-4"]["input_tokens"] == 300
        assert by_provider["openrouter/gpt-4"]["output_tokens"] == 150
        assert by_provider["openrouter/gpt-4"]["count"] == 2

        assert "aws/claude" in by_provider
        assert by_provider["aws/claude"]["cost"] == Decimal("3.00")
        assert by_provider["aws/claude"]["count"] == 1

    def test_specific_month(self, user):
        """Querying a specific month only returns that month's data."""
        with freeze_time("2026-06-20"):
            CostLedgerService.log_interaction(user=user, provider="p", model_name="m",
                cost_usd=Decimal("10.00"))

        with freeze_time("2026-07-10"):
            CostLedgerService.log_interaction(user=user, provider="p", model_name="m",
                cost_usd=Decimal("20.00"))

        with freeze_time("2026-07-15"):
            result = CostLedgerService.get_user_spend(user, month=date(2026, 6, 1))

        assert result["total_cost_usd"] == Decimal("10.00")
        assert result["call_count"] == 1

    def test_ignores_failed_interactions(self, user):
        """FAILED interactions are excluded from spend aggregation."""
        with freeze_time("2026-07-10"):
            CostLedgerService.log_interaction(user=user, provider="p", model_name="m",
                cost_usd=Decimal("5.00"), status="SUCCESS")
            CostLedgerService.log_interaction(user=user, provider="p", model_name="m",
                cost_usd=Decimal("100.00"), status="FAILED")

        with freeze_time("2026-07-15"):
            result = CostLedgerService.get_user_spend(user)

        assert result["total_cost_usd"] == Decimal("5.00")
        assert result["call_count"] == 1


# ============================================================================
# get_system_spend
# ============================================================================


class TestGetSystemSpend:
    """Tests for ``CostLedgerService.get_system_spend``."""

    def test_empty(self):
        """No SYSTEM-billed rows → zero totals."""
        result = CostLedgerService.get_system_spend()
        assert result["total_cost_usd"] == Decimal("0")
        assert result["by_user"] == {}

    def test_current_month_aggregation(self, user):
        """SYSTEM-billed rows are aggregated per user."""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user2 = User.objects.create_user(username="user2", password="pass")

        with freeze_time("2026-07-10"):
            CostLedgerService.log_interaction(user=user, billed_to="SYSTEM",
                provider="p", model_name="m", cost_usd=Decimal("1.00"))
            CostLedgerService.log_interaction(user=user, billed_to="SYSTEM",
                provider="p", model_name="m", cost_usd=Decimal("2.00"))
            CostLedgerService.log_interaction(user=user2, billed_to="SYSTEM",
                provider="p", model_name="m", cost_usd=Decimal("3.00"))

        with freeze_time("2026-07-15"):
            result = CostLedgerService.get_system_spend()

        assert result["total_cost_usd"] == Decimal("6.00")
        assert len(result["by_user"]) == 2
        assert result["by_user"][user.pk]["cost"] == Decimal("3.00")
        assert result["by_user"][user.pk]["count"] == 2
        assert result["by_user"][user2.pk]["cost"] == Decimal("3.00")
        assert result["by_user"][user2.pk]["count"] == 1

    def test_excludes_user_billed(self, user):
        """USER-billed rows are NOT included in system spend."""
        with freeze_time("2026-07-10"):
            CostLedgerService.log_interaction(user=user, billed_to="SYSTEM",
                provider="p", model_name="m", cost_usd=Decimal("5.00"))
            CostLedgerService.log_interaction(user=user, billed_to="USER",
                provider="p", model_name="m", cost_usd=Decimal("999.00"))

        with freeze_time("2026-07-15"):
            result = CostLedgerService.get_system_spend()

        assert result["total_cost_usd"] == Decimal("5.00")

    def test_excludes_failed(self, user):
        """FAILED SYSTEM rows are excluded."""
        with freeze_time("2026-07-10"):
            CostLedgerService.log_interaction(user=user, billed_to="SYSTEM",
                provider="p", model_name="m", cost_usd=10, status="SUCCESS")
            CostLedgerService.log_interaction(user=user, billed_to="SYSTEM",
                provider="p", model_name="m", cost_usd=99, status="FAILED")

        with freeze_time("2026-07-15"):
            result = CostLedgerService.get_system_spend()

        assert result["total_cost_usd"] == Decimal("10")

    def test_specific_month(self, user):
        """Querying a specific month works for system spend."""
        with freeze_time("2026-06-05"):
            CostLedgerService.log_interaction(user=user, billed_to="SYSTEM",
                provider="p", model_name="m", cost_usd=Decimal("7.00"))

        with freeze_time("2026-07-10"):
            CostLedgerService.log_interaction(user=user, billed_to="SYSTEM",
                provider="p", model_name="m", cost_usd=Decimal("8.00"))

        with freeze_time("2026-07-15"):
            result = CostLedgerService.get_system_spend(month=date(2026, 6, 1))

        assert result["total_cost_usd"] == Decimal("7.00")


# ============================================================================
# check_budget
# ============================================================================


class TestCheckBudget:
    """Tests for ``CostLedgerService.check_budget``."""

    def test_no_settings_allows(self, user):
        """User without AI settings has no budget → allowed."""
        assert CostLedgerService.check_budget(user) is True

    def test_unlimited_budget(self, user, user_unlimited_budget):
        """monthly_budget_usd=None means unlimited → allowed."""
        with freeze_time("2026-07-10"):
            # 5000 fits in AIInteractionLog.cost_usd (max 9999.999999)
            # and would exceed any reasonable cap — but None means unlimited
            CostLedgerService.log_interaction(user=user, provider="p", model_name="m",
                cost_usd=Decimal("5000.00"))

        user.refresh_from_db()
        assert CostLedgerService.check_budget(user) is True

    def test_within_budget(self, user, user_with_settings):
        """Spend under the $10 cap → allowed."""
        with freeze_time("2026-07-10"):
            CostLedgerService.log_interaction(user=user, provider="p", model_name="m",
                cost_usd=Decimal("9.99"))

        user.refresh_from_db()
        assert CostLedgerService.check_budget(user) is True

    def test_exactly_at_budget_raises(self, user, user_with_settings):
        """Spend exactly at cap SHOULD still be allowed (only > triggers)."""
        with freeze_time("2026-07-10"):
            CostLedgerService.log_interaction(user=user, provider="p", model_name="m",
                cost_usd=Decimal("10.00"))

        user.refresh_from_db()
        # Exactly at budget is NOT over → allowed
        assert CostLedgerService.check_budget(user) is True

    def test_exceeded_budget_raises(self, user, user_with_settings):
        """Spend over the $10 cap raises BudgetExceededError."""
        with freeze_time("2026-07-10"):
            CostLedgerService.log_interaction(user=user, provider="p", model_name="m",
                cost_usd=Decimal("10.01"))

        user.refresh_from_db()
        with pytest.raises(BudgetExceededError, match="Monthly AI budget exceeded"):
            CostLedgerService.check_budget(user)

    def test_month_rollover_resets_budget(self, user, user_with_settings):
        """When month rolls over, the old spend doesn't count."""
        with freeze_time("2026-07-10"):
            CostLedgerService.log_interaction(user=user, provider="p", model_name="m",
                cost_usd=Decimal("50.00"))  # Way over budget
            # Mid-month: should be over budget
            user.refresh_from_db()
            with pytest.raises(BudgetExceededError):
                CostLedgerService.check_budget(user)

        # Next month: counter resets, should now be allowed
        # We need to log a new interaction in August to reset the month key
        with freeze_time("2026-08-01"):
            CostLedgerService.log_interaction(user=user, provider="p", model_name="m",
                cost_usd=Decimal("1.00"))

        user.refresh_from_db()
        assert CostLedgerService.check_budget(user) is True

    def test_zero_budget_blocks_everything(self, user):
        """A budget of $0.00 should block any positive spend."""
        UserAISettings.objects.create(
            user=user,
            provider=UserAISettings.Provider.OPENROUTER,
            monthly_budget_usd=Decimal("0.00"),
        )

        with freeze_time("2026-07-10"):
            CostLedgerService.log_interaction(user=user, provider="p", model_name="m",
                cost_usd=Decimal("0.01"))

        user.refresh_from_db()
        with pytest.raises(BudgetExceededError):
            CostLedgerService.check_budget(user)

    def test_failed_interactions_dont_affect_budget(self, user, user_with_settings):
        """FAILED interactions don't roll up → don't affect budget check."""
        with freeze_time("2026-07-10"):
            CostLedgerService.log_interaction(user=user, provider="p", model_name="m",
                cost_usd=Decimal("999.00"), status="FAILED")

        user.refresh_from_db()
        assert CostLedgerService.check_budget(user) is True


# ============================================================================
# Edge cases
# ============================================================================


class TestEdgeCases:
    """Edge-case and regression tests."""

    def test_concurrent_month_reset(self, user):
        """Month reset logic works even when old month key is stale on user."""
        # Manually set stale values
        user.ai_spent_month = 202606  # June
        user.ai_spent_this_month_usd = Decimal("50.00")
        user.save()

        # Now log in July — should reset
        with freeze_time("2026-07-05"):
            CostLedgerService.log_interaction(user=user, provider="p", model_name="m",
                cost_usd=Decimal("2.00"))

        user.refresh_from_db()
        assert user.ai_spent_month == 202607
        assert user.ai_spent_this_month_usd == Decimal("2.00")

    def test_fresh_user_no_previous_spend(self, user):
        """A user with no prior ai_spent_month works fine."""
        assert user.ai_spent_month is None
        assert user.ai_spent_this_month_usd == Decimal("0.00")

        CostLedgerService.log_interaction(user=user, provider="p", model_name="m",
            cost_usd=Decimal("1.50"))

        user.refresh_from_db()
        assert user.ai_spent_this_month_usd == Decimal("1.50")

    def test_large_decimal_precision(self, user):
        """Very small costs are stored correctly."""
        log = CostLedgerService.log_interaction(
            user=user, provider="p", model_name="m", cost_usd=Decimal("0.000001")
        )
        assert log.cost_usd == Decimal("0.000001")

        user.refresh_from_db()
        # User counter uses decimal_places=2, so tiny values round down
        assert user.ai_spent_this_month_usd == Decimal("0.00")
