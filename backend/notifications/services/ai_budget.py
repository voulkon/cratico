"""Cache-aware AI budget helpers for notification summaries.

The unit that costs money is *new provider work*, not the number of batches.
A batch whose decisions are already in the shared one-liner cache is free and
must be allowed even when the user has no budget left.
"""

from datetime import datetime, time

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from notifications.models import NotificationBatch, NotificationPreference


def subscription_new_decision_allowance(
    subscription, now=None, exclude_batch_id=None
):
    """How many uncached decisions this subscription may pay for today.

    ``exclude_batch_id`` keeps the batch currently being summarized from
    consuming its own budget (its provisional count is already persisted when a
    retry recomputes the allowance).
    """
    preference = NotificationPreference.get_for_user_id(subscription.user_id)
    if not preference.ai_summary_enabled:
        return 0

    now = now or timezone.localtime()
    day_start = timezone.make_aware(
        datetime.combine(now.date(), time.min),
        timezone.get_current_timezone(),
    )
    cap = getattr(
        settings,
        "NOTIFICATION_AI_NEW_DECISIONS_PER_SUBSCRIPTION_PER_DAY",
        25,
    )
    if cap <= 0:
        return 0

    batches = NotificationBatch.objects.filter(
        subscription=subscription,
        created_at__gte=day_start,
    )
    if exclude_batch_id is not None:
        batches = batches.exclude(id=exclude_batch_id)
    used = batches.aggregate(total=Sum("ai_summary_new_count"))["total"] or 0
    return max(cap - used, 0)


def user_has_ai_budget(user_id):
    """Soft monthly budget check based on the user's AI interaction log.

    Returns ``True`` when no budget is configured (unlimited).  Cache hits are
    free and therefore remain available when this returns ``False``.
    """
    from core.models.ai_interaction_log import AIInteractionLog
    from core.models.user_ai_settings import UserAISettings

    ai_settings = UserAISettings.objects.filter(
        user_id=user_id, is_default=True
    ).first()
    if ai_settings is None or ai_settings.monthly_budget_usd is None:
        return True

    month_start = timezone.localtime().replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    spent = (
        AIInteractionLog.objects.filter(
            user_id=user_id,
            created_at__gte=month_start,
        ).aggregate(total=Sum("cost_usd"))["total"]
        or 0
    )
    return spent < ai_settings.monthly_budget_usd
