# Notification Batch System - Design Decisions

**Related Documents:**
- [Full Implementation Plan](./notification-batch-system-implementation-plan.md)
- [Quick Checklist](./notification-batch-checklist.md)

This document captures key design decisions that should be made before implementation.

---

## Decision 1: Batch Size Limits

### Context
A very generic subscription (e.g., "amount > €100") could match thousands of decisions. Should we cap batch sizes?

### Options

**A. No limit - One batch contains all matches**
```
Pros:
- Simple logic
- True representation of "what matched"
- User sees everything

Cons:
- Large batches slow to load
- Junction table could have millions of rows
- Memory issues when processing
```

**B. Cap at 1000 decisions per batch**
```python
# If more than 1000 matches, create multiple batches
if matching_count > 1000:
    # Batch 1: decisions 0-999
    # Batch 2: decisions 1000-1999
    # etc.
```
```
Pros:
- Keeps batches manageable
- Better UX (pagination)
- Prevents memory issues

Cons:
- User sees multiple notifications for same subscription/check
- More complex logic
```

**C. Sample/Top N approach**
```python
# Store only top 1000 by amount, note that more exist
batch.metadata = {
    "total_matches": 5000,
    "stored_matches": 1000,
    "sampling_strategy": "top_by_amount"
}
```
```
Pros:
- Shows most important decisions
- Keeps batch small
- Clear to user

Cons:
- Not comprehensive
- User might miss something
```

### Recommendation
**Option B** - Cap at 1000 with multiple batches. Add a field to batch:
```python
batch_sequence = IntegerField(default=1)  # 1 of 3, 2 of 3, etc.
batch_group_id = UUIDField()  # Groups related batches
```

Display in UI: "Your subscription matched 3,500 decisions (Batch 1 of 4)"

### Decision: [ ] To be decided

---

## Decision 2: Email/Push Notifications

### Context
Should we send email/push notifications when batches are created, or only show in-app?

### Options

**A. No external notifications - in-app only**
```
Pros:
- No spam
- Simple
- User checks when they want

Cons:
- User might miss important alerts
- Less engagement
```

**B. Email for every batch**
```
Pros:
- User always informed
- High engagement

Cons:
- Email spam for active subscriptions
- Unsubscribe risk
```

**C. Configurable per subscription**
```python
notification_method = CharField(
    choices=['in_app', 'email', 'both'],
    default='in_app'
)

# Or threshold-based:
email_threshold = IntegerField(
    null=True,
    help_text="Send email only if batch has >= X decisions"
)
```
```
Pros:
- User control
- Flexible
- Can set "only email me if >10 decisions"

Cons:
- More complex
- Email infrastructure needed
```

### Recommendation
**Option A** for MVP, add Option C later based on user feedback.

### Decision: [ ] In-app only for now

---

## Decision 3: Historical Batch Updates

### Context
If a decision in a batch is later updated (e.g., amount changes from €10k→€15k), should the batch reflect this?

### Options

**A. Immutable batches (snapshot)**
```python
# Batch shows decision as it was when matched
# If decision deleted, batch still shows it existed
```
```
Pros:
- Historical accuracy
- "You were notified about this" stays true
- Audit trail

Cons:
- Might show outdated data
```

**B. Live batches (dynamic)**
```python
# Batch always shows current decision state
# If decision deleted, remove from batch
```
```
Pros:
- Always up-to-date
- No confusion

Cons:
- "47 decisions" might show 45 if 2 deleted
- Confusing for user
```

**C. Hybrid with indicator**
```python
# Store original match_details
# Show current decision data
# Highlight if changed: "Amount was €10k, now €15k"
```
```
Pros:
- Best of both worlds
- User sees changes

Cons:
- Complex to implement
```

### Recommendation
**Option A** - Immutable batches. This matches how email/notification systems work - you're notified at a point in time.

Store decision snapshot in `NotificationBatchDecision.match_details`:
```python
match_details = {
    "decision_ada": "ΨΩΨ7465ΧΛΔ-ΒΡ6",
    "subject": "...",
    "amount": 10000.00,
    "organization_name": "...",
    # Snapshot at match time
}
```

When displaying, fetch live decision but keep batch counts based on snapshot.

### Decision: [ ] Immutable (snapshot)

---

## Decision 4: Subscription Modification Retroactivity

### Context
User edits subscription (adds keyword). Should we:

### Options

**A. Only affects future checks**
```python
# Existing batches unchanged
# New checks use new criteria
```
```
Pros:
- Simple
- Fast
- No reprocessing

Cons:
- User might want to see historical matches with new criteria
```

**B. Trigger retroactive check**
```python
# When subscription updated:
if criteria_changed:
    # Re-check last 30 days with new criteria
    # Create new batch with "Retroactive check" flag
```
```
Pros:
- User sees what they would have caught
- Useful for exploring

Cons:
- Expensive
- Confusing ("why new batch for old decisions?")
```

**C. Ask user**
```javascript
// On save:
"Do you want to check for past matches with these new criteria?"
[Yes - Check last 30 days] [No - Apply to future only]
```
```
Pros:
- User choice
- Clear

Cons:
- Extra step
```

### Recommendation
**Option A** by default, with manual "Check Now" button that users can click if they want to see historical matches with new criteria.

### Decision: [ ] Future only, with manual check option

---

## Decision 5: Batch Expiry/Cleanup

### Context
Old batches take up space. When to delete?

### Options

**A. Never delete**
```
Pros:
- Complete history
- User can always review

Cons:
- Database grows forever
- Most users don't care about old notifications
```

**B. Fixed age (e.g., 6 months)**
```python
delete_batches_older_than = timedelta(days=180)
```
```
Pros:
- Bounded growth
- Reasonable history
- Automatic

Cons:
- Arbitrary cutoff
- Some users might want longer
```

**C. Configurable per user/account**
```python
user.notification_retention_days = 365
```
```
Pros:
- User choice
- Flexible

Cons:
- More complex
- Need UI for it
```

**D. Progressive: mark as archived, delete later**
```python
# After 3 months: archive (don't show in UI by default)
# After 12 months: delete
```
```
Pros:
- Gradual
- Can still access if needed

Cons:
- Two-step process
```

### Recommendation
**Option B** - Delete after 6 months, but make it configurable via Django setting:

```python
# settings.py
NOTIFICATION_BATCH_RETENTION_DAYS = 180  # 6 months
```

Can override for specific users if needed (e.g., premium accounts keep forever).

### Decision: [ ] 6-month deletion

---

## Decision 6: Keyword Matching Scope

### Context
Currently keywords only search `decision.subject`. Should we expand?

### Options

**A. Subject only (current)**
```python
Q(subject__icontains=keyword)
```
```
Pros:
- Fast
- Simple
- Subject is indexed

Cons:
- Misses keywords in extracts/content
```

**B. Subject + Extracts**
```python
Q(subject__icontains=keyword) | Q(extracts__icontains=keyword)
```
```
Pros:
- More comprehensive
- Catches more matches

Cons:
- Slower (extracts can be large text)
- Might match too much
```

**C. Configurable per subscription**
```python
keyword_search_scope = JSONField(
    default=['subject'],
    choices=['subject', 'extracts', 'organization_name']
)
```
```
Pros:
- User control
- Can be specific or broad

Cons:
- Complex UI
```

### Recommendation
**Option A** for MVP. Keywords in subject covers most use cases. Add Option C later if users request it.

### Decision: [ ] Subject only for now

---

## Decision 7: Partial Read Tracking

### Context
Should we track which individual decisions within a batch the user viewed?

### Current Design
```python
# NotificationBatchDecision has:
is_viewed = BooleanField(default=False)
```

### Options

**A. Track individual views**
- Mark `is_viewed=True` when user clicks decision in batch results page
- Show "You've viewed 15 of 47 decisions"
```
Pros:
- Granular tracking
- User knows what they've seen
- Can show "unviewed" filter

Cons:
- Extra writes
- Complex to implement
```

**B. Only track batch-level read**
- Just `batch.is_read` (whole batch read/unread)
```
Pros:
- Simple
- Matches email model (read/unread message)

Cons:
- Less granular
```

### Recommendation
**Option B** for MVP - Just track batch-level. The `is_viewed` field is in the model (for future use) but not actively used in Phase 1.

Can add in Phase 2 if users want it:
```javascript
// On decision click in batch results:
await markDecisionViewed(batchId, decisionId);
```

### Decision: [ ] Batch-level only for now

---

## Decision 8: Notification Results Page UX

### Context
How should the results page look? Reuse existing components or create new?

### Options

**A. Reuse EntityDetailPage logic**
```javascript
// Same filtering, sorting, aggregates ribbon
// Just different data source (batch decisions instead of entity decisions)
```
```
Pros:
- Consistent UX
- Reuse tested code
- Users already know how to use it

Cons:
- Might feel generic
- Some filters might not apply
```

**B. Create custom NotificationResultsPage**
```javascript
// Custom layout optimized for batch viewing
// Highlight match reasons
// Different filters
```
```
Pros:
- Tailored to use case
- Can show match_details prominently

Cons:
- More work
- Different UX to learn
```

**C. Hybrid - Reuse components but custom layout**
```javascript
// Use DecisionList, AmountFilter, etc. components
// But custom page layout and header
```
```
Pros:
- Best of both
- Reuse components
- Custom UX where needed

Cons:
- Medium complexity
```

### Recommendation
**Option C** - Reuse components but custom page structure:

```
┌─────────────────────────────────────────┐
│ Batch Header (custom)                   │
│ • Subscription name                     │
│ • "47 decisions matched"                │
│ • Date range checked                    │
│ • [Mark all as viewed] [Dismiss batch]  │
├─────────────────────────────────────────┤
│ Filters (reuse FilterBar component)     │
├─────────────────────────────────────────┤
│ Stats ribbon (reuse, but batch-specific)│
│ Total: €X  |  Avg: €Y  |  Types: Z     │
├─────────────────────────────────────────┤
│ Decision List (reuse DecisionList)      │
│ • Show match_reason badges              │
│ • Regular decision cards                │
└─────────────────────────────────────────┘
```

### Decision: [ ] Hybrid approach

---

## Decision 9: AND/OR UI Presentation

### Context
How to present the keyword operator choice to users?

### Options

**A. Simple toggle**
```
Keywords: [contract] [agreement] [urgent]
Match: (*) All keywords  ( ) Any keyword
```

**B. Dropdown per keyword group**
```
Keyword Group 1: AND ▼
  - contract
  - urgent

Keyword Group 2: OR ▼
  - agreement
  - deal
```

**C. Query builder interface**
```
[ subject ] [ contains ] [ contract ]
[ AND ]
[ subject ] [ contains ] [ urgent ]
```

### Recommendation
**Option A** for Phase 1 - simple toggle:

```jsx
<FormGroup>
  <Label>Keywords</Label>
  <TagInput value={keywords} onChange={setKeywords} />

  <RadioGroup value={keywordOperator} onChange={setKeywordOperator}>
    <Radio value="AND">All keywords must match</Radio>
    <Radio value="OR">Any keyword matches</Radio>
  </RadioGroup>
</FormGroup>
```

### Decision: [ ] Simple toggle (Option A)

---

## Decision 10: Test Data Strategy

### Context
How to generate test data for development/testing?

### Options

**A. Factory fixtures**
```python
# conftest.py
NotificationBatchFactory
NotificationBatchDecisionFactory
```

**B. Management command**
```bash
python manage.py generate_test_batches --users=10 --batches-per-user=5
```

**C. Dedicated test database dump**
```bash
# Load pre-populated test data
pg_restore test_data.dump
```

### Recommendation
**Option A + B**:
- Factories for unit tests (fast, isolated)
- Management command for local dev (realistic data)

```python
# backend/notifications/tests/factories.py
class NotificationBatchFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = NotificationBatch

    user = factory.SubFactory(UserFactory)
    subscription = factory.SubFactory(NotificationSubscriptionFactory)
    match_count = factory.Faker('random_int', min=1, max=100)
    # etc.
```

### Decision: [ ] Factories + management command

---

## Summary of Recommended Decisions

| # | Decision | Recommendation | Rationale |
|---|----------|---------------|-----------|
| 1 | Batch size | Cap at 1000, multiple batches | Keeps UI performant |
| 2 | External notifications | In-app only (MVP) | Avoid spam, add email later |
| 3 | Historical updates | Immutable snapshots | Historical accuracy |
| 4 | Subscription edits | Future only + manual check | Simple and clear |
| 5 | Batch cleanup | 6-month deletion | Bounded growth |
| 6 | Keyword scope | Subject only | Fast and sufficient |
| 7 | View tracking | Batch-level only | Simple, can extend later |
| 8 | Results page UX | Hybrid (reuse components) | Consistency + customization |
| 9 | AND/OR UI | Simple toggle | Easy to use |
| 10 | Test data | Factories + mgmt command | Best practices |

---

## Next Steps

1. Review these decisions with team
2. Mark final choices in checkboxes above
3. Document any deviations in implementation
4. Start Phase 1 implementation

---

**Last Updated:** 2026-03-08
**Status:** Awaiting decisions
