from datetime import timedelta

from celery import chord, shared_task
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
            # Also send if all decisions are duplicates but the existing batch hasn't been emailed
            email_sent = False
            should_email = (
                send_email
                and batch_result.get("batch_id")
                and (
                    batch_result.get("decisions_added", 0) > 0
                    or not batch_result.get("batch_already_emailed", True)
                )
            )
            if should_email:
                # Never send email to users whose email hasn't been verified.
                # SES rejects unverified identities; this also prevents
                # sending to test/placeholder addresses (e.g. admin@example.com).
                if not getattr(subscription.user, "email_verified", False):
                    logger.warning(
                        f"User {subscription.user_id} ({subscription.user.email}) "
                        f"email not verified — skipping notification email for "
                        f"batch {batch_result['batch_id']} (subscription {subscription_id})"
                    )
                    should_email = False

            if should_email:
                logger.info(
                    f"Triggering email for batch {batch_result['batch_id']} "
                    f"(subscription {subscription_id}, decisions_added={batch_result.get('decisions_added', 0)}, "
                    f"all_duplicates={batch_result.get('all_duplicates', False)})"
                )
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
                        "subscription_name": subscription.alias
                        or f"Subscription #{subscription.id}",
                        "organization_name": (
                            subscription.organization.label
                            if subscription.organization
                            else None
                        ),
                        "entity_name": (
                            subscription.entity.name if subscription.entity else None
                        ),
                        "decision_count": batch.match_count
                        if batch.match_count
                        else batch_result.get("decisions_added", 0),
                        "check_window_start": check_window_start,
                        "check_window_end": check_window_end,
                        "decisions": [
                            {
                                "id": d.ada,
                                "subject": d.subject,
                                "organization": (
                                    d.organization.label if d.organization else "Unknown"
                                ),
                                "date": d.submission_timestamp,
                            }
                            for d in decisions_list
                        ],
                    }

                    # Send email
                    from core.services.frontend_url import frontend_base_url

                    frontend_url = frontend_base_url()
                    # TODO: Remove this log
                    logger.debug("Using frontend URL for email links: {}", frontend_url)
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
            elif batch_result.get("batch_id") and batch_result.get("decisions_added", 0) > 0:
                logger.info(
                    f"Skipping email for batch {batch_result['batch_id']}: "
                    f"send_email={send_email}"
                )
            elif batch_result.get("all_duplicates") and batch_result.get("batch_id"):
                logger.info(
                    f"Skipping email for batch {batch_result['batch_id']}: "
                    f"all decisions are duplicates and batch was already emailed"
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
        # Find the most recent batch for this subscription that overlaps with the check window
        # (for email re-sending if the batch hasn't been emailed yet)
        existing_batch = (
            NotificationBatch.objects.filter(
                subscription=subscription,
                check_window_end__gte=check_window_start,
                check_window_start__lte=check_window_end,
            )
            .order_by("-created_at")
            .first()
        )
        logger.info(
            f"All {len(decisions_list)} decisions already exist in batches for subscription {subscription.id}"
        )
        return {
            "batch_id": existing_batch.id if existing_batch else None,
            "decisions_added": 0,
            "all_duplicates": True,
            "batch_already_emailed": existing_batch.email_sent if existing_batch else True,
        }

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

            # Trigger AI summarization if enabled on the subscription
            if decisions_added > 0 and getattr(
                subscription, "ai_summary_enabled", False
            ):
                try:
                    from notifications.tasks.ai_summary_tasks import (
                        summarize_notification_batch,
                    )

                    summarize_notification_batch.delay(batch_id=batch.id)
                    logger.info(
                        f"Triggered AI summarization for batch {batch.id} "
                        f"(subscription {subscription.id})"
                    )
                except Exception as ai_err:
                    logger.warning(
                        f"Failed to trigger AI summarization for batch {batch.id}: {ai_err}"
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


def _subscription_criteria_hash(subscription) -> str:
    """
    Build a stable hash of a subscription's matching criteria.

    Two subscriptions with the same hash will match the exact same set of
    decisions for a given time window, so the matching query only needs to
    run once per unique hash.

    Includes all fields that affect find_matching_decisions():
    - Target: organization, entity, relationship_org, relationship_entity,
              person_name, signer_name
    - Filters: keywords, keyword_match_operator, amount_min, amount_max,
              decision_types
    """
    import hashlib
    import json

    criteria = {
        "organization_id": subscription.organization_id,
        "entity_id": subscription.entity_id,
        "relationship_org_id": subscription.relationship_org_id,
        "relationship_entity_id": subscription.relationship_entity_id,
        "person_name": (subscription.person_name or "").strip().lower(),
        "signer_name": (subscription.signer_name or "").strip().lower(),
        "keywords": sorted(subscription.keywords) if subscription.keywords else None,
        "keyword_match_operator": subscription.keyword_match_operator,
        "amount_min": str(subscription.amount_min) if subscription.amount_min else None,
        "amount_max": str(subscription.amount_max) if subscription.amount_max else None,
        "decision_types": (
            sorted(subscription.decision_types)
            if subscription.decision_types
            else None
        ),
    }
    raw = json.dumps(criteria, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


@shared_task
def check_all_active_subscriptions(lookback_days: int = 1):
    """
    Fan-out task: check ALL active subscriptions for new matching decisions.

    Called by the post-import orchestrator after a global daily import completes.

    Groups subscriptions by user and dispatches one per-user chord:
        check_user_subscriptions(user_id, [sub_ids], lookback_days)
          → send_consolidated_email_for_user(user_id)

    Each user's chord fires independently — user A's email doesn't wait for
    user B's checks to finish.

    Only checks subscriptions with check_frequency='daily' or 'weekly' that
    are due for a check.  Manual-only subscriptions are skipped.

    Args:
        lookback_days: How many days back to check (default: 1 for yesterday's data).

    Returns:
        dict with total/dispatched/skipped/users counts.
    """
    from notifications.constants import CHECK_FREQUENCY_DAILY, CHECK_FREQUENCY_WEEKLY

    now = timezone.now()

    active_subscriptions = (
        NotificationSubscription.objects.filter(
            is_active=True,
            check_frequency__in=[CHECK_FREQUENCY_DAILY, CHECK_FREQUENCY_WEEKLY],
        )
        .select_related("user")
        .order_by("user_id")
    )

    total = active_subscriptions.count()

    # Group due subscription IDs by user
    user_subscriptions: dict[int, list[int]] = {}
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

            user_subscriptions.setdefault(subscription.user_id, []).append(
                subscription.id
            )

        except Exception as e:
            logger.error(
                f"Error dispatching check for subscription {subscription.id}: {e}",
                exc_info=True,
            )
            skipped += 1

    dispatched = sum(len(subs) for subs in user_subscriptions.values())

    logger.info(
        f"Bulk notification check: "
        f"{dispatched} dispatched across {len(user_subscriptions)} users, "
        f"{skipped} skipped out of {total} total"
    )

    if not user_subscriptions:
        logger.info("No subscriptions to check, skipping consolidated emails")
        return {
            "status": "dispatched",
            "total": total,
            "dispatched": 0,
            "skipped": skipped,
            "users": 0,
        }

    # Dispatch one chord per user — each fires independently
    for user_id, subscription_ids in user_subscriptions.items():
        chord(
            check_user_subscriptions.s(
                user_id=user_id,
                subscription_ids=subscription_ids,
                lookback_days=lookback_days,
            )
        )(send_consolidated_email_for_user.s(user_id=user_id))

    return {
        "status": "dispatched",
        "total": total,
        "dispatched": dispatched,
        "skipped": skipped,
        "users": len(user_subscriptions),
    }


@shared_task
def check_user_subscriptions(user_id, subscription_ids, lookback_days=1):
    """
    Check all subscriptions for a single user, with criteria deduplication.

    Subscriptions with identical matching criteria (same target + same filters)
    share a single find_matching_decisions() query.  Each subscription still
    gets its own NotificationBatch (so users can manage them independently),
    but the expensive DB query runs only once per unique criteria set.

    This task does NOT send emails — the chord callback handles that.

    Args:
        user_id: User ID
        subscription_ids: List of subscription IDs to check
        lookback_days: How many days back to check

    Returns:
        dict with user_id, batches_created, total_decisions, errors
    """
    check_window_end = timezone.now()
    check_window_start = check_window_end - timedelta(days=lookback_days)

    subscriptions = NotificationSubscription.objects.filter(
        id__in=subscription_ids
    ).select_related(
        "user", "organization", "entity", "relationship_org", "relationship_entity"
    )

    # Group subscriptions by criteria hash for deduplication
    criteria_groups: dict[str, list[NotificationSubscription]] = {}
    for sub in subscriptions:
        criteria_hash = _subscription_criteria_hash(sub)
        criteria_groups.setdefault(criteria_hash, []).append(sub)

    logger.info(
        f"User {user_id}: {len(subscriptions)} subscriptions, "
        f"{len(criteria_groups)} unique criteria sets"
    )

    batches_created = 0
    total_decisions = 0
    errors = 0
    batch_ids = []

    for criteria_hash, group_subs in criteria_groups.items():
        try:
            # Use the first subscription in the group to run the query
            primary_sub = group_subs[0]

            matching_decisions = find_matching_decisions(
                primary_sub, check_window_start
            )

            if not matching_decisions:
                logger.debug(
                    f"Criteria group {criteria_hash[:8]}: no matching decisions"
                )
                # Still update last_checked for all subs in the group
                for sub in group_subs:
                    sub.last_checked = timezone.now()
                    sub.save(update_fields=["last_checked"])
                continue

            matching_list = list(matching_decisions)
            logger.info(
                f"Criteria group {criteria_hash[:8]}: {len(matching_list)} matches, "
                f"creating batches for {len(group_subs)} subscriptions"
            )

            # Create a batch for EACH subscription in the group
            # (each needs its own batch for independent user management)
            for sub in group_subs:
                batch_result = create_batch_for_matches(
                    sub, matching_list, check_window_start, check_window_end
                )

                if batch_result.get("batch_id"):
                    batches_created += 1
                    total_decisions += batch_result.get("decisions_added", 0)
                    batch_ids.append(batch_result["batch_id"])

                # Update last_checked
                sub.last_checked = timezone.now()
                sub.save(update_fields=["last_checked"])

        except Exception as e:
            errors += 1
            logger.error(
                f"Error checking criteria group {criteria_hash[:8]} "
                f"for user {user_id}: {e}",
                exc_info=True,
            )
            # Still try to update last_checked
            for sub in group_subs:
                try:
                    sub.last_checked = timezone.now()
                    sub.save(update_fields=["last_checked"])
                except Exception:
                    pass

    logger.info(
        f"User {user_id}: check complete — {batches_created} batches, "
        f"{total_decisions} decisions, {errors} errors"
    )

    return {
        "user_id": user_id,
        "batches_created": batches_created,
        "total_decisions": total_decisions,
        "errors": errors,
        "batch_ids": batch_ids,
    }


@shared_task
def send_consolidated_email_for_user(*args, user_id=None):
    """
    Send a single consolidated email to a user summarizing their new batches
    from the current check run only.

    Called as the callback of a per-user chord after check_user_subscriptions
    completes.  Only emails the batches created by the just-finished header
    task — not any stale un-emailed batches from previous runs.

    Args:
        *args: Results from the chord header task (check_user_subscriptions).
               Expected to contain a dict with 'batch_ids' (list of ints).
        user_id: The user ID to send the email to (passed via .s(user_id=...)).

    Returns:
        dict with user_id, batches_emailed, success
    """
    from core.email_service import NotificationEmailService
    from django.contrib.auth import get_user_model

    if user_id is None:
        logger.error("send_consolidated_email_for_user called without user_id")
        return {"user_id": None, "batches_emailed": 0, "success": False}

    User = get_user_model()

    # Extract batch IDs from the chord header results.
    # Celery delivers chord header results as a LIST of per-task results,
    # even when the header is a single task — so unwrap one level when the
    # first element is a list.  Fall back to the old behaviour (all
    # un-emailed) only when no usable result is present at all.
    header_result = None
    if args:
        candidate = args[0]
        if isinstance(candidate, (list, tuple)) and len(candidate) == 1:
            candidate = candidate[0]
        if isinstance(candidate, dict) and "batch_ids" in candidate:
            header_result = candidate

    batch_ids_from_run = (
        header_result["batch_ids"] if header_result is not None else None
    )

    if batch_ids_from_run is not None:
        if not batch_ids_from_run:
            # No batches were created in this run — nothing to email
            logger.info(
                f"User {user_id}: no new batches created in this run, "
                f"skipping email"
            )
            return {"user_id": user_id, "batches_emailed": 0, "success": True}

        # Only email the batches created in this run
        unemailed_batches = (
            NotificationBatch.objects.filter(
                email_sent=False, user_id=user_id, id__in=batch_ids_from_run
            )
            .select_related("subscription__organization", "subscription__entity")
            .order_by("-created_at")
        )
    else:
        # Fallback: no batch IDs from header — query recent un-emailed
        # batches only.  Batches older than 2h are from previous runs and
        # must NOT be emailed here (prevents stale batches leaking into
        # every subsequent day's email when the fallback fires).
        logger.warning(
            f"User {user_id}: no batch_ids from chord header, "
            f"falling back to recent un-emailed batches"
        )
        recent_cutoff = timezone.now() - timedelta(hours=2)
        unemailed_batches = (
            NotificationBatch.objects.filter(
                email_sent=False, user_id=user_id, created_at__gte=recent_cutoff
            )
            .select_related("subscription__organization", "subscription__entity")
            .order_by("-created_at")
        )

    if not unemailed_batches.exists():
        logger.info(f"User {user_id}: no un-emailed batches, skipping email")
        return {"user_id": user_id, "batches_emailed": 0, "success": True}

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.error(f"User {user_id} not found, cannot send consolidated email")
        return {"user_id": user_id, "batches_emailed": 0, "success": False}

    # Never send email to users whose email hasn't been verified.
    # SES rejects unverified identities; this also prevents sending
    # to test/placeholder addresses (e.g. admin@example.com).
    if not getattr(user, "email_verified", False):
        logger.warning(
            f"User {user_id} ({user.email}) email not verified — "
            f"skipping consolidated notification email"
        )
        return {"user_id": user_id, "batches_emailed": 0, "success": True}

    user_language = getattr(user, "preferred_language", "en") or "en"

    # Build batch data for the template
    batch_data_list = []
    total_decisions = 0
    batch_ids_to_mark = []

    for batch in unemailed_batches:
        batch_ids_to_mark.append(batch.id)
        total_decisions += batch.match_count

        batch_data_list.append(
            {
                "id": batch.id,
                "subscription_name": (
                    batch.subscription.alias
                    or f"Subscription #{batch.subscription.id}"
                ),
                "organization_name": (
                    batch.subscription.organization.label
                    if batch.subscription.organization
                    else None
                ),
                "entity_name": (
                    batch.subscription.entity.name
                    if batch.subscription.entity
                    else None
                ),
                "decision_count": batch.match_count,
            }
        )

    # Send one consolidated email
    email_sent = NotificationEmailService.send_consolidated_batch_summary(
        user_email=user.email,
        username=user.username or user.email,
        batches=batch_data_list,
        total_decisions=total_decisions,
        language=user_language,
    )

    if email_sent:
        # Mark all batches as emailed
        now = timezone.now()
        NotificationBatch.objects.filter(id__in=batch_ids_to_mark).update(
            email_sent=True,
            email_sent_at=now,
        )
        logger.info(
            f"Consolidated email sent to {user.email}: "
            f"{len(batch_ids_to_mark)} batches, {total_decisions} decisions"
        )
        return {
            "user_id": user_id,
            "batches_emailed": len(batch_ids_to_mark),
            "success": True,
        }
    else:
        logger.error(f"Failed to send consolidated email to {user.email}")
        return {
            "user_id": user_id,
            "batches_emailed": 0,
            "success": False,
        }
