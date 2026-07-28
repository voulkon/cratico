"""
CostLedgerService — creates AIInteractionLog entries and tracks spend.

Responsibilities:
- ``log_interaction(...)`` — create an ``AIInteractionLog`` and update the
  user's monthly spend counter on ``CustomUser``.
- ``get_user_spend(user, month)`` — aggregate spend for a user.
- ``get_system_spend(month)`` — all SYSTEM-billed rows (re-invoicing report).
- ``check_budget(user)`` — raise/flag if the user is over their soft cap.
"""

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from loguru import logger

from core.models.ai_interaction_log import AIInteractionLog
from core.models.user_ai_settings import UserAISettings


class BudgetExceededError(Exception):
    """Raised when a user's monthly AI spend exceeds their soft cap."""


class CostLedgerService:
    """Service for logging AI interactions and querying spend."""

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    @staticmethod
    @transaction.atomic
    def log_interaction(
        *,
        user=None,
        billed_to: str = "SYSTEM",
        trigger: str = "manual",
        trigger_ref: str | None = None,
        provider: str = "",
        model_name: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: Decimal | float | int = 0,
        latency_ms: int | None = None,
        status: str = "SUCCESS",
        error_message: str | None = None,
        pipeline_run=None,
        pipeline_step_run=None,
    ) -> AIInteractionLog:
        """
        Create an ``AIInteractionLog`` and roll up cost to the user's monthly
        counter.
        """
        cost = Decimal(str(cost_usd))

        log = AIInteractionLog.objects.create(
            user=user,
            billed_to=billed_to,
            trigger=trigger,
            trigger_ref=trigger_ref,
            provider=provider,
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            status=status,
            error_message=error_message,
            pipeline_run=pipeline_run,
            pipeline_step_run=pipeline_step_run,
        )

        # Roll up to user's monthly counter
        if user is not None and status == "SUCCESS":
            CostLedgerService._update_user_monthly_spend(user, cost)

        return log

    # ------------------------------------------------------------------
    # Monthly spend counter
    # ------------------------------------------------------------------
    @staticmethod
    def _current_month_key() -> int:
        """Return current month as YYYYMM integer."""
        now = timezone.now()
        return now.year * 100 + now.month

    @staticmethod
    def _update_user_monthly_spend(user, cost: Decimal) -> None:
        """Increment the user's monthly spend, resetting if the month rolled."""
        month_key = CostLedgerService._current_month_key()

        # Refresh from DB to avoid stale values in long-running workers
        from users.models import CustomUser

        user = CustomUser.objects.select_for_update().get(pk=user.pk)

        if user.ai_spent_month != month_key:
            user.ai_spent_month = month_key
            user.ai_spent_this_month_usd = cost
        else:
            user.ai_spent_this_month_usd += cost

        user.save(update_fields=["ai_spent_this_month_usd", "ai_spent_month"])

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    @staticmethod
    def get_user_spend(user, month: date | None = None) -> dict:
        """
        Return total spend, token totals, and per-provider breakdown for a
        user in a given month (defaults to current month).
        """
        qs = AIInteractionLog.objects.filter(user=user, status="SUCCESS")
        if month:
            qs = qs.filter(created_at__year=month.year, created_at__month=month.month)
        else:
            now = timezone.now()
            qs = qs.filter(created_at__year=now.year, created_at__month=now.month)

        total_cost = Decimal("0")
        total_input = 0
        total_output = 0
        count = 0
        by_provider: dict[str, dict] = {}

        for log in qs:
            total_cost += log.cost_usd
            total_input += log.input_tokens
            total_output += log.output_tokens
            count += 1
            key = f"{log.provider}/{log.model_name}"
            entry = by_provider.setdefault(
                key, {"cost": Decimal("0"), "input_tokens": 0, "output_tokens": 0, "count": 0}
            )
            entry["cost"] += log.cost_usd
            entry["input_tokens"] += log.input_tokens
            entry["output_tokens"] += log.output_tokens
            entry["count"] += 1

        return {
            "total_cost_usd": total_cost,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "call_count": count,
            "by_provider": by_provider,
        }

    @staticmethod
    def get_system_spend(month: date | None = None) -> dict:
        """Aggregate all SYSTEM-billed rows for a given month."""
        qs = AIInteractionLog.objects.filter(billed_to="SYSTEM", status="SUCCESS")
        if month:
            qs = qs.filter(created_at__year=month.year, created_at__month=month.month)
        else:
            now = timezone.now()
            qs = qs.filter(created_at__year=now.year, created_at__month=now.month)

        total_cost = Decimal("0")
        by_user: dict[int, dict] = {}

        for log in qs:
            total_cost += log.cost_usd
            uid = log.user_id
            entry = by_user.setdefault(
                uid, {"user_id": uid, "cost": Decimal("0"), "count": 0}
            )
            entry["cost"] += log.cost_usd
            entry["count"] += 1

        return {
            "total_cost_usd": total_cost,
            "by_user": by_user,
        }

    # ------------------------------------------------------------------
    # Budget enforcement
    # ------------------------------------------------------------------
    @staticmethod
    def check_budget(user) -> bool:
        """
        Return ``True`` if the user is within their monthly budget.

        Raises ``BudgetExceededError`` if a budget is set and exceeded.
        """
        try:
            settings = user.ai_settings
        except UserAISettings.DoesNotExist:
            return True  # No settings → no budget → allow

        if settings.monthly_budget_usd is None:
            return True  # Unlimited

        # Refresh spend from DB
        from users.models import CustomUser

        user_fresh = CustomUser.objects.get(pk=user.pk)
        spent = user_fresh.ai_spent_this_month_usd or Decimal("0")
        if spent > settings.monthly_budget_usd:
            logger.warning(
                f"User {user.id} exceeded AI budget: "
                f"spent {spent} > cap {settings.monthly_budget_usd}"
            )
            raise BudgetExceededError(
                f"Monthly AI budget exceeded: ${spent:.2f} > ${settings.monthly_budget_usd:.2f}"
            )
        return True
