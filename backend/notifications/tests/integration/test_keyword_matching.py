"""
Comprehensive tests for keyword matching in notification subscriptions.

This test suite covers:
- OR operator: any keyword matches
- AND operator: all keywords must match
- Case insensitivity
- Edge cases (empty keywords, single keyword, no matches)
- Combinations with other subscription types and filters
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from notifications.models.notification_batch import NotificationBatch

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


# ============================================================================
# OR Operator Tests (keyword_match_operator='OR')
# ============================================================================


class TestKeywordMatchingOR:
    """Test keyword matching with OR operator - any keyword matches."""

    def test_single_keyword_match_or(self, user, organization, celery_eager_mode):
        """Single keyword should match when using OR operator"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        # Create subscription with OR operator (default in old code)
        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["contract"],
            keyword_match_operator="OR",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Create matching decision
        matching = DecisionFactory(
            organization=organization,
            subject="New contract for services",
            publish_timestamp=timezone.now(),
        )

        # Create non-matching decision
        non_matching = DecisionFactory(
            organization=organization,
            subject="Administrative note",
            publish_timestamp=timezone.now(),
        )

        # Check subscription
        check_single_subscription(sub.id)

        # Should create notification batch for matching decision only
        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1

        batch = batches.first()
        batch_decisions = batch.batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == matching
        assert "contract" in batch_decisions.first().match_details.get(
            "keywords_found", []
        )

    def test_multiple_keywords_any_match_or(
        self, user, organization, celery_eager_mode
    ):
        """With OR, matching any one keyword should trigger notification"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        # Create subscription with multiple keywords, OR operator
        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["contract", "tender", "procurement"],
            keyword_match_operator="OR",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Match first keyword only
        match1 = DecisionFactory(
            organization=organization,
            subject="New contract for supplies",
            publish_timestamp=timezone.now(),
        )

        # Match second keyword only
        match2 = DecisionFactory(
            organization=organization,
            subject="Public tender announcement",
            publish_timestamp=timezone.now(),
        )

        # Match multiple keywords
        match3 = DecisionFactory(
            organization=organization,
            subject="Procurement contract after tender process",
            publish_timestamp=timezone.now(),
        )

        # No match
        non_match = DecisionFactory(
            organization=organization,
            subject="Regular administrative decision",
            publish_timestamp=timezone.now(),
        )

        # Check subscription
        check_single_subscription(sub.id)

        # Should create 1 batch with 3 decisions
        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1

        batch = batches.first()
        batch_decisions = batch.batch_decisions.all()
        assert batch_decisions.count() == 3

        # Verify each decision has correct keyword matches
        decision_keywords = {
            match1.id: ["contract"],
            match2.id: ["tender"],
            match3.id: ["contract", "tender", "procurement"],
        }

        for batch_decision in batch_decisions:
            expected_keywords = decision_keywords.get(batch_decision.decision.id, [])
            found_keywords = batch_decision.match_details.get("keywords_found", [])
            # Check that at least one expected keyword was found
            assert any(kw in found_keywords for kw in expected_keywords)

    def test_case_insensitive_keyword_matching_or(
        self, user, organization, celery_eager_mode
    ):
        """Keywords should match case-insensitively with OR operator"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["Contract", "TENDER", "ProcureMent"],
            keyword_match_operator="OR",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Lowercase keyword in subject
        match1 = DecisionFactory(
            organization=organization,
            subject="new contract for supplies",
            publish_timestamp=timezone.now(),
        )

        # Uppercase keyword in subject
        match2 = DecisionFactory(
            organization=organization,
            subject="PUBLIC TENDER ANNOUNCEMENT",
            publish_timestamp=timezone.now(),
        )

        # Mixed case
        match3 = DecisionFactory(
            organization=organization,
            subject="Procurement Process Started",
            publish_timestamp=timezone.now(),
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 3

    def test_greek_keywords_or(self, user, organization, celery_eager_mode):
        """Test Greek keyword matching with OR operator"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["διαγωνισμός", "σύμβαση", "προμήθεια"],
            keyword_match_operator="OR",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        match1 = DecisionFactory(
            organization=organization,
            subject="Ανακοίνωση διαγωνισμού για έργο",
            publish_timestamp=timezone.now(),
        )

        match2 = DecisionFactory(
            organization=organization,
            subject="Σύμβαση παροχής υπηρεσιών",
            publish_timestamp=timezone.now(),
        )

        non_match = DecisionFactory(
            organization=organization,
            subject="Διοικητική πράξη",
            publish_timestamp=timezone.now(),
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 2


# ============================================================================
# AND Operator Tests (keyword_match_operator='AND')
# ============================================================================


class TestKeywordMatchingAND:
    """Test keyword matching with AND operator - all keywords must match."""

    def test_single_keyword_match_and(self, user, organization, celery_eager_mode):
        """Single keyword with AND operator should work like OR"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["contract"],
            keyword_match_operator="AND",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        matching = DecisionFactory(
            organization=organization,
            subject="New contract for services",
            publish_timestamp=timezone.now(),
        )

        non_matching = DecisionFactory(
            organization=organization,
            subject="Administrative note",
            publish_timestamp=timezone.now(),
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == matching

    def test_all_keywords_must_match_and(self, user, organization, celery_eager_mode):
        """With AND, all keywords must be present to trigger notification"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        # Create subscription with AND operator (all keywords required)
        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["contract", "urgent", "supplies"],
            keyword_match_operator="AND",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Match: has all three keywords
        full_match = DecisionFactory(
            organization=organization,
            subject="Urgent contract for supplies delivery",
            publish_timestamp=timezone.now(),
        )

        # Partial match 1: has only 2 out of 3 keywords - should NOT match
        partial_match1 = DecisionFactory(
            organization=organization,
            subject="Urgent contract for services",
            publish_timestamp=timezone.now(),
        )

        # Partial match 2: has only 1 keyword - should NOT match
        partial_match2 = DecisionFactory(
            organization=organization,
            subject="Regular supplies order",
            publish_timestamp=timezone.now(),
        )

        # No match
        non_match = DecisionFactory(
            organization=organization,
            subject="Administrative decision",
            publish_timestamp=timezone.now(),
        )

        # Check subscription
        check_single_subscription(sub.id)

        # Should create batch only for the decision with all keywords
        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        batch_decision = batch_decisions.first()
        assert batch_decision.decision == full_match

        # Verify all keywords are in match_details
        found_keywords = batch_decision.match_details.get("keywords_found", [])
        assert "contract" in found_keywords
        assert "urgent" in found_keywords
        assert "supplies" in found_keywords
        assert batch_decision.match_details.get("keyword_match_operator") == "AND"

    def test_two_keywords_both_required_and(
        self, user, organization, celery_eager_mode
    ):
        """With AND and 2 keywords, both must be present"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["tender", "construction"],
            keyword_match_operator="AND",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Has both keywords
        match = DecisionFactory(
            organization=organization,
            subject="Public tender for construction project",
            publish_timestamp=timezone.now(),
        )

        # Has only 'tender'
        no_match1 = DecisionFactory(
            organization=organization,
            subject="Public tender for consulting services",
            publish_timestamp=timezone.now(),
        )

        # Has only 'construction'
        no_match2 = DecisionFactory(
            organization=organization,
            subject="Construction permit approval",
            publish_timestamp=timezone.now(),
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == match

    def test_case_insensitive_and(self, user, organization, celery_eager_mode):
        """AND operator should also be case-insensitive"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["URGENT", "Contract"],
            keyword_match_operator="AND",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Mixed case in subject
        match = DecisionFactory(
            organization=organization,
            subject="urgent new contract for services",
            publish_timestamp=timezone.now(),
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == match

    def test_keyword_order_irrelevant_and(self, user, organization, celery_eager_mode):
        """With AND, keyword order in subject should not matter"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["first", "second", "third"],
            keyword_match_operator="AND",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Keywords in different order than subscription
        match1 = DecisionFactory(
            organization=organization,
            subject="third item comes before second and first",
            publish_timestamp=timezone.now(),
        )

        # Keywords scattered throughout subject
        match2 = DecisionFactory(
            organization=organization,
            subject="first decision regarding the third party and second step",
            publish_timestamp=timezone.now(),
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 2


# ============================================================================
# Default Behavior Tests
# ============================================================================


class TestKeywordMatchingDefaults:
    """Test default behavior when keyword_match_operator is not explicitly set."""

    def test_default_operator_is_and(self, user, organization, celery_eager_mode):
        """Default operator should be AND based on model definition"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        # Create subscription without explicitly setting operator (should default to AND)
        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["contract", "urgent"],
            # Note: NOT setting keyword_match_operator, should default to 'AND'
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Verify default is 'AND'
        assert sub.keyword_match_operator == "AND"

        # Has both keywords - should match
        match = DecisionFactory(
            organization=organization,
            subject="Urgent contract for supplies",
            publish_timestamp=timezone.now(),
        )

        # Has only one keyword - should NOT match
        no_match = DecisionFactory(
            organization=organization,
            subject="Urgent administrative note",
            publish_timestamp=timezone.now(),
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == match


# ============================================================================
# Edge Cases
# ============================================================================


class TestKeywordMatchingEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_keywords_list(self, user, organization, celery_eager_mode):
        """Empty keywords list should not filter (match all)"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=[],  # Empty list
            keyword_match_operator="OR",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        decision1 = DecisionFactory(
            organization=organization,
            subject="First decision",
            publish_timestamp=timezone.now(),
        )

        decision2 = DecisionFactory(
            organization=organization,
            subject="Second decision",
            publish_timestamp=timezone.now(),
        )

        check_single_subscription(sub.id)

        # Should match both decisions since no keyword filter is applied
        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 2

    def test_none_keywords(self, user, organization, celery_eager_mode):
        """None keywords should not filter"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user, organization=organization, keywords=None
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        decision = DecisionFactory(
            organization=organization,
            subject="Some decision",
            publish_timestamp=timezone.now(),
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1

    def test_keyword_not_found_in_any_decision_or(
        self, user, organization, celery_eager_mode
    ):
        """When no decisions match any keyword with OR, no notifications"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["nonexistent", "noway"],
            keyword_match_operator="OR",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        decision = DecisionFactory(
            organization=organization,
            subject="Regular decision without those words",
            publish_timestamp=timezone.now(),
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 0

    def test_keyword_not_found_in_any_decision_and(
        self, user, organization, celery_eager_mode
    ):
        """When no decisions match all keywords with AND, no notifications"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["one", "two", "three"],
            keyword_match_operator="AND",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Has only 'one' and 'two', missing 'three'
        decision = DecisionFactory(
            organization=organization,
            subject="Decision with one and two items",
            publish_timestamp=timezone.now(),
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 0


# ============================================================================
# Combination Tests (Keywords + Other Filters)
# ============================================================================


class TestKeywordWithOtherFilters:
    """Test keywords combined with other subscription filters."""

    def test_organization_and_keywords_or(self, user, organization, celery_eager_mode):
        """Organization filter + keyword OR filter"""
        from conftest import (
            DecisionFactory,
            NotificationSubscriptionFactory,
            OrganizationFactory,
        )
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["contract", "tender"],
            keyword_match_operator="OR",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Correct org + keyword
        match = DecisionFactory(
            organization=organization,
            subject="New contract",
            publish_timestamp=timezone.now(),
        )

        # Correct org, no keyword
        no_match1 = DecisionFactory(
            organization=organization,
            subject="Administrative note",
            publish_timestamp=timezone.now(),
        )

        # Has keyword, wrong org
        other_org = OrganizationFactory()
        no_match2 = DecisionFactory(
            organization=other_org,
            subject="Contract from another org",
            publish_timestamp=timezone.now(),
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == match

    def test_organization_and_keywords_and(self, user, organization, celery_eager_mode):
        """Organization filter + keyword AND filter"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["urgent", "contract"],
            keyword_match_operator="AND",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Correct org + both keywords
        match = DecisionFactory(
            organization=organization,
            subject="Urgent contract for supplies",
            publish_timestamp=timezone.now(),
        )

        # Correct org + only one keyword
        no_match = DecisionFactory(
            organization=organization,
            subject="Urgent administrative note",
            publish_timestamp=timezone.now(),
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == match

    def test_keywords_and_amount_filter_or(self, user, organization, celery_eager_mode):
        """Keywords (OR) + amount filter"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["contract", "procurement"],
            keyword_match_operator="OR",
            amount_min=Decimal("10000.00"),
            amount_max=Decimal("50000.00"),
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Has keyword + amount in range
        match = DecisionFactory(
            organization=organization,
            subject="New contract",
            amount=Decimal("25000.00"),
            publish_timestamp=timezone.now(),
        )

        # Has keyword, amount too high
        no_match1 = DecisionFactory(
            organization=organization,
            subject="Large contract",
            amount=Decimal("100000.00"),
            publish_timestamp=timezone.now(),
        )

        # Amount in range, no keyword
        no_match2 = DecisionFactory(
            organization=organization,
            subject="Administrative decision",
            amount=Decimal("20000.00"),
            publish_timestamp=timezone.now(),
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == match

    def test_keywords_and_amount_filter_and(
        self, user, organization, celery_eager_mode
    ):
        """Keywords (AND) + amount filter"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["urgent", "contract"],
            keyword_match_operator="AND",
            amount_min=Decimal("10000.00"),
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Has both keywords + amount
        match = DecisionFactory(
            organization=organization,
            subject="Urgent contract for supplies",
            amount=Decimal("15000.00"),
            publish_timestamp=timezone.now(),
        )

        # Has both keywords, amount too low
        no_match1 = DecisionFactory(
            organization=organization,
            subject="Urgent contract for minor supplies",
            amount=Decimal("5000.00"),
            publish_timestamp=timezone.now(),
        )

        # Has one keyword + amount
        no_match2 = DecisionFactory(
            organization=organization,
            subject="Urgent delivery",
            amount=Decimal("15000.00"),
            publish_timestamp=timezone.now(),
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == match

    def test_entity_subscription_with_keywords_and(
        self, user, afm_entity, celery_eager_mode
    ):
        """Entity subscription + keywords (AND)"""
        from conftest import DecisionFactory, EntitySubscriptionFactory
        from core.models.entities import DecisionEntityRelationship, EntityRole
        from notifications.tasks import check_single_subscription

        sub = EntitySubscriptionFactory(
            user=user,
            entity=afm_entity,
            keywords=["contract", "services"],
            keyword_match_operator="AND",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Has entity + both keywords
        match = DecisionFactory(
            subject="Contract for services", publish_timestamp=timezone.now()
        )
        DecisionEntityRelationship.objects.create(
            decision=match,
            entity=afm_entity,
            role=EntityRole.SPONSOR,
            parent_key_path="sponsor[0]",
        )

        # Has entity + only one keyword
        no_match = DecisionFactory(
            subject="Contract for supplies", publish_timestamp=timezone.now()
        )
        DecisionEntityRelationship.objects.create(
            decision=no_match,
            entity=afm_entity,
            role=EntityRole.SPONSOR,
            parent_key_path="sponsor[0]",
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == match

    def test_filter_only_subscription_keywords_and(self, user, celery_eager_mode):
        """Filter-only subscription with keywords (AND)"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        # No organization or entity, just filters
        sub = NotificationSubscriptionFactory(
            user=user,
            organization=None,
            keywords=["urgent", "public", "tender"],
            keyword_match_operator="AND",
            amount_min=Decimal("50000.00"),
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Has all keywords + amount
        match = DecisionFactory(
            subject="Urgent public tender for construction",
            amount=Decimal("75000.00"),
            publish_timestamp=timezone.now(),
        )

        # Has all keywords, no amount
        no_match1 = DecisionFactory(
            subject="Urgent public tender announcement",
            amount=None,
            publish_timestamp=timezone.now(),
        )

        # Has amount, missing one keyword
        no_match2 = DecisionFactory(
            subject="Urgent tender for services",
            amount=Decimal("60000.00"),
            publish_timestamp=timezone.now(),
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == match


# ============================================================================
# Document Text Keyword Matching Tests
# ============================================================================


class TestKeywordMatchingInDocumentText:
    """Test keyword matching in DocumentExtraction.raw_text field."""

    def test_keyword_in_subject_only(self, user, organization, celery_eager_mode):
        """Keyword found only in subject should match (existing behavior)"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from core.models.document_analysis import DocumentExtraction
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["contract"],
            keyword_match_operator="OR",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Create decision with keyword in subject
        decision = DecisionFactory(
            organization=organization,
            subject="New contract for services",
            publish_timestamp=timezone.now(),
        )

        # Create text extraction WITHOUT the keyword
        DocumentExtraction.objects.create(
            decision=decision,
            extraction_status="COMPLETED",
            raw_text="This is some text about other things, no matching keyword here.",
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        batch_decision = batch_decisions.first()
        assert batch_decision.decision == decision
        assert "contract" in batch_decision.match_details.get("keywords_found", [])
        assert "subject" in batch_decision.match_details.get("keywords_found_in", [])

    def test_keyword_in_document_text_only(self, user, organization, celery_eager_mode):
        """Keyword found only in document text should match (new behavior)"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from core.models.document_analysis import DocumentExtraction
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["procurement"],
            keyword_match_operator="OR",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Create decision WITHOUT keyword in subject
        decision = DecisionFactory(
            organization=organization,
            subject="Administrative decision",
            publish_timestamp=timezone.now(),
        )

        # Create text extraction WITH the keyword
        DocumentExtraction.objects.create(
            decision=decision,
            extraction_status="COMPLETED",
            raw_text="This document contains details about the procurement process and vendor selection.",
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        batch_decision = batch_decisions.first()
        assert batch_decision.decision == decision
        assert "procurement" in batch_decision.match_details.get("keywords_found", [])
        assert "document_text" in batch_decision.match_details.get(
            "keywords_found_in", []
        )

    def test_keyword_in_both_subject_and_document(
        self, user, organization, celery_eager_mode
    ):
        """Keyword found in both subject and document text"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from core.models.document_analysis import DocumentExtraction
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["tender"],
            keyword_match_operator="OR",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Create decision with keyword in subject
        decision = DecisionFactory(
            organization=organization,
            subject="Public tender announcement",
            publish_timestamp=timezone.now(),
        )

        # Create text extraction also with the keyword
        DocumentExtraction.objects.create(
            decision=decision,
            extraction_status="COMPLETED",
            raw_text="The tender process will begin next month and all vendors are invited to participate.",
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        batch_decision = batch_decisions.first()
        assert batch_decision.decision == decision
        assert "tender" in batch_decision.match_details.get("keywords_found", [])
        # Should be found in both locations
        found_in = batch_decision.match_details.get("keywords_found_in", [])
        assert "subject" in found_in
        assert "document_text" in found_in

    def test_keyword_not_in_subject_or_document(
        self, user, organization, celery_eager_mode
    ):
        """Keyword not found in either subject or document text should not match"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from core.models.document_analysis import DocumentExtraction
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["helicopter"],
            keyword_match_operator="OR",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Create decision without keyword
        decision = DecisionFactory(
            organization=organization,
            subject="Administrative decision about office supplies",
            publish_timestamp=timezone.now(),
        )

        # Create text extraction without keyword
        DocumentExtraction.objects.create(
            decision=decision,
            extraction_status="COMPLETED",
            raw_text="This document describes the purchase of paper and pens for the office.",
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 0

    def test_no_document_extraction_fallback_to_subject_only(
        self, user, organization, celery_eager_mode
    ):
        """If no DocumentExtraction exists, should still match on subject"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["services"],
            keyword_match_operator="OR",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Create decision with keyword in subject, NO DocumentExtraction
        decision = DecisionFactory(
            organization=organization,
            subject="Services agreement",
            publish_timestamp=timezone.now(),
        )
        # Do NOT create DocumentExtraction

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == decision

    def test_document_text_or_operator_multiple_keywords(
        self, user, organization, celery_eager_mode
    ):
        """OR operator with multiple keywords - should match if any keyword in document text"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from core.models.document_analysis import DocumentExtraction
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["construction", "renovation", "building"],
            keyword_match_operator="OR",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Subject has no keywords, but document text has one
        decision = DecisionFactory(
            organization=organization,
            subject="Project approval decision",
            publish_timestamp=timezone.now(),
        )

        DocumentExtraction.objects.create(
            decision=decision,
            extraction_status="COMPLETED",
            raw_text="The renovation of the municipal building will be completed by the end of the year.",
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert "renovation" in batch_decisions.first().match_details.get(
            "keywords_found", []
        )

    def test_document_text_and_operator_all_keywords_required(
        self, user, organization, celery_eager_mode
    ):
        """AND operator - all keywords must be present in subject OR document text"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from core.models.document_analysis import DocumentExtraction
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["urgent", "repair", "equipment"],
            keyword_match_operator="AND",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Subject has 'urgent', document text has 'repair' and 'equipment'
        match = DecisionFactory(
            organization=organization,
            subject="Urgent decision required",
            publish_timestamp=timezone.now(),
        )

        DocumentExtraction.objects.create(
            decision=match,
            extraction_status="COMPLETED",
            raw_text="This concerns the repair of critical equipment in the facility.",
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        found_keywords = batch_decisions.first().match_details.get("keywords_found", [])
        assert "urgent" in found_keywords
        assert "repair" in found_keywords
        assert "equipment" in found_keywords

    def test_document_text_and_operator_missing_one_keyword(
        self, user, organization, celery_eager_mode
    ):
        """AND operator - should NOT match if one keyword is missing from both subject and document"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from core.models.document_analysis import DocumentExtraction
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["urgent", "repair", "equipment"],
            keyword_match_operator="AND",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Has 'urgent' in subject and 'repair' in document, but missing 'equipment'
        decision = DecisionFactory(
            organization=organization,
            subject="Urgent decision",
            publish_timestamp=timezone.now(),
        )

        DocumentExtraction.objects.create(
            decision=decision,
            extraction_status="COMPLETED",
            raw_text="This concerns the repair work needed in the building.",
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 0

    def test_greek_keywords_in_document_text(
        self, user, organization, celery_eager_mode
    ):
        """Test Greek keyword matching in document text"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from core.models.document_analysis import DocumentExtraction
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["σύμβαση", "προμήθεια"],
            keyword_match_operator="OR",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Greek keyword only in document text
        decision = DecisionFactory(
            organization=organization,
            subject="Διοικητική πράξη",
            publish_timestamp=timezone.now(),
        )

        DocumentExtraction.objects.create(
            decision=decision,
            extraction_status="COMPLETED",
            raw_text="Η σύμβαση αφορά την προμήθεια υλικών για το έργο.",
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        found_keywords = batch_decisions.first().match_details.get("keywords_found", [])
        # Should find both Greek keywords
        assert any("σύμβαση" in kw or "προμήθεια" in kw for kw in found_keywords)

    def test_case_insensitive_in_document_text(
        self, user, organization, celery_eager_mode
    ):
        """Document text keyword matching should be case-insensitive"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from core.models.document_analysis import DocumentExtraction
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["CONTRACT", "Services"],
            keyword_match_operator="OR",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        decision = DecisionFactory(
            organization=organization,
            subject="Administrative decision",
            publish_timestamp=timezone.now(),
        )

        # Document has lowercase versions
        DocumentExtraction.objects.create(
            decision=decision,
            extraction_status="COMPLETED",
            raw_text="The contract for services was signed yesterday.",
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1

    def test_keyword_in_document_with_amount_filter(
        self, user, organization, celery_eager_mode
    ):
        """Keyword in document text combined with amount filter"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from core.models.document_analysis import DocumentExtraction
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["equipment"],
            keyword_match_operator="OR",
            amount_min=Decimal("10000.00"),
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Keyword in document + amount in range
        match = DecisionFactory(
            organization=organization,
            subject="Purchase decision",
            amount=Decimal("15000.00"),
            publish_timestamp=timezone.now(),
        )

        DocumentExtraction.objects.create(
            decision=match,
            extraction_status="COMPLETED",
            raw_text="Purchase of new equipment for the office.",
        )

        # Keyword in document but amount too low
        no_match = DecisionFactory(
            organization=organization,
            subject="Small purchase",
            amount=Decimal("5000.00"),
            publish_timestamp=timezone.now(),
        )

        DocumentExtraction.objects.create(
            decision=no_match,
            extraction_status="COMPLETED",
            raw_text="Purchase of minor equipment items.",
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == match

    def test_long_document_text_with_keyword(
        self, user, organization, celery_eager_mode
    ):
        """Test keyword matching in longer document text"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from core.models.document_analysis import DocumentExtraction
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["environmental"],
            keyword_match_operator="OR",
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        decision = DecisionFactory(
            organization=organization,
            subject="Decision regarding project approval",
            publish_timestamp=timezone.now(),
        )

        # Long document with keyword buried in the middle
        long_text = """
        This is a comprehensive decision document describing the approval process.

        Section 1: Introduction
        This document outlines the procedures and requirements for the proposed project.

        Section 2: Technical Specifications
        The project must meet all technical standards and requirements.

        Section 3: Environmental Impact
        The environmental assessment has been completed and reviewed by experts.
        All environmental regulations must be strictly followed.

        Section 4: Budget
        Total estimated cost is within approved budget limits.

        Section 5: Timeline
        Project completion is scheduled for next year.
        """

        DocumentExtraction.objects.create(
            decision=decision, extraction_status="COMPLETED", raw_text=long_text
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert "environmental" in batch_decisions.first().match_details.get(
            "keywords_found", []
        )
