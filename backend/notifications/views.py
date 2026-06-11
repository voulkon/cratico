from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Count, Max, Min
from django.utils import timezone
from loguru import logger
from notifications.constants import (
    SUBSCRIPTION_TYPE_ENTITY,
    SUBSCRIPTION_TYPE_FILTER,
    SUBSCRIPTION_TYPE_ORGANIZATION,
    SUBSCRIPTION_TYPE_PERSON,
    SUBSCRIPTION_TYPE_RELATIONSHIP,
    SUBSCRIPTION_TYPE_SIGNER,
)
from notifications.models import (
    Notification,
    NotificationBatch,
    NotificationBatchDecision,
    NotificationSubscription,
)
from notifications.serializers import (
    NotificationBatchDecisionSerializer,
    NotificationBatchDetailSerializer,
    NotificationBatchListSerializer,
    NotificationDetailSerializer,
    NotificationListSerializer,
    NotificationSerializer,
    NotificationSubscriptionCreateSerializer,
    NotificationSubscriptionListSerializer,
    NotificationSubscriptionSerializer,
)
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


class NotificationSubscriptionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing notification subscriptions.

    Users can only see and manage their own subscriptions.

    Provides standard CRUD operations:
    - list: GET /api/notifications/subscriptions/
    - create: POST /api/notifications/subscriptions/
    - retrieve: GET /api/notifications/subscriptions/{id}/
    - update: PUT /api/notifications/subscriptions/{id}/
    - partial_update: PATCH /api/notifications/subscriptions/{id}/
    - destroy: DELETE /api/notifications/subscriptions/{id}/

    Custom actions:
    - check_organization_subscription: Check if user is subscribed to an organization
    - check_entity_subscription: Check if user is subscribed to an entity
    - check_relationship_subscription: Check if user is subscribed to a relationship
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        Filter queryset to only show current user's subscriptions.
        Optimize with select_related for nested relationships.
        """
        # Handle schema generation (drf-yasg) with AnonymousUser
        if not self.request.user or not self.request.user.is_authenticated:
            return NotificationSubscription.objects.none()

        return (
            NotificationSubscription.objects.filter(user=self.request.user)
            .select_related(
                "organization", "entity", "relationship_org", "relationship_entity"
            )
            .order_by("-created_at")
        )

    def get_serializer_class(self):
        """
        Use different serializers for different actions.
        """
        if self.action == "list":
            return NotificationSubscriptionListSerializer
        elif self.action == "create":
            return NotificationSubscriptionCreateSerializer
        else:
            return NotificationSubscriptionSerializer

    def create(self, request, *args, **kwargs):
        """
        Create a new subscription for the current user.
        Optionally triggers an immediate check for matching decisions.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            subscription = serializer.save()
        except (IntegrityError, ValidationError) as e:
            # Handle duplicate subscription attempts
            logger.warning(
                f"Duplicate subscription attempt by user {request.user.id}: {e}"
            )
            return Response(
                {
                    "error": "A notification rule for this already exists.",
                    "detail": "You are already subscribed to this entity. Please check your existing subscriptions.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Don't automatically check for historical matches - only notify about new decisions
        # Users can manually trigger a check if they want to see past matches using the "check-now" action

        # Return full details using the detail serializer
        output_serializer = NotificationSubscriptionSerializer(subscription)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        """
        Update an existing subscription.
        Note: Users cannot change the subscription type (organization/entity/relationship).
        They should delete and create a new subscription instead.
        """
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = NotificationSubscriptionSerializer(
            instance, data=request.data, partial=partial
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="check-now")
    def check_now(self, request, pk=None):
        """
        Manually trigger a check for new matching decisions.

        POST /api/notifications/subscriptions/{id}/check-now/

        Optional query params:
        - lookback_days: Override - check specific number of days back (e.g., 30, 90)
                        If not provided, checks from last_checked to now for continuity

        Behavior:
        - Default (no lookback_days): Checks from last_checked (or created_at) to now
        - With lookback_days: Checks from (now - lookback_days) to now
        - Always updates last_checked to now after check

        Returns:
            {
                "status": "check started",
                "task_id": "<task_id>",
                "subscription_id": <id>,
                "lookback_days": <days> or null,
                "check_mode": "continuity" or "override"
            }
        """
        subscription = self.get_object()

        # Get optional lookback_days from query params
        lookback_days_param = request.query_params.get("lookback_days")
        lookback_days = None
        check_mode = "continuity"

        if lookback_days_param:
            try:
                lookback_days = int(lookback_days_param)
                check_mode = "override"
            except ValueError:
                return Response(
                    {"error": "lookback_days must be a valid integer"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Trigger the check task
        from notifications.tasks import check_single_subscription

        task = check_single_subscription.delay(
            subscription.id, lookback_days=lookback_days
        )

        return Response(
            {
                "status": "check started",
                "task_id": task.id,
                "subscription_id": subscription.id,
                "lookback_days": lookback_days,
                "check_mode": check_mode,
            }
        )

    @action(
        detail=False, methods=["get"], url_path="check-organization/(?P<org_uid>[^/.]+)"
    )
    def check_organization_subscription(self, request, org_uid=None):
        """
        Check if the current user is subscribed to a specific organization.

        Returns:
            {
                "subscribed": true/false,
                "subscription": {...} or null
            }
        """
        try:
            subscription = NotificationSubscription.objects.get(
                user=request.user, organization__uid=org_uid, is_active=True
            )
            serializer = NotificationSubscriptionSerializer(subscription)
            return Response({"subscribed": True, "subscription": serializer.data})
        except NotificationSubscription.MultipleObjectsReturned:
            # Handle duplicate subscriptions - return the first one and log warning
            logger.warning(
                f"Multiple subscriptions found for user {request.user.id} and organization {org_uid}"
            )
            subscription = NotificationSubscription.objects.filter(
                user=request.user, organization__uid=org_uid, is_active=True
            ).first()
            serializer = NotificationSubscriptionSerializer(subscription)
            return Response({"subscribed": True, "subscription": serializer.data})
        except NotificationSubscription.DoesNotExist:
            return Response({"subscribed": False, "subscription": None})

    @action(detail=False, methods=["get"], url_path="check-entity/(?P<afm>[^/.]+)")
    def check_entity_subscription(self, request, afm=None):
        """
        Check if the current user is subscribed to a specific entity.

        Returns:
            {
                "subscribed": true/false,
                "subscription": {...} or null
            }
        """
        try:
            subscription = NotificationSubscription.objects.get(
                user=request.user, entity__afm=afm, is_active=True
            )
            serializer = NotificationSubscriptionSerializer(subscription)
            return Response({"subscribed": True, "subscription": serializer.data})
        except NotificationSubscription.MultipleObjectsReturned:
            # Handle duplicate subscriptions - return the first one and log warning
            logger.warning(
                f"Multiple subscriptions found for user {request.user.id} and entity {afm}"
            )
            subscription = NotificationSubscription.objects.filter(
                user=request.user, entity__afm=afm, is_active=True
            ).first()
            serializer = NotificationSubscriptionSerializer(subscription)
            return Response({"subscribed": True, "subscription": serializer.data})
        except NotificationSubscription.DoesNotExist:
            return Response({"subscribed": False, "subscription": None})

    @action(detail=False, methods=["get"], url_path="check-relationship")
    def check_relationship_subscription(self, request):
        """
        Check if the current user is subscribed to a specific org-entity relationship.

        Query params:
            - org_uid: Organization UID
            - entity_afm: Entity AFM

        Returns:
            {
                "subscribed": true/false,
                "subscription": {...} or null
            }
        """
        org_uid = request.query_params.get("org_uid")
        entity_afm = request.query_params.get("entity_afm")

        if not org_uid or not entity_afm:
            return Response(
                {"error": "Both org_uid and entity_afm query parameters are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            subscription = NotificationSubscription.objects.get(
                user=request.user,
                relationship_org__uid=org_uid,
                relationship_entity__afm=entity_afm,
                is_active=True,
            )
            serializer = NotificationSubscriptionSerializer(subscription)
            return Response({"subscribed": True, "subscription": serializer.data})
        except NotificationSubscription.MultipleObjectsReturned:
            # Handle duplicate subscriptions - return the first one and log warning
            logger.warning(
                f"Multiple subscriptions found for user {request.user.id}, org {org_uid}, entity {entity_afm}"
            )
            subscription = NotificationSubscription.objects.filter(
                user=request.user,
                relationship_org__uid=org_uid,
                relationship_entity__afm=entity_afm,
                is_active=True,
            ).first()
            serializer = NotificationSubscriptionSerializer(subscription)
            return Response({"subscribed": True, "subscription": serializer.data})
        except NotificationSubscription.DoesNotExist:
            return Response({"subscribed": False, "subscription": None})

    @action(
        detail=False, methods=["get"], url_path="check-person/(?P<person_name>[^/.]+)"
    )
    def check_person_subscription(self, request, person_name=None):
        """
        Check if the current user is subscribed to a specific person.

        Returns:
            {
                "subscribed": true/false,
                "subscription": {...} or null
            }
        """
        try:
            subscription = NotificationSubscription.objects.get(
                user=request.user, person_name=person_name, is_active=True
            )
            serializer = NotificationSubscriptionSerializer(subscription)
            return Response({"subscribed": True, "subscription": serializer.data})
        except NotificationSubscription.MultipleObjectsReturned:
            # Handle duplicate subscriptions - return the first one and log warning
            logger.warning(
                f"Multiple subscriptions found for user {request.user.id} and person {person_name}"
            )
            subscription = NotificationSubscription.objects.filter(
                user=request.user, person_name=person_name, is_active=True
            ).first()
            serializer = NotificationSubscriptionSerializer(subscription)
            return Response({"subscribed": True, "subscription": serializer.data})
        except NotificationSubscription.DoesNotExist:
            return Response({"subscribed": False, "subscription": None})

    @action(
        detail=False, methods=["get"], url_path="check-signer/(?P<signer_name>[^/.]+)"
    )
    def check_signer_subscription(self, request, signer_name=None):
        """
        Check if the current user is subscribed to a specific signer.

        Returns:
            {
                "subscribed": true/false,
                "subscription": {...} or null
            }
        """
        try:
            subscription = NotificationSubscription.objects.get(
                user=request.user, signer_name=signer_name, is_active=True
            )
            serializer = NotificationSubscriptionSerializer(subscription)
            return Response({"subscribed": True, "subscription": serializer.data})
        except NotificationSubscription.MultipleObjectsReturned:
            # Handle duplicate subscriptions - return the first one and log warning
            logger.warning(
                f"Multiple subscriptions found for user {request.user.id} and signer {signer_name}"
            )
            subscription = NotificationSubscription.objects.filter(
                user=request.user, signer_name=signer_name, is_active=True
            ).first()
            serializer = NotificationSubscriptionSerializer(subscription)
            return Response({"subscribed": True, "subscription": serializer.data})
        except NotificationSubscription.DoesNotExist:
            return Response({"subscribed": False, "subscription": None})

    @action(detail=True, methods=["get"], url_path="all-decisions")
    def all_decisions(self, request, pk=None):
        """
        Get all decisions from all batches for this subscription.

        GET /api/notifications/subscriptions/{id}/all-decisions/

        Query parameters:
        - page: Page number (default: 1)
        - page_size: Items per page (default: 20, max: 100)
        - sort: Sort order (recent, oldest, amount_desc, amount_asc) (default: recent)
        - is_viewed: Filter by viewed status (true/false)

        Returns:
            {
                "count": <total_count>,
                "next": <next_page_url>,
                "previous": <previous_page_url>,
                "results": [<NotificationBatchDecision objects>],
                "metadata": {
                    "subscription": <SubscriptionSerializer data>,
                    "total_batches": <number>,
                    "date_range": {"from": <date>, "to": <date>}
                }
            }
        """
        subscription = self.get_object()

        # Get all batch decisions for this subscription
        queryset = NotificationBatchDecision.objects.filter(subscription=subscription)

        # Filter by viewed status if specified
        is_viewed = request.query_params.get("is_viewed")
        if is_viewed is not None:
            queryset = queryset.filter(is_viewed=is_viewed.lower() == "true")

        # Optimize with select_related and prefetch_related
        queryset = queryset.select_related(
            "decision", "decision__organization", "decision__decision_type", "batch"
        ).prefetch_related("decision__signers", "decision__kae_amounts")

        # Apply sorting
        from api.utils.sorting import apply_decision_sorting

        sort_by = request.query_params.get("sort", "recent")
        queryset = apply_decision_sorting(
            queryset,
            sort_by,
            amount_field="decision__amount",
            date_field="decision__issue_date",
        )

        # Get metadata
        batch_stats = NotificationBatch.objects.filter(
            subscription=subscription
        ).aggregate(
            total_batches=Count("id"),
            earliest=Min("created_at"),
            latest=Max("created_at"),
        )

        # Paginate
        paginator = PageNumberPagination()
        paginator.page_size = min(int(request.query_params.get("page_size", 20)), 100)
        page = paginator.paginate_queryset(queryset, request)

        if page is not None:
            serializer = NotificationBatchDecisionSerializer(page, many=True)
            response = paginator.get_paginated_response(serializer.data)

            # Add metadata
            response.data["metadata"] = {
                "subscription": NotificationSubscriptionSerializer(subscription).data,
                "total_batches": batch_stats["total_batches"] or 0,
                "date_range": {
                    "from": (
                        batch_stats["earliest"].isoformat()
                        if batch_stats["earliest"]
                        else None
                    ),
                    "to": (
                        batch_stats["latest"].isoformat()
                        if batch_stats["latest"]
                        else None
                    ),
                },
            }

            return response

        # Fallback (shouldn't happen with pagination)
        serializer = NotificationBatchDecisionSerializer(queryset, many=True)
        return Response(serializer.data)


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for reading and managing notifications.

    Notifications are read-only from the API perspective (created by background tasks).
    Users can only see their own notifications.

    Provides read operations:
    - list: GET /api/notifications/
    - retrieve: GET /api/notifications/{id}/

    Custom actions:
    - unread_count: Get count of unread notifications
    - mark_read: Mark a notification as read
    - mark_unread: Mark a notification as unread
    - dismiss: Dismiss a notification
    - mark_all_read: Mark all notifications as read
    - dismiss_all: Dismiss all notifications

    Query parameters for list:
    - is_read: Filter by read status (true/false)
    - is_dismissed: Filter by dismissed status (true/false)
    - subscription_type: Filter by subscription type (organization/entity/relationship/person/signer/filter)
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        Filter queryset to only show current user's notifications.
        Apply query parameter filters.
        Optimize with select_related for nested relationships.
        """
        # Handle schema generation (drf-yasg) with AnonymousUser
        if not self.request.user or not self.request.user.is_authenticated:
            return Notification.objects.none()

        queryset = Notification.objects.filter(user=self.request.user)

        # Filter by read status
        is_read = self.request.query_params.get("is_read")
        if is_read is not None:
            queryset = queryset.filter(is_read=is_read.lower() == "true")

        # Filter by dismissed status
        is_dismissed = self.request.query_params.get("is_dismissed")
        if is_dismissed is not None:
            queryset = queryset.filter(is_dismissed=is_dismissed.lower() == "true")

        # Filter by subscription type
        subscription_type = self.request.query_params.get("subscription_type")
        if subscription_type:
            if subscription_type == SUBSCRIPTION_TYPE_ORGANIZATION:
                queryset = queryset.filter(subscription__organization__isnull=False)
            elif subscription_type == SUBSCRIPTION_TYPE_ENTITY:
                queryset = queryset.filter(subscription__entity__isnull=False)
            elif subscription_type == SUBSCRIPTION_TYPE_RELATIONSHIP:
                queryset = queryset.filter(
                    subscription__relationship_org__isnull=False,
                    subscription__relationship_entity__isnull=False,
                )
            elif subscription_type == SUBSCRIPTION_TYPE_PERSON:
                queryset = queryset.filter(subscription__person_name__isnull=False)
            elif subscription_type == SUBSCRIPTION_TYPE_SIGNER:
                queryset = queryset.filter(subscription__signer_name__isnull=False)
            elif subscription_type == SUBSCRIPTION_TYPE_FILTER:
                # Filter-only subscriptions have no target
                queryset = queryset.filter(
                    subscription__organization__isnull=True,
                    subscription__entity__isnull=True,
                    subscription__relationship_org__isnull=True,
                    subscription__person_name__isnull=True,
                    subscription__signer_name__isnull=True,
                )

        return queryset.select_related(
            "subscription",
            "subscription__organization",
            "subscription__entity",
            "subscription__relationship_org",
            "subscription__relationship_entity",
            "decision",
            "decision__organization",
            "decision__decision_type",
        ).order_by("-created_at")

    def get_serializer_class(self):
        """
        Use different serializers for different actions.
        """
        if self.action == "list":
            return NotificationListSerializer
        elif self.action == "retrieve":
            return NotificationDetailSerializer
        else:
            return NotificationSerializer

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        """
        Get count of unread notifications for the current user.

        Returns:
            {"unread_count": <number>}
        """
        count = Notification.objects.filter(
            user=request.user, is_read=False, is_dismissed=False
        ).count()
        return Response({"unread_count": count})

    @action(detail=True, methods=["post"], url_path="mark-read")
    def mark_read(self, request, pk=None):
        """
        Mark a notification as read.

        Returns:
            {"status": "marked as read"}
        """
        notification = self.get_object()
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save()
        return Response({"status": "marked as read"})

    @action(detail=True, methods=["post"], url_path="mark-unread")
    def mark_unread(self, request, pk=None):
        """
        Mark a notification as unread.

        Returns:
            {"status": "marked as unread"}
        """
        notification = self.get_object()
        notification.is_read = False
        notification.read_at = None
        notification.save()
        return Response({"status": "marked as unread"})

    @action(detail=True, methods=["post"])
    def dismiss(self, request, pk=None):
        """
        Dismiss a notification.

        Returns:
            {"status": "dismissed"}
        """
        notification = self.get_object()
        notification.is_dismissed = True
        notification.save()
        return Response({"status": "dismissed"})

    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, request):
        """
        Mark all unread notifications as read for the current user.

        Returns:
            {"marked_read": <count>}
        """
        count = Notification.objects.filter(
            user=request.user, is_read=False, is_dismissed=False
        ).update(is_read=True, read_at=timezone.now())
        return Response({"marked_read": count})

    @action(detail=False, methods=["post"], url_path="dismiss-all")
    def dismiss_all(self, request):
        """
        Dismiss all notifications for the current user.

        Returns:
            {"dismissed": <count>}
        """
        count = Notification.objects.filter(
            user=request.user, is_dismissed=False
        ).update(is_dismissed=True)
        return Response({"dismissed": count})


class NotificationBatchViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for reading and managing notification batches.

    Batches are read-only from the API perspective (created by background tasks).
    Users can only see their own batches.

    Provides read operations:
    - list: GET /api/notification-batches/
    - retrieve: GET /api/notification-batches/{id}/

    Custom actions:
    - decisions: Get paginated list of decisions in this batch
    - mark_read: Mark a batch as read
    - dismiss: Dismiss a batch
    - unread_count: Get count of unread batches

    Query parameters for list:
    - is_read: Filter by read status (true/false)
    - is_dismissed: Filter by dismissed status (true/false)
    - subscription_id: Filter by subscription ID
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        Filter queryset to only show current user's batches.
        Apply query parameter filters.
        Optimize with select_related for nested relationships.
        """
        # Handle schema generation (drf-yasg) with AnonymousUser
        if not self.request.user or not self.request.user.is_authenticated:
            return NotificationBatch.objects.none()

        queryset = NotificationBatch.objects.filter(user=self.request.user)

        # Filter by read status
        is_read = self.request.query_params.get("is_read")
        if is_read is not None:
            queryset = queryset.filter(is_read=is_read.lower() == "true")

        # Filter by dismissed status
        is_dismissed = self.request.query_params.get("is_dismissed")
        if is_dismissed is not None:
            queryset = queryset.filter(is_dismissed=is_dismissed.lower() == "true")

        # Filter by subscription
        subscription_id = self.request.query_params.get("subscription_id")
        if subscription_id:
            queryset = queryset.filter(subscription_id=subscription_id)

        return queryset.select_related(
            "subscription",
            "subscription__organization",
            "subscription__entity",
            "subscription__relationship_org",
            "subscription__relationship_entity",
        ).order_by("-created_at")

    def get_serializer_class(self):
        """
        Use different serializers for different actions.
        """
        if self.action == "list":
            return NotificationBatchListSerializer
        else:
            return NotificationBatchDetailSerializer

    @action(detail=True, methods=["get"], url_path="decisions")
    def decisions(self, request, pk=None):
        """
        Get paginated list of decisions in this batch.

        GET /api/notification-batches/{id}/decisions/

        Query parameters:
        - page: Page number (default: 1)
        - page_size: Items per page (default: 20, max: 100)
        - is_viewed: Filter by viewed status (true/false)
        - sort: Sort order (recent, oldest, amount_desc, amount_asc) (default: recent)

        Returns:
            {
                "count": <total_count>,
                "next": <next_page_url>,
                "previous": <previous_page_url>,
                "results": [<decision_objects>]
            }
        """
        from notifications.serializers import NotificationBatchDecisionSerializer
        from rest_framework.pagination import PageNumberPagination

        batch = self.get_object()

        # Get batch decisions queryset
        queryset = NotificationBatchDecision.objects.filter(batch=batch)

        # Filter by viewed status
        is_viewed = request.query_params.get("is_viewed")
        if is_viewed is not None:
            queryset = queryset.filter(is_viewed=is_viewed.lower() == "true")

        # Optimize with select_related and prefetch_related
        queryset = queryset.select_related(
            "decision", "decision__organization", "decision__decision_type"
        ).prefetch_related("decision__signers", "decision__kae_amounts")

        # Apply sorting with proper NULL handling
        from api.utils.sorting import apply_decision_sorting

        sort_by = request.query_params.get("sort", "recent")
        queryset = apply_decision_sorting(
            queryset,
            sort_by,
            amount_field="decision__amount",
            date_field="decision__issue_date",
        )

        # Paginate
        paginator = PageNumberPagination()
        paginator.page_size = min(int(request.query_params.get("page_size", 20)), 100)
        page = paginator.paginate_queryset(queryset, request)

        if page is not None:
            serializer = NotificationBatchDecisionSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = NotificationBatchDecisionSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="mark-read")
    def mark_read(self, request, pk=None):
        """
        Mark a specific batch as read.

        POST /api/notification-batches/{id}/mark-read/

        Returns:
            {"status": "marked as read", "batch_id": <id>}
        """
        batch = self.get_object()
        batch.mark_as_read()
        return Response({"status": "marked as read", "batch_id": batch.id})

    @action(detail=True, methods=["post"], url_path="dismiss")
    def dismiss(self, request, pk=None):
        """
        Dismiss a specific batch.

        POST /api/notification-batches/{id}/dismiss/

        Returns:
            {"status": "dismissed", "batch_id": <id>}
        """
        batch = self.get_object()
        batch.dismiss()
        return Response({"status": "dismissed", "batch_id": batch.id})

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        """
        Get the count of unread batches for the current user.

        GET /api/notification-batches/unread-count/

        Returns:
            {"unread_count": <count>}
        """
        count = NotificationBatch.objects.filter(
            user=request.user, is_read=False, is_dismissed=False
        ).count()
        return Response({"unread_count": count})
