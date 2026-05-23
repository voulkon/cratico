# Notification Batch System - Quick Checklist

**Related:** [Full Implementation Plan](./notification-batch-system-implementation-plan.md)

---

## Phase 1: Data Models ✓/✗

- [ ] Create `backend/notifications/models/notification_batch.py`
  - [ ] NotificationBatch model
  - [ ] NotificationBatchDecision model
- [ ] Add `keyword_match_operator` to NotificationSubscription
- [ ] Generate and run migrations
- [ ] Test in Django admin

---

## Phase 2: Backend Tasks ✓/✗

- [ ] Update `find_matching_decisions()` - Add AND/OR keyword logic
- [ ] Create `create_notification_batch()` function
- [ ] Update `check_subscriptions_for_new_decisions()` to create batches
- [ ] Update `check_single_subscription()` for manual checks
- [ ] Test with real subscriptions

---

## Phase 3: API ✓/✗

- [ ] Create `backend/notifications/serializers/notification_batch.py`
  - [ ] NotificationBatchListSerializer
  - [ ] NotificationBatchDetailSerializer
  - [ ] NotificationBatchDecisionSerializer
- [ ] Create NotificationBatchViewSet in `views.py`
  - [ ] list, retrieve endpoints
  - [ ] decisions endpoint (with pagination/filtering)
  - [ ] mark-read, dismiss actions
  - [ ] unread-count endpoint
- [ ] Update NotificationSubscription serializers (add keyword_match_operator)
- [ ] Add URL routing
- [ ] Test all endpoints with Postman/curl

---

## Phase 4: Frontend ✓/✗

- [ ] Update `frontend/src/api/notifications.js`
  - [ ] Add batch API functions
  - [ ] Update subscription functions
- [ ] Update `NotificationSidebar.js`
  - [ ] Load and display batches
  - [ ] Update unread count
  - [ ] Click → navigate to results
- [ ] Create `NotificationResultsPage.js`
  - [ ] Display batch metadata
  - [ ] Show decisions list (reuse components)
  - [ ] Add filtering/sorting
- [ ] Add subscription edit modal
  - [ ] Keyword operator toggle
- [ ] Add route in App.js
- [ ] Update translations (el.json, en.json)
- [ ] Test in browser

---

## Phase 5: Testing ✓/✗

- [ ] Backend model tests
- [ ] Backend task tests (especially AND/OR)
- [ ] API endpoint tests
- [ ] Integration tests
- [ ] Frontend component tests (if using)
- [ ] Manual end-to-end testing

---

## Phase 6: Deployment ✓/✗

- [ ] Backup database
- [ ] Deploy to staging
- [ ] Run migrations
- [ ] Test in staging
- [ ] Deploy to production
- [ ] Monitor logs and metrics

---

## Phase 7: Cleanup ✓/✗

- [ ] Create cleanup task (delete old batches)
- [ ] Add to Celery Beat schedule
- [ ] Create admin interfaces
- [ ] Consider removing old Notification model
- [ ] Update documentation

---

## Quick Test Commands

```bash
# Run migrations
cd backend
python manage.py makemigrations
python manage.py migrate

# Run tests
pytest backend/notifications/tests/ -v

# Run specific test
pytest backend/notifications/tests/test_notification_tasks.py::test_keyword_or_operator -v

# Create test data
python manage.py shell
# ... create subscriptions, run tasks

# Check Celery
celery -A diavgeia_project worker -l info

# Trigger task manually
from notifications.tasks import check_subscriptions_for_new_decisions
check_subscriptions_for_new_decisions.delay()
```

---

## Current Status

**Phase:** Not Started
**Last Updated:** 2026-03-08
**Blocked By:** None
**Notes:**

---

## Quick Reference - Key Files

### Backend
- `backend/notifications/models/notification_batch.py` - NEW
- `backend/notifications/models/notification_subscription.py` - MODIFY
- `backend/notifications/tasks/notification_tasks.py` - MODIFY
- `backend/notifications/serializers/notification_batch.py` - NEW
- `backend/notifications/views.py` - ADD NotificationBatchViewSet
- `backend/notifications/urls.py` - ADD routes

### Frontend
- `frontend/src/api/notifications.js` - ADD batch functions
- `frontend/src/components/NotificationSidebar.js` - MODIFY
- `frontend/src/pages/NotificationResultsPage.js` - NEW
- `frontend/src/locales/el.json` - ADD translations
- `frontend/src/locales/en.json` - ADD translations
- `frontend/src/App.js` - ADD route

### Tests
- `backend/notifications/tests/test_models.py` - NEW
- `backend/notifications/tests/test_notification_tasks.py` - UPDATE
- `backend/notifications/tests/test_api.py` - NEW
- `backend/notifications/tests/integration/test_batch_flow.py` - NEW

---

**Start Here:** Phase 1 → Create new models
