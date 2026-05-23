"""
Comprehensive tests for all notification subscription types and filter combinations.

This test suite covers:
- All 6 subscription target types: organization, entity, relationship, person, signer, filter-only
- All 4 filter types: keywords, amount_min/max, decision_types
- Combinations: target + filter combinations (e.g., organization + keyword + amount)

Each test verifies that:
1. Subscription can be created with the specific combination
2. Matching decisions trigger notifications
3. Non-matching decisions do NOT trigger notifications
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from notifications.models.notification_batch import NotificationBatch

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


# ============================================================================
# Base Target Type Tests (no additional filters)
# ============================================================================


class TestBaseSubscriptionTypes:
    """Test each subscription type without additional filters."""

    def test_organization_subscription_basic(
        self, user, organization, celery_eager_mode
    ):
        """Test basic organization subscription - any decision from that org"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        # Create subscription
        sub = NotificationSubscriptionFactory(user=user, organization=organization)
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Create matching decision
        matching = DecisionFactory(
            organization=organization,
            subject="Some decision from this org",
            publish_timestamp=timezone.now(),
        )

        # Create non-matching decision (different org)
        from conftest import OrganizationFactory

        other_org = OrganizationFactory()
        non_matching = DecisionFactory(
            organization=other_org, subject="Decision from another org"
        )

        # Check subscription
        check_single_subscription(sub.id)

        # Should create notification batch for matching decision only
        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == matching

    def test_entity_subscription_basic(self, user, afm_entity, celery_eager_mode):
        """Test basic entity subscription - any decision involving that entity"""
        from conftest import DecisionFactory, EntitySubscriptionFactory
        from core.models.entities import DecisionEntityRelationship, EntityRole
        from notifications.tasks import check_single_subscription

        # Create subscription
        sub = EntitySubscriptionFactory(user=user, entity=afm_entity)
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Create decision with this entity
        matching = DecisionFactory(publish_timestamp=timezone.now())
        DecisionEntityRelationship.objects.create(
            decision=matching,
            entity=afm_entity,
            role=EntityRole.SPONSOR,
            parent_key_path="sponsor[0]",
        )

        # Create decision without this entity
        non_matching = DecisionFactory(publish_timestamp=timezone.now())

        # Check subscription
        check_single_subscription(sub.id)

        # Should create notification batch for matching decision only
        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == matching

    def test_relationship_subscription_basic(
        self, user, organization, afm_entity, celery_eager_mode
    ):
        """Test relationship subscription - org + entity combination"""
        from conftest import (
            DecisionFactory,
            OrganizationFactory,
            RelationshipSubscriptionFactory,
        )
        from core.models.entities import DecisionEntityRelationship, EntityRole
        from notifications.tasks import check_single_subscription

        # Create subscription
        sub = RelationshipSubscriptionFactory(
            user=user, relationship_org=organization, relationship_entity=afm_entity
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Create matching decision (correct org + entity)
        matching = DecisionFactory(
            organization=organization, publish_timestamp=timezone.now()
        )
        DecisionEntityRelationship.objects.create(
            decision=matching,
            entity=afm_entity,
            role=EntityRole.SPONSOR,
            parent_key_path="sponsor[0]",
        )

        # Create non-matching (correct org, wrong entity)
        from conftest import AFMEntityFactory

        other_entity = AFMEntityFactory()
        wrong_entity = DecisionFactory(
            organization=organization, publish_timestamp=timezone.now()
        )
        DecisionEntityRelationship.objects.create(
            decision=wrong_entity,
            entity=other_entity,
            role=EntityRole.SPONSOR,
            parent_key_path="sponsor[0]",
        )

        # Create non-matching (wrong org, correct entity)
        other_org = OrganizationFactory()
        wrong_org = DecisionFactory(
            organization=other_org, publish_timestamp=timezone.now()
        )
        DecisionEntityRelationship.objects.create(
            decision=wrong_org,
            entity=afm_entity,
            role=EntityRole.SPONSOR,
            parent_key_path="sponsor[0]",
        )

        # Check subscription
        check_single_subscription(sub.id)

        # Should create notification for matching decision only
        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == matching

    def test_signer_subscription_basic(self, user, celery_eager_mode):
        """Test signer subscription - decisions signed by specific person"""
        from conftest import (
            DecisionFactory,
            NotificationSubscriptionFactory,
            SignerFactory,
        )
        from notifications.tasks import check_single_subscription

        # Create a signer
        signer = SignerFactory(first_name="Γεώργιος", last_name="Παπαδόπουλος")
        signer_name = f"{signer.first_name} {signer.last_name}"

        # Create subscription
        sub = NotificationSubscriptionFactory(
            user=user,
            organization=None,  # No organization filter
            signer_name=signer_name,
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Create matching decision with this signer
        matching = DecisionFactory(
            publish_timestamp=timezone.now(), subject="Decision signed by target person"
        )
        matching.signers.add(signer)

        # Create another signer and non-matching decision
        other_signer = SignerFactory(first_name="Άλλος", last_name="Υπογραφών")
        non_matching = DecisionFactory(
            publish_timestamp=timezone.now(), subject="Decision signed by someone else"
        )
        non_matching.signers.add(other_signer)

        # Check subscription
        check_single_subscription(sub.id)

        # Should create notification for matching decision
        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == matching

    def test_filter_only_subscription(self, user, celery_eager_mode):
        """Test filter-only subscription - no specific target, just criteria"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        # Create subscription with only keyword filter (no organization/entity)
        sub = NotificationSubscriptionFactory(
            user=user, organization=None, keywords=["urgent", "contract"]
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Create matching decision
        matching = DecisionFactory(
            subject="Urgent contract for supplies", publish_timestamp=timezone.now()
        )

        # Create non-matching decision
        non_matching = DecisionFactory(
            subject="Regular administrative note", publish_timestamp=timezone.now()
        )

        # Check subscription
        check_single_subscription(sub.id)

        # Should create notification for matching decision
        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == matching


# ============================================================================
# Filter Combination Tests
# ============================================================================


class TestOrganizationWithFilters:
    """Test organization subscriptions combined with various filters."""

    def test_organization_with_keywords(self, user, organization, celery_eager_mode):
        """Organization + keyword filter"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user, organization=organization, keywords=["procurement", "contract"]
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Matching (correct org + keyword)
        matching = DecisionFactory(
            organization=organization,
            subject="Procurement contract for services",
            publish_timestamp=timezone.now(),
        )

        # Non-matching (correct org, no keyword)
        wrong_keyword = DecisionFactory(
            organization=organization,
            subject="Administrative note",
            publish_timestamp=timezone.now(),
        )

        # Non-matching (has keyword, wrong org)
        from conftest import OrganizationFactory

        other_org = OrganizationFactory()
        wrong_org = DecisionFactory(
            organization=other_org,
            subject="Procurement contract elsewhere",
            publish_timestamp=timezone.now(),
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == matching

    def test_organization_with_amount_range(
        self, user, organization, celery_eager_mode
    ):
        """Organization + amount filter"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            amount_min=Decimal("10000.00"),
            amount_max=Decimal("50000.00"),
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Matching (correct org + amount in range)
        matching = DecisionFactory(
            organization=organization,
            subject="Medium value contract",
            publish_timestamp=timezone.now(),
        )
        matching.amount = Decimal("25000.00")
        matching.save()

        # Non-matching (correct org, amount too low)
        too_low = DecisionFactory(
            organization=organization,
            subject="Small value",
            publish_timestamp=timezone.now(),
        )
        too_low.amount = Decimal("5000.00")
        too_low.save()

        # Non-matching (correct org, amount too high)
        too_high = DecisionFactory(
            organization=organization,
            subject="Large value",
            publish_timestamp=timezone.now(),
        )
        too_high.amount = Decimal("100000.00")
        too_high.save()

        # Non-matching (amount in range, wrong org)
        from conftest import OrganizationFactory

        other_org = OrganizationFactory()
        wrong_org = DecisionFactory(
            organization=other_org,
            subject="Right amount wrong org",
            publish_timestamp=timezone.now(),
        )
        wrong_org.amount = Decimal("30000.00")
        wrong_org.save()

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == matching

    def test_organization_with_decision_types(
        self, user, organization, decision_type, celery_eager_mode
    ):
        """Organization + decision type filter"""
        from conftest import (
            DecisionFactory,
            DecisionTypeFactory,
            NotificationSubscriptionFactory,
        )
        from notifications.tasks import check_single_subscription

        # Create target decision type
        target_type = decision_type

        # Create another decision type
        other_type = DecisionTypeFactory(uid="Δ999", label="Other type")

        sub = NotificationSubscriptionFactory(
            user=user, organization=organization, decision_types=[target_type.uid]
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Matching (correct org + type)
        matching = DecisionFactory(
            organization=organization,
            decision_type=target_type,
            subject="Decision of target type",
            publish_timestamp=timezone.now(),
        )

        # Non-matching (correct org, wrong type)
        wrong_type = DecisionFactory(
            organization=organization,
            decision_type=other_type,
            subject="Decision of other type",
            publish_timestamp=timezone.now(),
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == matching

    def test_organization_with_keyword_and_amount(
        self, user, organization, celery_eager_mode
    ):
        """Organization + keywords + amount range"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["equipment", "purchase"],
            amount_min=Decimal("20000.00"),
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Matching (all criteria met)
        matching = DecisionFactory(
            organization=organization,
            subject="Equipment purchase for department",
            publish_timestamp=timezone.now(),
        )
        matching.amount = Decimal("35000.00")
        matching.save()

        # Non-matching (has keyword, amount too low)
        low_amount = DecisionFactory(
            organization=organization,
            subject="Equipment purchase small",
            publish_timestamp=timezone.now(),
        )
        low_amount.amount = Decimal("15000.00")
        low_amount.save()

        # Non-matching (correct amount, no keyword)
        no_keyword = DecisionFactory(
            organization=organization,
            subject="Administrative matter",
            publish_timestamp=timezone.now(),
        )
        no_keyword.amount = Decimal("25000.00")
        no_keyword.save()

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == matching

    def test_organization_with_all_filters(
        self, user, organization, decision_type, celery_eager_mode
    ):
        """Organization + keywords + amount + decision_type"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["tender"],
            amount_min=Decimal("50000.00"),
            amount_max=Decimal("100000.00"),
            decision_types=[decision_type.uid],
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Matching (all criteria met)
        matching = DecisionFactory(
            organization=organization,
            decision_type=decision_type,
            subject="Public tender announcement",
            publish_timestamp=timezone.now(),
        )
        matching.amount = Decimal("75000.00")
        matching.save()

        # Non-matching (missing keyword)
        no_keyword = DecisionFactory(
            organization=organization,
            decision_type=decision_type,
            subject="General contract",
            publish_timestamp=timezone.now(),
        )
        no_keyword.amount = Decimal("60000.00")
        no_keyword.save()

        # Non-matching (amount out of range)
        wrong_amount = DecisionFactory(
            organization=organization,
            decision_type=decision_type,
            subject="Tender for major project",
            publish_timestamp=timezone.now(),
        )
        wrong_amount.amount = Decimal("150000.00")
        wrong_amount.save()

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == matching


class TestEntityWithFilters:
    """Test entity subscriptions combined with various filters."""

    def test_entity_with_keywords(self, user, afm_entity, celery_eager_mode):
        """Entity + keyword filter"""
        from conftest import DecisionFactory, EntitySubscriptionFactory
        from core.models.entities import DecisionEntityRelationship, EntityRole
        from notifications.tasks import check_single_subscription

        sub = EntitySubscriptionFactory(
            user=user, entity=afm_entity, keywords=["sponsorship", "grant"]
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Matching (entity + keyword)
        matching = DecisionFactory(
            subject="Grant sponsorship program", publish_timestamp=timezone.now()
        )
        DecisionEntityRelationship.objects.create(
            decision=matching,
            entity=afm_entity,
            role=EntityRole.SPONSOR,
            parent_key_path="sponsor[0]",
        )

        # Non-matching (entity but no keyword)
        no_keyword = DecisionFactory(
            subject="Regular contract", publish_timestamp=timezone.now()
        )
        DecisionEntityRelationship.objects.create(
            decision=no_keyword,
            entity=afm_entity,
            role=EntityRole.SPONSOR,
            parent_key_path="sponsor[0]",
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == matching

    def test_entity_with_amount_and_keyword(self, user, afm_entity, celery_eager_mode):
        """Entity + amount + keyword"""
        from conftest import DecisionFactory, EntitySubscriptionFactory
        from core.models.entities import DecisionEntityRelationship, EntityRole
        from notifications.tasks import check_single_subscription

        sub = EntitySubscriptionFactory(
            user=user,
            entity=afm_entity,
            keywords=["consulting"],
            amount_min=Decimal("30000.00"),
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Matching (all criteria)
        matching = DecisionFactory(
            subject="Consulting services contract", publish_timestamp=timezone.now()
        )
        matching.amount = Decimal("40000.00")
        matching.save()
        DecisionEntityRelationship.objects.create(
            decision=matching,
            entity=afm_entity,
            role=EntityRole.SPONSOR,
            parent_key_path="sponsor[0]",
        )

        # Non-matching (entity + keyword, amount too low)
        low_amount = DecisionFactory(
            subject="Small consulting project", publish_timestamp=timezone.now()
        )
        low_amount.amount = Decimal("10000.00")
        low_amount.save()
        DecisionEntityRelationship.objects.create(
            decision=low_amount,
            entity=afm_entity,
            role=EntityRole.SPONSOR,
            parent_key_path="sponsor[0]",
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == matching


class TestRelationshipWithFilters:
    """Test relationship subscriptions with filters."""

    def test_relationship_with_keywords(
        self, user, organization, afm_entity, celery_eager_mode
    ):
        """Relationship + keyword filter"""
        from conftest import DecisionFactory, RelationshipSubscriptionFactory
        from core.models.entities import DecisionEntityRelationship, EntityRole
        from notifications.tasks import check_single_subscription

        sub = RelationshipSubscriptionFactory(
            user=user,
            relationship_org=organization,
            relationship_entity=afm_entity,
            keywords=["partnership", "collaboration"],
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Matching (org + entity + keyword)
        matching = DecisionFactory(
            organization=organization,
            subject="Partnership agreement for collaboration",
            publish_timestamp=timezone.now(),
        )
        DecisionEntityRelationship.objects.create(
            decision=matching,
            entity=afm_entity,
            role=EntityRole.SPONSOR,
            parent_key_path="sponsor[0]",
        )

        # Non-matching (org + entity, no keyword)
        no_keyword = DecisionFactory(
            organization=organization,
            subject="Standard procurement",
            publish_timestamp=timezone.now(),
        )
        DecisionEntityRelationship.objects.create(
            decision=no_keyword,
            entity=afm_entity,
            role=EntityRole.SPONSOR,
            parent_key_path="sponsor[0]",
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == matching

    def test_relationship_with_amount_keyword_type(
        self, user, organization, afm_entity, decision_type, celery_eager_mode
    ):
        """Relationship + all filters (complex combination)"""
        from conftest import DecisionFactory, RelationshipSubscriptionFactory
        from core.models.entities import DecisionEntityRelationship, EntityRole
        from notifications.tasks import check_single_subscription

        sub = RelationshipSubscriptionFactory(
            user=user,
            relationship_org=organization,
            relationship_entity=afm_entity,
            keywords=["services"],
            amount_min=Decimal("100000.00"),
            decision_types=[decision_type.uid],
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Matching (all criteria)
        matching = DecisionFactory(
            organization=organization,
            decision_type=decision_type,
            subject="Professional services contract",
            publish_timestamp=timezone.now(),
        )
        matching.amount = Decimal("150000.00")
        matching.save()
        DecisionEntityRelationship.objects.create(
            decision=matching,
            entity=afm_entity,
            role=EntityRole.SPONSOR,
            parent_key_path="sponsor[0]",
        )

        # Non-matching (all match except amount)
        wrong_amount = DecisionFactory(
            organization=organization,
            decision_type=decision_type,
            subject="Services small contract",
            publish_timestamp=timezone.now(),
        )
        wrong_amount.amount = Decimal("50000.00")
        wrong_amount.save()
        DecisionEntityRelationship.objects.create(
            decision=wrong_amount,
            entity=afm_entity,
            role=EntityRole.SPONSOR,
            parent_key_path="sponsor[0]",
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == matching


class TestSignerWithFilters:
    """Test signer subscriptions with filters."""

    def test_signer_with_keywords(self, user, celery_eager_mode):
        """Signer + keyword filter"""
        from conftest import (
            DecisionFactory,
            NotificationSubscriptionFactory,
            SignerFactory,
        )
        from notifications.tasks import check_single_subscription

        # Create signer
        signer = SignerFactory(first_name="Μαρία", last_name="Κωνσταντίνου")
        signer_name = f"{signer.first_name} {signer.last_name}"

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=None,
            signer_name=signer_name,
            keywords=["approval", "authorization"],
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Matching (signer + keyword)
        matching = DecisionFactory(
            subject="Approval authorization document", publish_timestamp=timezone.now()
        )
        matching.signers.add(signer)

        # Non-matching (signer but no keyword)
        no_keyword = DecisionFactory(
            subject="General administrative note", publish_timestamp=timezone.now()
        )
        no_keyword.signers.add(signer)

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == matching

    def test_signer_with_organization_and_amount(
        self, user, organization, celery_eager_mode
    ):
        """Signer + organization + amount (complex combination)"""
        from conftest import (
            DecisionFactory,
            NotificationSubscriptionFactory,
            SignerFactory,
        )
        from notifications.tasks import check_single_subscription

        # Create signer
        signer = SignerFactory(first_name="Ιωάννης", last_name="Δημητρίου")
        signer_name = f"{signer.first_name} {signer.last_name}"

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            signer_name=signer_name,
            amount_min=Decimal("50000.00"),
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Matching (all criteria)
        matching = DecisionFactory(
            organization=organization,
            subject="Large value contract",
            publish_timestamp=timezone.now(),
        )
        matching.amount = Decimal("80000.00")
        matching.save()
        matching.signers.add(signer)

        # Non-matching (org + signer, amount too low)
        low_amount = DecisionFactory(
            organization=organization,
            subject="Small contract",
            publish_timestamp=timezone.now(),
        )
        low_amount.amount = Decimal("20000.00")
        low_amount.save()
        low_amount.signers.add(signer)

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == matching


class TestAmountOnlyFilters:
    """Test amount-based filtering without specific targets."""

    def test_amount_min_only(self, user, celery_eager_mode):
        """Filter-only subscription with just minimum amount"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user, organization=None, amount_min=Decimal("100000.00")
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Matching (high value)
        matching = DecisionFactory(
            subject="Major infrastructure project", publish_timestamp=timezone.now()
        )
        matching.amount = Decimal("500000.00")
        matching.save()

        # Non-matching (too low)
        too_low = DecisionFactory(
            subject="Small purchase", publish_timestamp=timezone.now()
        )
        too_low.amount = Decimal("50000.00")
        too_low.save()

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == matching

    def test_amount_range(self, user, celery_eager_mode):
        """Filter-only subscription with amount range"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=None,
            amount_min=Decimal("50000.00"),
            amount_max=Decimal("150000.00"),
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Matching (in range)
        matching = DecisionFactory(
            subject="Medium value project", publish_timestamp=timezone.now()
        )
        matching.amount = Decimal("100000.00")
        matching.save()

        # Non-matching (too low)
        too_low = DecisionFactory(
            subject="Small project", publish_timestamp=timezone.now()
        )
        too_low.amount = Decimal("30000.00")
        too_low.save()

        # Non-matching (too high)
        too_high = DecisionFactory(
            subject="Large project", publish_timestamp=timezone.now()
        )
        too_high.amount = Decimal("200000.00")
        too_high.save()

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == matching


class TestDecisionTypeFilters:
    """Test decision type filtering."""

    def test_decision_type_only(self, user, decision_type, celery_eager_mode):
        """Filter-only subscription with just decision type"""
        from conftest import (
            DecisionFactory,
            DecisionTypeFactory,
            NotificationSubscriptionFactory,
        )
        from notifications.tasks import check_single_subscription

        target_type = decision_type
        other_type = DecisionTypeFactory(uid="Δ888", label="Other")

        sub = NotificationSubscriptionFactory(
            user=user, organization=None, decision_types=[target_type.uid]
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Matching
        matching = DecisionFactory(
            decision_type=target_type,
            subject="Decision of target type",
            publish_timestamp=timezone.now(),
        )

        # Non-matching
        non_matching = DecisionFactory(
            decision_type=other_type,
            subject="Decision of other type",
            publish_timestamp=timezone.now(),
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch_decisions = batches.first().batch_decisions.all()
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == matching

    def test_multiple_decision_types(self, user, decision_type, celery_eager_mode):
        """Filter subscription with multiple decision types"""
        from conftest import (
            DecisionFactory,
            DecisionTypeFactory,
            NotificationSubscriptionFactory,
        )
        from notifications.tasks import check_single_subscription

        type1 = decision_type
        type2 = DecisionTypeFactory(uid="Δ777", label="Type 2")
        type3 = DecisionTypeFactory(uid="Δ666", label="Type 3")

        sub = NotificationSubscriptionFactory(
            user=user, organization=None, decision_types=[type1.uid, type2.uid]
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Matching (type1)
        matching1 = DecisionFactory(
            decision_type=type1,
            subject="Type 1 decision",
            publish_timestamp=timezone.now(),
        )

        # Matching (type2)
        matching2 = DecisionFactory(
            decision_type=type2,
            subject="Type 2 decision",
            publish_timestamp=timezone.now(),
        )

        # Non-matching (type3)
        non_matching = DecisionFactory(
            decision_type=type3,
            subject="Type 3 decision",
            publish_timestamp=timezone.now(),
        )

        check_single_subscription(sub.id)

        batch = NotificationBatch.objects.filter(subscription=sub)
        assert batch.count() == 1

        batch_decisions = batch.first().batch_decisions.all()
        assert batch_decisions.count() == 2

        decision_ids = [bd.decision.id for bd in batch_decisions]
        assert matching1.id in decision_ids
        assert matching2.id in decision_ids
        assert non_matching.id not in decision_ids


# ============================================================================
# Edge Cases and Complex Combinations
# ============================================================================


class TestEdgeCasesAndComplexCombinations:
    """Test edge cases and very complex filter combinations."""

    @pytest.mark.parametrize(
        "operator,expected_count",
        [
            ("OR", 3),  # OR: any single keyword matches → 3 decisions
            ("AND", 0),  # AND: all keywords required → 0 decisions (none have all 3)
        ],
    )
    def test_multiple_keywords_operator_behavior(
        self, user, organization, celery_eager_mode, operator, expected_count
    ):
        """Test keyword matching with different operators (OR vs AND)"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["urgent", "critical", "emergency"],
            keyword_match_operator=operator,
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Matches first keyword only
        match1 = DecisionFactory(
            organization=organization,
            subject="Urgent matter requires attention",
            publish_timestamp=timezone.now(),
        )

        # Matches second keyword only
        match2 = DecisionFactory(
            organization=organization,
            subject="Critical infrastructure update",
            publish_timestamp=timezone.now(),
        )

        # Matches multiple keywords (2 out of 3)
        match3 = DecisionFactory(
            organization=organization,
            subject="Emergency urgent response needed",
            publish_timestamp=timezone.now(),
        )

        # Matches none
        no_match = DecisionFactory(
            organization=organization,
            subject="Regular administrative note",
            publish_timestamp=timezone.now(),
        )

        result = check_single_subscription(sub.id)
        number_of_decisions_added = result["decisions_added"]

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert number_of_decisions_added == expected_count
        if expected_count > 0:
            batch_decisions = batches.first().batch_decisions.all()
            assert batch_decisions.count() == expected_count

    def test_no_results_when_no_matches(self, user, organization, celery_eager_mode):
        """Test that no notifications are created when nothing matches"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["impossible-keyword-12345"],
            amount_min=Decimal("999999999.00"),
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Create some decisions that don't match
        DecisionFactory(
            organization=organization,
            subject="Normal decision",
            publish_timestamp=timezone.now(),
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 0

    def test_duplicate_notification_prevention(
        self, user, organization, celery_eager_mode
    ):
        """Test that running check twice doesn't create duplicate notifications"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(user=user, organization=organization)
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        decision = DecisionFactory(
            organization=organization,
            subject="Test decision",
            publish_timestamp=timezone.now(),
        )

        # Run check first time
        result1 = check_single_subscription(sub.id, lookback_days=30)
        notifications1 = NotificationBatch.objects.filter(subscription=sub).count()

        # Run check second time (should not create duplicates)
        result2 = check_single_subscription(sub.id, lookback_days=30)
        notifications2 = NotificationBatch.objects.filter(subscription=sub).count()

        # Should still be the same count
        assert notifications1 == notifications2 == 1

    def test_case_insensitive_keyword_matching(
        self, user, organization, celery_eager_mode
    ):
        """Test that keyword matching is case-insensitive"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        sub = NotificationSubscriptionFactory(
            user=user, organization=organization, keywords=["URGENT"]  # uppercase
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Decision with lowercase keyword
        matching = DecisionFactory(
            organization=organization,
            subject="This is an urgent matter",  # lowercase
            publish_timestamp=timezone.now(),
        )

        check_single_subscription(sub.id)

        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        if batches.count() > 0:
            batch_decisions = batches.first().batch_decisions.all()
            assert batch_decisions.count() == 1
