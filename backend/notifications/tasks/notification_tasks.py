from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone
from loguru import logger
from notifications.constants import CHECK_FREQUENCY_DAILY, CHECK_FREQUENCY_WEEKLY
from notifications.models import (
    Notification,
    NotificationBatch,
    NotificationBatchDecision,
    NotificationSubscription,
)
from notifications.utils import determine_match_reason, find_matching_decisions


@shared_task
def check_single_subscription(
    subscription_id, lookback_days=None, use_batch=True, send_email=False
):
    """
    Check a single subscription for matching decisions.
    Used for on-demand checks triggered by users via the "check now" button.

    Args:
        subscription_id: ID of the subscription to check
        lookback_days: Optional override - how many days back to check.
                      If None (default), checks from last_checked to now for continuity.
                      If specified, checks from (now - lookback_days) to now.
        use_batch: If True, create NotificationBatch; if False, create individual Notifications (default: True)
        send_email: If True, send email notification when matches are found (default: False)

    Returns:
        dict with subscription_id and either batch_id/decisions_added or notifications_created
    """
    try:
        subscription = NotificationSubscription.objects.select_related(
            "organization", "entity", "relationship_org", "relationship_entity"
        ).get(id=subscription_id)

        check_window_end = timezone.now()

        # Determine check window start based on whether lookback_days is specified
        if lookback_days is not None:
            # Override mode: user explicitly wants to check a specific period
            check_window_start = check_window_end - timedelta(days=lookback_days)
            logger.info(
                f"Checking subscription {subscription_id} (manual check with override, "
                f"lookback: {lookback_days} days)"
            )
        else:
            # Default mode: check from last_checked for continuity
            if subscription.last_checked:
                check_window_start = subscription.last_checked
                logger.info(
                    f"Checking subscription {subscription_id} (manual check, "
                    f"from last_checked: {check_window_start})"
                )
            else:
                # Never checked before - use subscription creation date or default to 30 days
                check_window_start = subscription.created_at
                logger.info(
                    f"Checking subscription {subscription_id} (first check, "
                    f"from created_at: {check_window_start})"
                )

        logger.info(f"Check window: {check_window_start} to {check_window_end}")

        # Find matching decisions
        matching_decisions = find_matching_decisions(subscription, check_window_start)

        if use_batch:
            # Create batch for matches (prevents notification spam)
            batch_result = create_batch_for_matches(
                subscription, matching_decisions, check_window_start, check_window_end
            )

            # Send email notification if requested and batch has decisions
            email_sent = False
            if (
                send_email
                and batch_result.get("batch_id")
                and batch_result.get("decisions_added", 0) > 0
            ):
                try:
                    from core.email_service import NotificationEmailService

                    # Get the batch to prepare email data
                    batch = NotificationBatch.objects.get(id=batch_result["batch_id"])

                    # Prepare batch data for email
                    decisions_list = list(
                        matching_decisions[:10]
                    )  # Limit to first 10 for email
                    batch_data = {
                        "id": batch.id,
                        "subscription_name": subscription.name
                        or f"Subscription #{subscription.id}",
                        "organization_name": (
                            subscription.organization.name
                            if subscription.organization
                            else None
                        ),
                        "entity_name": (
                            subscription.entity.name if subscription.entity else None
                        ),
                        "decision_count": batch_result.get("decisions_added", 0),
                        "check_window_start": check_window_start,
                        "check_window_end": check_window_end,
                        "decisions": [
                            {
                                "id": d.ada,
                                "subject": d.subject,
                                "organization": (
                                    d.organization.name if d.organization else "Unknown"
                                ),
                                "date": d.submission_timestamp,
                            }
                            for d in decisions_list
                        ],
                    }

                    # Send email
                    frontend_url = (
                        settings.FRONTEND_DOMAINS_clean[0]
                        if settings.FRONTEND_DOMAINS_clean
                        else "https://crati.co"
                    )
                    batch_data["app_url"] = frontend_url

                    # Get user's preferred language (default to 'en')
                    user_language = getattr(
                        subscription.user, "preferred_language", "en"
                    )

                    email_sent = (
                        NotificationEmailService.send_notification_batch_summary(
                            user_email=subscription.user.email,
                            username=subscription.user.username
                            or subscription.user.email,
                            batch_data=batch_data,
                            language=user_language,
                        )
                    )

                    if email_sent:
                        # Mark batch as emailed
                        batch.email_sent = True
                        batch.email_sent_at = timezone.now()
                        batch.save(update_fields=["email_sent", "email_sent_at"])
                        logger.info(
                            f"Email sent for batch {batch.id} to {subscription.user.email}"
                        )
                    else:
                        logger.warning(f"Failed to send email for batch {batch.id}")

                except Exception as e:
                    logger.error(
                        f"Error sending email for batch {batch_result.get('batch_id')}: {e}",
                        exc_info=True,
                    )

            # Update last_checked
            subscription.last_checked = timezone.now()
            subscription.save(update_fields=["last_checked"])

            logger.info(
                f"Subscription {subscription_id}: Created batch {batch_result.get('batch_id')} "
                f"with {batch_result.get('decisions_added', 0)} decisions"
            )

            return {
                "subscription_id": subscription_id,
                "batch_id": batch_result.get("batch_id"),
                "decisions_added": batch_result.get("decisions_added", 0),
                "batch_created": batch_result.get("batch_created", False),
                "email_sent": email_sent,
                "lookback_days": lookback_days,
                "check_window_start": check_window_start.isoformat(),
                "check_window_end": check_window_end.isoformat(),
                # For backwards compatibility with tests expecting 'notifications_created'
                "notifications_created": batch_result.get("decisions_added", 0),
            }
        else:
            # Create individual notifications
            notifications_created = create_notifications_for_matches(
                subscription, matching_decisions
            )

            # Update last_checked
            subscription.last_checked = timezone.now()
            subscription.save(update_fields=["last_checked"])

            logger.info(
                f"Subscription {subscription_id}: Created {notifications_created} notifications"
            )

            return {
                "subscription_id": subscription_id,
                "notifications_created": notifications_created,
                "lookback_days": lookback_days,
                "check_window_start": check_window_start.isoformat(),
                "check_window_end": check_window_end.isoformat(),
            }

    except NotificationSubscription.DoesNotExist:
        logger.error(f"Subscription {subscription_id} not found")
        return {"error": "Subscription not found", "subscription_id": subscription_id}
    except Exception as e:
        logger.error(
            f"Error checking subscription {subscription_id}: {e}", exc_info=True
        )
        return {"error": str(e), "subscription_id": subscription_id}


@shared_task
def check_subscriptions_for_new_decisions():
    """
    Main scheduled task - checks all active subscriptions with automatic check frequency
    for new matching decisions since last check.

    Runs daily. Only checks subscriptions with check_frequency='daily' or 'weekly'
    (weekly subscriptions are checked if last_checked was more than 7 days ago).
    """
    logger.info("Starting scheduled subscription check for new decisions")

    now = timezone.now()

    # Get active subscriptions that should be checked
    active_subscriptions = NotificationSubscription.objects.filter(
        is_active=True,
        check_frequency__in=[CHECK_FREQUENCY_DAILY, CHECK_FREQUENCY_WEEKLY],
    ).select_related(
        "organization", "entity", "relationship_org", "relationship_entity"
    )

    logger.info(
        f"Found {active_subscriptions.count()} active subscriptions with automatic checking enabled"
    )

    notifications_created = 0
    checked_count = 0

    for subscription in active_subscriptions:
        try:
            # Determine if we should check this subscription
            should_check = False

            if subscription.check_frequency == CHECK_FREQUENCY_DAILY:
                should_check = True
                # For daily checks, look back 1 day (or since last_checked if more recent)
                default_check_since = now - timedelta(days=1)
            elif subscription.check_frequency == CHECK_FREQUENCY_WEEKLY:
                # Check weekly subscriptions only if last_checked was more than 7 days ago
                if subscription.last_checked is None:
                    should_check = True
                    default_check_since = now - timedelta(days=7)
                elif (now - subscription.last_checked).days >= 7:
                    should_check = True
                    default_check_since = now - timedelta(days=7)

            if not should_check:
                continue

            # Determine actual check window
            check_window_start = subscription.last_checked or default_check_since
            check_window_end = now

            # Find matching decisions
            matching_decisions = find_matching_decisions(
                subscription, check_window_start
            )

            # Create batch for matches
            batch_result = create_batch_for_matches(
                subscription, matching_decisions, check_window_start, check_window_end
            )

            notifications_created += batch_result.get("decisions_added", 0)
            checked_count += 1

            # Update last_checked
            subscription.last_checked = now
            subscription.save(update_fields=["last_checked"])

            logger.info(
                f"Subscription {subscription.id} ({subscription.check_frequency}): "
                f"created {batch_result.get('decisions_added', 0)} notifications"
            )

        except Exception as e:
            logger.error(
                f"Error processing subscription {subscription.id}: {e}", exc_info=True
            )
            continue

    logger.info(
        f"Checked {checked_count} subscriptions, created {notifications_created} notifications"
    )
    return {
        "notifications_created": notifications_created,
        "checked_count": checked_count,
    }


def create_notifications_for_matches(subscription, matching_decisions):
    """
    Create Notification objects for each matching decision.
    Uses bulk_create with ignore_conflicts to avoid duplicates.

    This is the current approach used by check tasks to create individual
    notifications for each matching decision.
    """
    notifications_to_create = []

    for decision in matching_decisions:
        # Determine match reason and details
        match_reason, match_details = determine_match_reason(subscription, decision)

        notifications_to_create.append(
            Notification(
                user=subscription.user,
                subscription=subscription,
                decision=decision,
                match_reason=match_reason,
                match_details=match_details,
            )
        )

    # Use bulk_create with ignore_conflicts to handle unique constraint
    # Note: bulk_create with ignore_conflicts=True returns an empty list,
    # so we count before creating rather than after
    count = len(notifications_to_create)

    Notification.objects.bulk_create(notifications_to_create, ignore_conflicts=True)

    return count


def create_batch_for_matches(
    subscription, matching_decisions, check_window_start, check_window_end
):
    """
    Create a NotificationBatch and NotificationBatchDecision objects for matching decisions.

    This is the preferred approach for manual checks (check_single_subscription),
    grouping multiple matches into a single batch to prevent notification spam.

    Args:
        subscription: NotificationSubscription instance
        matching_decisions: QuerySet or list of Decision instances that matched
        check_window_start: datetime when check started
        check_window_end: datetime when check ended

    Returns:
        dict with batch_id and decisions_added count
    """

    from django.db import transaction

    # Convert to list if it's a QuerySet
    decisions_list = list(matching_decisions)

    if not decisions_list:
        logger.info(f"No decisions to batch for subscription {subscription.id}")
        return {"batch_id": None, "decisions_added": 0}

    # Filter out decisions that already exist in any batch for this subscription
    existing_decision_ids = NotificationBatchDecision.objects.filter(
        subscription=subscription, decision__in=decisions_list
    ).values_list("decision_id", flat=True)

    new_decisions = [d for d in decisions_list if d.id not in existing_decision_ids]

    if not new_decisions:
        logger.info(
            f"All {len(decisions_list)} decisions already exist in batches for subscription {subscription.id}"
        )
        return {"batch_id": None, "decisions_added": 0, "all_duplicates": True}

    logger.info(
        f"Subscription {subscription.id}: {len(new_decisions)} new decisions, "
        f"{len(existing_decision_ids)} already in batches"
    )

    # Calculate aggregate statistics (only for new decisions)
    aggregate_stats = {}

    # Amount statistics (if decisions have amounts)
    amounts = []
    for decision in new_decisions:
        if hasattr(decision, "amount") and decision.amount:
            amounts.append(float(decision.amount))

    if amounts:
        aggregate_stats["total_amount"] = sum(amounts)
        aggregate_stats["avg_amount"] = sum(amounts) / len(amounts)
        aggregate_stats["min_amount"] = min(amounts)
        aggregate_stats["max_amount"] = max(amounts)

    # Decision type breakdown
    decision_types = {}
    for decision in new_decisions:
        if decision.decision_type:
            type_uid = decision.decision_type.uid
            decision_types[type_uid] = decision_types.get(type_uid, 0) + 1

    if decision_types:
        aggregate_stats["decision_types"] = decision_types

    try:
        with transaction.atomic():
            # Create or get existing batch for this time window
            batch, created = NotificationBatch.objects.get_or_create(
                subscription=subscription,
                check_window_start=check_window_start,
                check_window_end=check_window_end,
                defaults={
                    "user": subscription.user,
                    "match_count": len(new_decisions),
                    "aggregate_stats": aggregate_stats,
                },
            )

            if not created:
                # Batch already exists - update match count and stats
                batch.match_count += len(new_decisions)
                batch.aggregate_stats = aggregate_stats
                batch.save(update_fields=["match_count", "aggregate_stats"])
                logger.info(
                    f"Updated existing batch {batch.id} for subscription {subscription.id}"
                )
            else:
                logger.info(
                    f"Created new batch {batch.id} for subscription {subscription.id}"
                )

            # Create batch decisions (only for new decisions)
            batch_decisions_to_create = []
            for decision in new_decisions:
                match_reason, match_details = determine_match_reason(
                    subscription, decision
                )

                batch_decisions_to_create.append(
                    NotificationBatchDecision(
                        batch=batch,
                        subscription=subscription,
                        decision=decision,
                        match_reason=match_reason,
                        match_details=match_details,
                    )
                )

            # Bulk create - duplicates already filtered out, but use ignore_conflicts for safety
            NotificationBatchDecision.objects.bulk_create(
                batch_decisions_to_create, ignore_conflicts=True
            )

            decisions_added = len(new_decisions)

            logger.info(
                f"Batch {batch.id}: Added {decisions_added} decisions "
                f"(total in batch: {batch.match_count})"
            )

            return {
                "batch_id": batch.id,
                "decisions_added": decisions_added,
                "batch_created": created,
            }

    except Exception as e:
        logger.error(
            f"Error creating batch for subscription {subscription.id}: {e}",
            exc_info=True,
        )
        return {"batch_id": None, "decisions_added": 0, "error": str(e)}


@shared_task
def check_all_active_subscriptions(lookback_days: int = 1):
    """
    Fan-out task: check ALL active subscriptions for new matching decisions.

    Called by the post-import orchestrator after a global daily import completes.
    Fans out to individual check_single_subscription tasks so each subscription
    is checked independently (retries, logging, error isolation).

    Only checks subscriptions with check_frequency='daily' or 'weekly' that
    are due for a check.  Manual-only subscriptions are skipped.

    Args:
        lookback_days: How many days back to check (default: 1 for yesterday's data).

    Returns:
        dict with total/dispatched/skipped counts.
    """
    from notifications.constants import CHECK_FREQUENCY_DAILY, CHECK_FREQUENCY_WEEKLY

    now = timezone.now()

    active_subscriptions = NotificationSubscription.objects.filter(
        is_active=True,
        check_frequency__in=[CHECK_FREQUENCY_DAILY, CHECK_FREQUENCY_WEEKLY],
    )

    total = active_subscriptions.count()
    dispatched = 0
    skipped = 0

    for subscription in active_subscriptions:
        try:
            should_check = False

            if subscription.check_frequency == CHECK_FREQUENCY_DAILY:
                should_check = True
            elif subscription.check_frequency == CHECK_FREQUENCY_WEEKLY:
                if subscription.last_checked is None:
                    should_check = True
                elif (now - subscription.last_checked).days >= 7:
                    should_check = True

            if not should_check:
                skipped += 1
                continue

            # Fire-and-forget each subscription check independently
            check_single_subscription.delay(
                subscription_id=subscription.id,
                lookback_days=lookback_days,
                use_batch=True,
                send_email=False,
            )
            dispatched += 1

        except Exception as e:
            logger.error(
                f"Error dispatching check for subscription {subscription.id}: {e}",
                exc_info=True,
            )
            skipped += 1

    logger.info(
        f"Bulk notification check complete: "
        f"{dispatched} dispatched, {skipped} skipped out of {total} total"
    )

    return {
        "status": "dispatched",
        "total": total,
        "dispatched": dispatched,
        "skipped": skipped,
    }
