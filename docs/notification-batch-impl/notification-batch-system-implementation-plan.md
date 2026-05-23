# Notification Batch System - Implementation Plan

## Executive Summary

Transition from individual notification-per-decision model to a batched notification system where one notification batch captures multiple matching decisions. This prevents notification spam for generic subscriptions and provides a better UX.

**Status:** Planning Phase
**Target Branch:** `notifications`
**Estimated Effort:** 3-5 days

---

## Current State Analysis

### Existing Models

#### NotificationSubscription
```python
# Location: backend/notifications/models/notification_subscription.py
- user: ForeignKey
- organization/entity/relationship fields (target)
- person_name, signer_name (target)
- keywords: JSONField (currently AND logic only)
- amount_min, amount_max: Decimal
- decision_types: JSONField
- check_frequency: CharField (daily/weekly/manual)
- last_checked: DateTimeField
```

#### Notification (Current - WILL BE REPLACED)
```python
# Location: backend/notifications/models/notification.py
- user: ForeignKey
- subscription: ForeignKey
- decision: ForeignKey  # ← ONE notification per decision (PROBLEM)
- match_reason: CharField
- match_details: JSONField
- is_read, is_dismissed: BooleanField
- created_at, read_at: DateTimeField

# UNIQUE CONSTRAINT: (user, subscription, decision)
# This prevents duplicates but creates notification spam
```

### Current Task Flow

```python
# Location: backend/notifications/tasks/notification_tasks.py

check_subscriptions_for_new_decisions()
  ↓
  for each active subscription:
    ↓
    find_matching_decisions(subscription, since=last_checked)
      ↓ (queries Decision model with filters)
    create_notifications_for_matches(subscription, matching_decisions)
      ↓
      for each decision:  # ← CREATES ONE NOTIFICATION PER DECISION
        Notification.objects.bulk_create([...])
```

**Problem:** Generic subscription (e.g., "amount > €10,000") finds 500 decisions → Creates 500 Notification records → User overwhelmed.

### Current API Endpoints

```
NotificationSubscriptionViewSet:
  - GET    /api/notifications/subscriptions/
  - POST   /api/notifications/subscriptions/
  - GET    /api/notifications/subscriptions/{id}/
  - PUT    /api/notifications/subscriptions/{id}/
  - DELETE /api/notifications/subscriptions/{id}/
  - POST   /api/notifications/subscriptions/{id}/check-now/
  - GET    /api/notifications/subscriptions/check-organization/{uid}/
  - GET    /api/notifications/subscriptions/check-entity/{afm}/
  - GET    /api/notifications/subscriptions/check-relationship/

NotificationViewSet:
  - GET  /api/notifications/
  - GET  /api/notifications/{id}/
  - GET  /api/notifications/unread-count/
  - POST /api/notifications/{id}/mark-read/
  - POST /api/notifications/{id}/mark-unread/
  - POST /api/notifications/{id}/dismiss/
  - POST /api/notifications/mark-all-read/
  - POST /api/notifications/dismiss-all/
```

### Current Frontend Components

```javascript
// NotificationSidebar.js - Main UI
- Shows notifications and subscriptions in tabs
- Click notification → navigates to decision detail page
- Shows unread count
- Can dismiss notifications

// API: frontend/src/api/notifications.js
- getNotifications()
- getSubscriptions()
- markNotificationRead()
- dismissNotification()
- // etc.
```

---

## Target Architecture

### New Models

#### NotificationBatch (NEW)
```python
# Location: backend/notifications/models/notification_batch.py

class NotificationBatch(models.Model):
    """
    A batch of decisions that matched a subscription during a check.
    Replaces individual Notification records to prevent spam.
    """

    subscription = models.ForeignKey(
        'notifications.NotificationSubscription',
        on_delete=models.CASCADE,
        related_name='batches'
    )

    user = models.ForeignKey(
        'users.CustomUser',
        on_delete=models.CASCADE,
        related_name='notification_batches'
    )

    # Time window that was checked
    check_window_start = models.DateTimeField(
        help_text="Start of the time range checked (usually subscription.last_checked)"
    )

    check_window_end = models.DateTimeField(
        help_text="End of the time range checked (usually now())"
    )

    # Denormalized counts for quick display
    match_count = models.IntegerField(
        help_text="Total number of decisions matched in this batch"
    )

    # Aggregate statistics (for display without querying all decisions)
    aggregate_stats = models.JSONField(
        help_text="Stats like total_amount, avg_amount, decision_type_breakdown, etc."
    )

    # Status
    is_read = models.BooleanField(default=False)
    is_dismissed = models.BooleanField(default=False)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    # Many-to-many with decisions through junction table
    decisions = models.ManyToManyField(
        'core.Decision',
        through='NotificationBatchDecision',
        related_name='notification_batches'
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read']),
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['subscription', 'created_at']),
        ]
```

#### NotificationBatchDecision (NEW)
```python
# Location: backend/notifications/models/notification_batch.py

class NotificationBatchDecision(models.Model):
    """
    Junction table connecting batches to decisions.
    Stores why each decision matched (for display).
    """

    batch = models.ForeignKey(
        'notifications.NotificationBatch',
        on_delete=models.CASCADE,
        related_name='batch_decisions'
    )

    decision = models.ForeignKey(
        'core.Decision',
        on_delete=models.CASCADE,
        related_name='batch_memberships'
    )

    # Why this decision was included
    match_reason = models.CharField(
        max_length=50,
        help_text="Primary reason: organization, entity, keyword_match, etc."
    )

    match_details = models.JSONField(
        help_text="Specific details: which keywords matched, amounts, etc."
    )

    # Optional: track if user viewed this specific decision
    is_viewed = models.BooleanField(
        default=False,
        help_text="Whether user clicked through to this decision"
    )

    class Meta:
        unique_together = [('batch', 'decision')]
        indexes = [
            models.Index(fields=['batch']),
            models.Index(fields=['decision']),
        ]
```

#### NotificationSubscription (MODIFIED)
```python
# ADD FIELD for AND/OR keyword logic:

keyword_match_operator = models.CharField(
    max_length=3,
    choices=[('AND', 'All keywords must match'), ('OR', 'Any keyword matches')],
    default='AND',
    help_text="How to combine multiple keywords"
)
```

### Storage Estimates

**Scenario:** 100 active users, 5 subscriptions each, daily checks, avg 50 decisions matched

- **NotificationBatch:** 500 rows/day = ~180k rows/year
  - Row size: ~200 bytes (fields + indexes)
  - Annual: ~36 MB

- **NotificationBatchDecision:** 25,000 rows/day = ~9M rows/year
  - Row size: ~100 bytes (3 integers + small JSON)
  - Annual: ~900 MB

**Total annual growth:** ~1 GB (very manageable)

With 6-month cleanup policy: ~500 MB steady state.

---

## Implementation Tasks

### Phase 1: Data Model Migration

#### Task 1.1: Create New Models
**File:** `backend/notifications/models/notification_batch.py`

- [ ] Create `NotificationBatch` model
- [ ] Create `NotificationBatchDecision` model
- [ ] Add to `backend/notifications/models/__init__.py`
- [ ] Generate migration: `python manage.py makemigrations`

**Acceptance Criteria:**
- Models can be created in Django admin
- Foreign keys resolve correctly
- Indexes are created

#### Task 1.2: Update NotificationSubscription
**File:** `backend/notifications/models/notification_subscription.py`

- [ ] Add `keyword_match_operator` field (default='AND')
- [ ] Generate migration: `python manage.py makemigrations`
- [ ] Run migration: `python manage.py migrate`

**Acceptance Criteria:**
- Existing subscriptions have operator='AND'
- Field appears in admin

#### Task 1.3: Keep Old Notification Model (Temporarily)
**Decision:** Keep the old `Notification` model during transition
- Allows testing new system alongside old
- Can migrate data if needed
- Can be removed in Phase 4 cleanup

---

### Phase 2: Backend Task Logic

#### Task 2.1: Update Keyword Matching Logic
**File:** `backend/notifications/tasks/notification_tasks.py`

**Function:** `find_matching_decisions()`

Current (AND only):
```python
if subscription.keywords:
    keyword_query = Q()
    for keyword in subscription.keywords:
        keyword_query &= Q(subject__icontains=keyword)  # AND
    queryset = queryset.filter(keyword_query)
```

New (AND/OR support):
```python
if subscription.keywords:
    keyword_query = Q()
    operator = subscription.keyword_match_operator or 'AND'

    for keyword in subscription.keywords:
        if operator == 'AND':
            keyword_query &= Q(subject__icontains=keyword)
        else:  # OR
            keyword_query |= Q(subject__icontains=keyword)

    if operator == 'OR' and keyword_query:
        queryset = queryset.filter(keyword_query)
    elif operator == 'AND' and keyword_query:
        queryset = queryset.filter(keyword_query)
```

- [ ] Implement AND/OR logic
- [ ] Update `determine_match_reason()` to capture which keywords matched

**Acceptance Criteria:**
- Subscription with keywords=['contract', 'agreement'], operator='OR' matches either keyword
- Subscription with keywords=['urgent', 'contract'], operator='AND' requires both
- Tests pass

#### Task 2.2: Create Batch Creation Function
**File:** `backend/notifications/tasks/notification_tasks.py`

**New Function:**
```python
def create_notification_batch(subscription, matching_decisions, check_window_start, check_window_end):
    """
    Create a NotificationBatch for matched decisions.

    Args:
        subscription: NotificationSubscription instance
        matching_decisions: QuerySet of Decision objects
        check_window_start: datetime when check started
        check_window_end: datetime when check ended

    Returns:
        NotificationBatch instance or None if no matches
    """
    # Don't create empty batches
    if not matching_decisions.exists():
        return None

    # Calculate aggregates
    from django.db.models import Sum, Avg, Count

    stats = matching_decisions.aggregate(
        total_amount=Sum('amount'),
        avg_amount=Avg('amount'),
        count=Count('id')
    )

    # Decision type breakdown
    type_breakdown = matching_decisions.values('decision_type__label').annotate(
        count=Count('id')
    ).order_by('-count')[:10]

    aggregate_stats = {
        'total_amount': float(stats['total_amount'] or 0),
        'avg_amount': float(stats['avg_amount'] or 0),
        'decision_count': stats['count'],
        'top_decision_types': list(type_breakdown)
    }

    # Create batch
    batch = NotificationBatch.objects.create(
        subscription=subscription,
        user=subscription.user,
        check_window_start=check_window_start,
        check_window_end=check_window_end,
        match_count=stats['count'],
        aggregate_stats=aggregate_stats,
        is_read=False,
        is_dismissed=False
    )

    # Create junction table entries
    batch_decisions = []
    for decision in matching_decisions[:1000]:  # Limit to prevent memory issues
        match_reason, match_details = determine_match_reason(subscription, decision)

        batch_decisions.append(
            NotificationBatchDecision(
                batch=batch,
                decision=decision,
                match_reason=match_reason,
                match_details=match_details
            )
        )

    NotificationBatchDecision.objects.bulk_create(
        batch_decisions,
        ignore_conflicts=True
    )

    logger.info(
        f"Created NotificationBatch {batch.id} for subscription {subscription.id}: "
        f"{batch.match_count} decisions matched"
    )

    return batch
```

- [ ] Implement function
- [ ] Handle large result sets (pagination/chunking)
- [ ] Add logging

**Acceptance Criteria:**
- Batch created with correct counts
- Junction table populated
- Aggregate stats calculated correctly

#### Task 2.3: Update Main Task Function
**File:** `backend/notifications/tasks/notification_tasks.py`

**Function:** `check_subscriptions_for_new_decisions()`

Changes:
```python
# OLD:
for subscription in active_subscriptions:
    matching_decisions = find_matching_decisions(subscription, check_since)
    created_count = create_notifications_for_matches(subscription, matching_decisions)
    notifications_created += created_count

# NEW:
for subscription in active_subscriptions:
    check_start = subscription.last_checked or now - timedelta(days=30)
    check_end = now

    matching_decisions = find_matching_decisions(subscription, check_since=check_start)

    batch = create_notification_batch(
        subscription,
        matching_decisions,
        check_window_start=check_start,
        check_window_end=check_end
    )

    if batch:
        batches_created += 1
        total_decisions_matched += batch.match_count

    subscription.last_checked = check_end
    subscription.save()

return {
    "batches_created": batches_created,
    "total_decisions_matched": total_decisions_matched
}
```

- [ ] Update main task loop
- [ ] Update return value structure
- [ ] Update logging messages

**Acceptance Criteria:**
- Task creates batches instead of individual notifications
- last_checked updated correctly
- Logging shows batch creation

#### Task 2.4: Update check_single_subscription Task
**File:** `backend/notifications/tasks/notification_tasks.py`

Similar changes for manual "check now" functionality.

- [ ] Update to create batch
- [ ] Support lookback_days parameter
- [ ] Return batch info

---

### Phase 3: API & Serializers

#### Task 3.1: Create Batch Serializers
**File:** `backend/notifications/serializers/notification_batch.py` (new file)

```python
class NotificationBatchDecisionSerializer(serializers.ModelSerializer):
    """Serialize a decision within a batch."""
    decision = DecisionListSerializer(read_only=True)

    class Meta:
        model = NotificationBatchDecision
        fields = [
            'decision',
            'match_reason',
            'match_details',
            'is_viewed'
        ]


class NotificationBatchListSerializer(serializers.ModelSerializer):
    """
    List serializer - light weight for sidebar display.
    """
    subscription_display = serializers.SerializerMethodField()

    class Meta:
        model = NotificationBatch
        fields = [
            'id',
            'subscription',
            'subscription_display',
            'match_count',
            'aggregate_stats',
            'is_read',
            'is_dismissed',
            'created_at',
            'check_window_start',
            'check_window_end'
        ]

    def get_subscription_display(self, obj):
        # Return friendly name like "Signer: John Doe" or "Organization: Ministry of Finance"
        return obj.subscription.get_display_name()


class NotificationBatchDetailSerializer(serializers.ModelSerializer):
    """
    Detail serializer - includes decisions (paginated separately via endpoint).
    """
    subscription = NotificationSubscriptionSerializer(read_only=True)
    # Don't include all decisions here - too heavy
    # Decisions fetched via separate endpoint: /batches/{id}/decisions/

    class Meta:
        model = NotificationBatch
        fields = [
            'id',
            'subscription',
            'match_count',
            'aggregate_stats',
            'is_read',
            'is_dismissed',
            'created_at',
            'read_at',
            'check_window_start',
            'check_window_end'
        ]
```

- [ ] Create serializers
- [ ] Add to `__init__.py`

#### Task 3.2: Create Batch ViewSet
**File:** `backend/notifications/views.py`

```python
class NotificationBatchViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for notification batches.

    Endpoints:
    - GET /api/notifications/batches/
    - GET /api/notifications/batches/{id}/
    - GET /api/notifications/batches/{id}/decisions/
    - POST /api/notifications/batches/{id}/mark-read/
    - POST /api/notifications/batches/{id}/dismiss/
    - GET /api/notifications/batches/unread-count/
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return NotificationBatch.objects.filter(
            user=self.request.user
        ).select_related('subscription').order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'list':
            return NotificationBatchListSerializer
        return NotificationBatchDetailSerializer

    @action(detail=True, methods=['get'], url_path='decisions')
    def decisions(self, request, pk=None):
        """
        Get decisions in this batch (paginated).

        Query params:
        - limit, offset (pagination)
        - search (filter by decision subject)
        - decision_type (filter by type)
        - sort (amount_asc, amount_desc, date_asc, date_desc)
        """
        batch = self.get_object()

        # Get decisions through junction table
        batch_decisions = NotificationBatchDecision.objects.filter(
            batch=batch
        ).select_related('decision', 'decision__organization', 'decision__decision_type')

        # Apply filters
        search = request.query_params.get('search')
        if search:
            batch_decisions = batch_decisions.filter(
                decision__subject__icontains=search
            )

        decision_type = request.query_params.get('decision_type')
        if decision_type:
            batch_decisions = batch_decisions.filter(
                decision__decision_type__uid=decision_type
            )

        # Sorting
        sort = request.query_params.get('sort', 'date_desc')
        sort_map = {
            'amount_asc': 'decision__amount',
            'amount_desc': '-decision__amount',
            'date_asc': 'decision__publish_timestamp',
            'date_desc': '-decision__publish_timestamp'
        }
        batch_decisions = batch_decisions.order_by(sort_map.get(sort, '-decision__publish_timestamp'))

        # Paginate
        paginator = LimitOffsetPagination()
        paginator.default_limit = 50
        page = paginator.paginate_queryset(batch_decisions, request)

        serializer = NotificationBatchDecisionSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @action(detail=True, methods=['post'], url_path='mark-read')
    def mark_read(self, request, pk=None):
        batch = self.get_object()
        batch.is_read = True
        batch.read_at = timezone.now()
        batch.save()
        return Response({'status': 'marked as read'})

    @action(detail=True, methods=['post'])
    def dismiss(self, request, pk=None):
        batch = self.get_object()
        batch.is_dismissed = True
        batch.save()
        return Response({'status': 'dismissed'})

    @action(detail=False, methods=['get'], url_path='unread-count')
    def unread_count(self, request):
        count = NotificationBatch.objects.filter(
            user=request.user,
            is_read=False,
            is_dismissed=False
        ).count()
        return Response({'unread_count': count})

    @action(detail=False, methods=['post'], url_path='mark-all-read')
    def mark_all_read(self, request):
        count = NotificationBatch.objects.filter(
            user=request.user,
            is_read=False
        ).update(is_read=True, read_at=timezone.now())
        return Response({'marked_read': count})
```

- [ ] Create ViewSet
- [ ] Add URL routing in `backend/notifications/urls.py`

#### Task 3.3: Update NotificationSubscription Serializer
**File:** `backend/notifications/serializers/notification_subscription.py`

Add `keyword_match_operator` to serializers:
- [ ] Add to `NotificationSubscriptionSerializer`
- [ ] Add to `NotificationSubscriptionCreateSerializer`
- [ ] Add validation

#### Task 3.4: Add Statistics Endpoint to Subscription
**File:** `backend/notifications/views.py` - `NotificationSubscriptionViewSet`

```python
@action(detail=True, methods=['get'])
def statistics(self, request, pk=None):
    """
    Get statistics about all batches for this subscription.
    """
    subscription = self.get_object()
    batches = NotificationBatch.objects.filter(subscription=subscription)

    total_batches = batches.count()
    total_decisions = batches.aggregate(Sum('match_count'))['match_count__sum'] or 0
    unread_batches = batches.filter(is_read=False, is_dismissed=False).count()

    return Response({
        'total_batches': total_batches,
        'total_decisions_ever_matched': total_decisions,
        'unread_batches': unread_batches,
        'last_checked': subscription.last_checked
    })
```

- [ ] Add endpoint
- [ ] Test

---

### Phase 4: Frontend Updates

#### Task 4.1: Update API Module
**File:** `frontend/src/api/notifications.js`

```javascript
// New functions for batches
export async function getNotificationBatches(filters = {}) {
    const params = new URLSearchParams(filters);
    const response = await fetch(`/api/notifications/batches/?${params}`);
    return response.json();
}

export async function getNotificationBatch(id) {
    const response = await fetch(`/api/notifications/batches/${id}/`);
    return response.json();
}

export async function getBatchDecisions(batchId, params = {}) {
    const queryParams = new URLSearchParams(params);
    const response = await fetch(
        `/api/notifications/batches/${batchId}/decisions/?${queryParams}`
    );
    return response.json();
}

export async function markBatchRead(id) {
    const response = await fetch(
        `/api/notifications/batches/${id}/mark-read/`,
        { method: 'POST' }
    );
    return response.json();
}

export async function dismissBatch(id) {
    const response = await fetch(
        `/api/notifications/batches/${id}/dismiss/`,
        { method: 'POST' }
    );
    return response.json();
}

export async function getBatchUnreadCount() {
    const response = await fetch('/api/notifications/batches/unread-count/');
    return response.json();
}

// Update subscription create/update to include keyword_match_operator
```

- [ ] Add batch API functions
- [ ] Update subscription functions to include `keyword_match_operator`

#### Task 4.2: Update NotificationSidebar
**File:** `frontend/src/components/NotificationSidebar.js`

Changes needed:
```javascript
// Instead of loading individual notifications:
const [batches, setBatches] = useState([]);

// Load function:
const loadData = async () => {
    const [subsData, batchesData] = await Promise.all([
        getSubscriptions(),
        getNotificationBatches()
    ]);
    setSubscriptions(subsData);
    setBatches(batchesData);
};

// Display batches:
{batches.map(batch => (
    <div key={batch.id} className="notification-batch">
        <div className="batch-header">
            <strong>{batch.subscription_display}</strong>
            <span className="match-count">{batch.match_count} decisions</span>
        </div>
        <div className="batch-stats">
            Total: €{batch.aggregate_stats.total_amount.toLocaleString()}
        </div>
        <button onClick={() => handleBatchClick(batch)}>
            View Decisions
        </button>
    </div>
))}

// Click handler:
const handleBatchClick = async (batch) => {
    await markBatchRead(batch.id);
    navigate(`/notification-results/${batch.id}`);
};
```

- [ ] Update state management
- [ ] Update UI to show batches
- [ ] Update click handlers
- [ ] Update unread count to use batch count

#### Task 4.3: Create NotificationResultsPage
**File:** `frontend/src/pages/NotificationResultsPage.js` (NEW)

This page displays decisions from a notification batch. Reuse logic from EntityDetailPage.

```javascript
const NotificationResultsPage = () => {
    const { batchId } = useParams();
    const [batch, setBatch] = useState(null);
    const [decisions, setDecisions] = useState([]);
    const [loading, setLoading] = useState(true);

    // Reuse filtering/sorting logic from EntityDetailPage
    const { sortBy, searchQuery, selectedTypes, ... } = useUrlFilters();

    useEffect(() => {
        async function loadBatch() {
            const batchData = await getNotificationBatch(batchId);
            setBatch(batchData);

            const decisionsData = await getBatchDecisions(batchId, {
                sort: sortBy,
                search: searchQuery,
                // ... other filters
            });
            setDecisions(decisionsData.results);
        }
        loadBatch();
    }, [batchId, sortBy, searchQuery]);

    return (
        <div className="notification-results-page">
            <h1>Notification Results</h1>
            <div className="batch-summary">
                <p>Subscription: {batch?.subscription?.alias || 'Unnamed'}</p>
                <p>{batch?.match_count} decisions matched</p>
                <p>Total Amount: €{batch?.aggregate_stats.total_amount}</p>
            </div>

            {/* Reuse DecisionList component */}
            <DecisionList
                decisions={decisions}
                loading={loading}
                // ... props
            />
        </div>
    );
};
```

- [ ] Create new page component
- [ ] Add route in App.js: `/notification-results/:batchId`
- [ ] Reuse decision display components
- [ ] Add filtering/sorting UI
- [ ] Show batch metadata

#### Task 4.4: Update Subscription Edit UI
**File:** `frontend/src/components/NotificationSidebar.js` or new modal component

Add UI for editing subscriptions:
```javascript
// Keyword operator toggle
<select
    value={subscription.keyword_match_operator}
    onChange={(e) => updateKeywordOperator(e.target.value)}
>
    <option value="AND">All keywords (AND)</option>
    <option value="OR">Any keyword (OR)</option>
</select>
```

- [ ] Add edit button to each subscription
- [ ] Create edit modal/form
- [ ] Include keyword operator selector
- [ ] Test update functionality

#### Task 4.5: Update Translations
**Files:**
- `frontend/src/locales/el.json`
- `frontend/src/locales/en.json`

Add translations:
```json
{
    "notifications": {
        "batch": {
            "matched_decisions": "{{count}} decisions matched",
            "total_amount": "Total Amount",
            "view_decisions": "View Decisions",
            "keyword_operator_and": "All keywords must match",
            "keyword_operator_or": "Any keyword matches"
        }
    }
}
```

- [ ] Add Greek translations
- [ ] Add English translations

---

### Phase 5: Testing

#### Task 5.1: Backend Model Tests
**File:** `backend/notifications/tests/test_models.py` (new)

```python
class TestNotificationBatch:
    def test_create_batch(self):
        # Test batch creation
        pass

    def test_batch_decision_relationship(self):
        # Test ManyToMany relationship
        pass

    def test_aggregate_stats(self):
        # Test stats calculation
        pass
```

- [ ] Create model tests
- [ ] Test constraints
- [ ] Test relationships

#### Task 5.2: Backend Task Tests
**File:** `backend/notifications/tests/test_notification_tasks.py` (update existing)

```python
def test_create_notification_batch():
    # Test batch creation from matching decisions
    pass

def test_keyword_and_operator():
    # Test AND logic
    pass

def test_keyword_or_operator():
    # Test OR logic
    pass

def test_check_subscriptions_creates_batches():
    # Test main task creates batches not individual notifications
    pass
```

- [ ] Update existing tests
- [ ] Add batch creation tests
- [ ] Add AND/OR keyword tests

#### Task 5.3: API Tests
**File:** `backend/notifications/tests/test_api.py` (new)

```python
def test_list_batches():
    pass

def test_batch_detail():
    pass

def test_batch_decisions_endpoint():
    pass

def test_mark_batch_read():
    pass

def test_batch_unread_count():
    pass
```

- [ ] Create API tests
- [ ] Test permissions
- [ ] Test pagination

#### Task 5.4: Integration Tests
**File:** `backend/notifications/tests/integration/test_batch_flow.py` (new)

```python
def test_complete_batch_flow():
    """
    1. Create subscription
    2. Create matching decisions
    3. Run task
    4. Verify batch created
    5. Retrieve via API
    6. Mark as read
    """
    pass
```

- [ ] Create end-to-end test
- [ ] Test with real-world scenarios

---

### Phase 6: Migration Strategy

#### Task 6.1: Data Migration (Optional)
If you want to migrate existing Notification records to batches:

```python
# Migration script: backend/notifications/management/commands/migrate_to_batches.py

def handle(self):
    # Group existing notifications by (user, subscription, created_at.date)
    # Create NotificationBatch for each group
    # Create NotificationBatchDecision entries
    # Mark old notifications as migrated (add flag)
```

- [ ] Decide: migrate old data or start fresh?
- [ ] If migrating, create management command
- [ ] Test migration on copy of production data

#### Task 6.2: Deprecation Plan
**Option A: Hard cutover**
- Remove old Notification model immediately after batch system deployed
- Simpler, cleaner

**Option B: Gradual transition**
- Keep both systems for 1-2 weeks
- Monitor for issues
- More cautious

Decision: [ ] To be determined

---

### Phase 7: Cleanup & Maintenance

#### Task 7.1: Cleanup Task
**File:** `backend/notifications/tasks/cleanup_tasks.py` (new)

```python
@shared_task
def cleanup_old_notification_batches():
    """
    Delete notification batches older than 6 months.
    Run weekly via Celery Beat.
    """
    cutoff = timezone.now() - timedelta(days=180)

    batches_to_delete = NotificationBatch.objects.filter(
        created_at__lt=cutoff
    )

    count = batches_to_delete.count()
    batches_to_delete.delete()  # CASCADE deletes NotificationBatchDecision

    logger.info(f"Cleaned up {count} old notification batches")
    return {'deleted': count}
```

- [ ] Create cleanup task
- [ ] Add to Celery Beat schedule
- [ ] Test

#### Task 7.2: Remove Old Notification Model
**After batch system is stable:**

- [ ] Remove old `Notification` model
- [ ] Remove old endpoints (or keep for backwards compatibility?)
- [ ] Create migration to drop table
- [ ] Update docs

#### Task 7.3: Admin Interface
**File:** `backend/notifications/admin.py`

```python
@admin.register(NotificationBatch)
class NotificationBatchAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'subscription', 'match_count', 'created_at', 'is_read']
    list_filter = ['is_read', 'is_dismissed', 'created_at']
    search_fields = ['user__username', 'subscription__alias']
    readonly_fields = ['created_at', 'aggregate_stats']
```

- [ ] Create admin interfaces
- [ ] Add inline for NotificationBatchDecision
- [ ] Test

---

## Deployment Checklist

### Database
- [ ] Backup production database
- [ ] Run migrations in staging first
- [ ] Verify indexes created
- [ ] Check migration time (shouldn't be long if tables are new)

### Backend
- [ ] Deploy with old system still working
- [ ] Monitor Celery tasks
- [ ] Check logs for batch creation
- [ ] Verify no errors

### Frontend
- [ ] Build and deploy new frontend
- [ ] Test sidebar shows batches
- [ ] Test navigation to results page
- [ ] Verify unread count updates

### Monitoring
- [ ] Set up alerts for:
  - Batch creation failures
  - Large batches (>1000 decisions)
  - API errors on batch endpoints
- [ ] Monitor database growth
- [ ] Check query performance

---

## Testing Scenarios

### Scenario 1: Generic Subscription
```
Given: User creates subscription "amount > €5,000"
When: Daily task runs and finds 500 matching decisions
Then:
  - One NotificationBatch created (not 500 notifications)
  - match_count = 500
  - aggregate_stats calculated
  - User sees "500 decisions matched"
```

### Scenario 2: Keyword OR Logic
```
Given: User creates subscription with keywords=['contract', 'agreement'], operator='OR'
When: Task finds decisions with either keyword
Then:
  - Batch contains all decisions with 'contract' OR 'agreement'
  - match_details shows which keyword matched
```

### Scenario 3: Empty Batch
```
Given: Subscription exists but no new decisions match
When: Task runs
Then:
  - No NotificationBatch created
  - last_checked updated
  - No user notification
```

### Scenario 4: View Batch Results
```
Given: NotificationBatch with 100 decisions
When: User clicks batch in sidebar
Then:
  - Navigates to /notification-results/{id}
  - Sees list of 100 decisions
  - Can filter, sort, search
  - Batch marked as read
```

---

## Success Metrics

After deployment, monitor:

1. **Notification spam reduction**
   - Before: X individual notifications per user per day
   - After: Y batches per user per day (should be much less)

2. **User engagement**
   - Click-through rate on batches
   - Time spent on results page
   - Number of batches dismissed vs read

3. **Performance**
   - Batch creation time
   - API response times
   - Database size growth

4. **System health**
   - Task success rate
   - Error logs
   - Memory usage

---

## Open Questions

1. **Batch size limits:** Should we cap batches at 1000 decisions and create multiple batches if needed?

2. **Notification delivery:** Should we send email/push notifications for batches? If so, what's the threshold (only if >X decisions)?

3. **Partial reads:** Should we track which individual decisions in a batch were viewed? (Currently supported via `is_viewed` field)

4. **Update handling:** If a decision in a batch is updated (amount changes), should the batch update too, or stay historical?

5. **Subscription changes:** If user modifies subscription (adds keyword), should it apply to existing batches or only future ones?

---

## Timeline Estimate

- **Phase 1 (Models):** 0.5 day
- **Phase 2 (Tasks):** 1 day
- **Phase 3 (API):** 1 day
- **Phase 4 (Frontend):** 1.5 days
- **Phase 5 (Testing):** 1 day
- **Phase 6 (Migration):** 0.5 day (if needed)
- **Phase 7 (Cleanup):** 0.5 day

**Total:** ~6 days (with buffer)

---

## Notes

- Start with Phase 1-3 (backend) and test thoroughly
- Can deploy backend before frontend (old UI will just not show batches)
- Keep old Notification model during transition for safety
- Monitor closely after deployment
- Consider feature flag to toggle between old/new system

---

**Status:** Ready for implementation
**Last Updated:** 2026-03-08
**Author:** Development Team
