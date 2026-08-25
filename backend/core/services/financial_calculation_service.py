"""
Centralized service for all financial calculations.
This service abstracts the complexity of the new amount calculation approach
and provides a clean interface for views to use.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from core.models.decisions import Decision, DecisionAmountKAE
from core.models.entities import (
    AFMEntity,
    DecisionAmountField,
    DecisionEntityRelationship,
)
from core.models.organizations import Organization
from core.schemas.financial import (
    AmountConsistency,
    CounterpartPage,
    CounterpartResult,
    DecisionAmountBreakdown,
    DecisionTypeBreakdown,
    EntityAmount,
    EntityDateRange,
    EntityFinancialSummary,
    EntityInfo,
    GlobalFinancialSummary,
    OrgBreakdown,
    OrganizationAmountSummary,
    OrganizationCounterpartPage,
    OrganizationCounterpartResult,
    RelationshipPairPage,
    RelationshipPairResult,
    RoleBreakdown,
    TimelinePoint,
)
from core.services.decision_facets import (
    effective_linked_amount_avg,
    effective_linked_amount_max,
    effective_linked_amount_min,
    effective_linked_amount_sum,
)
from core.utils.performance_monitoring import monitor_query_performance
from django.db.models import Count, F, Max, Min, Q, QuerySet, Sum
from django.db.models.functions import Coalesce


class FinancialCalculationService:
    """
    Central service for all financial calculations using DecisionAmountField and DecisionEntityRelationship.

    This service provides optimized methods for:
    - Entity-based financial calculations (requires entity relationships)
    - Organization-based financial calculations (via entity relationships)
    - Decision-based financial calculations (includes amounts with or without entities)
    - Aggregation and summarization

    Note: Entity and organization calculations naturally filter for amounts linked to entities,
    while decision-level calculations can include unlinked amounts (e.g., decisions with amounts
    but no AFM counterparts).
    """

    # =============================================================================
    # ROLE CONFIGURATION - Critical for Analytics
    # =============================================================================
    # These lists categorize entity relationship roles for financial calculations.
    # ALL analytics endpoints use these to filter which relationships to include.
    #
    # IMPORTANT: When new roles appear in decisions, they MUST be added here!
    #
    # MONEY_RECEIVED_ROLES: Entity receives money (vendor, contractor, grantee, etc.)
    #   - "person", "org": Primary roles in direct assignments (Δ.1) - 11,644+ relationships
    #   - "grantee": Receives grants
    #   - "donationReceiver": Receives donations
    #   - "sponsorAFMName": Sponsor/contractor receiving payment
    #
    # MONEY_PAID_ROLES: Entity pays money (less common)
    #   - "grantor": Gives grants
    #   - "donationGiver": Makes donations
    #
    # TEST COVERAGE: test_financial_calculation_service.py::TestRoleCoverageDefense
    # will FAIL if uncategorized roles appear in the database.
    # =============================================================================

    MONEY_RECEIVED_ROLES = [
        "grantee",
        "donationReceiver",
        "sponsorAFMName",
        "person",
        "org",
    ]
    MONEY_PAID_ROLES = ["grantor", "donationGiver"]

    def __init__(self):
        self.default_currency = "EUR"

    # =============================================================================
    # ENTITY-BASED CALCULATIONS
    # =============================================================================

    @monitor_query_performance(include_context=True)
    def get_entity_total_received(
        self,
        entity: AFMEntity,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        roles: Optional[List[str]] = None,
    ) -> Decimal:
        """
        Calculate total amount received by an entity.

        Args:
            entity: The AFMEntity to calculate for
            start_date: Optional start date filter
            end_date: Optional end date filter
            roles: Optional list of roles to filter by (defaults to MONEY_RECEIVED_ROLES)

        Returns:
            Total amount as Decimal
        """
        if roles is None:
            roles = self.MONEY_RECEIVED_ROLES

        qs = self._get_entity_relationships_queryset(
            entity, start_date, end_date, roles
        )
        result = qs.aggregate(total=effective_linked_amount_sum())
        return result["total"] or Decimal("0.00")

    @monitor_query_performance(include_context=True)
    def get_entity_financial_summary(
        self,
        entity: AFMEntity,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> EntityFinancialSummary:
        """
        Get comprehensive financial summary for an entity.

        Returns:
            EntityFinancialSummary Pydantic model
        """
        received_qs = self._get_entity_relationships_queryset(
            entity, start_date, end_date, self.MONEY_RECEIVED_ROLES
        )

        # Aggregate at database level for performance
        received_stats = received_qs.aggregate(
            total_received=effective_linked_amount_sum(),
            decision_count=Count("decision", distinct=True),
            avg_amount=effective_linked_amount_avg(),
            unique_organizations=Count("decision__organization", distinct=True),
        )

        # Get organization breakdown
        org_breakdown = (
            received_qs.values(
                "decision__organization__uid", "decision__organization__label"
            )
            .annotate(
                total_amount=effective_linked_amount_sum(),
                decision_count=Count("decision", distinct=True),
            )
            .order_by("-total_amount")[:10]
        )  # Top 10 organizations

        # Get role breakdown
        role_breakdown = (
            received_qs.values("role")
            .annotate(
                total_amount=effective_linked_amount_sum(),
                decision_count=Count("decision", distinct=True),
            )
            .order_by("-total_amount")
        )

        return EntityFinancialSummary(
            entity=EntityInfo(
                afm=entity.afm,
                name=entity.name,
                entity_type=entity.entity_type,
            ),
            total_received=received_stats["total_received"] or Decimal("0.00"),
            decision_count=received_stats["decision_count"] or 0,
            avg_amount=received_stats["avg_amount"] or Decimal("0.00"),
            unique_organizations=received_stats["unique_organizations"] or 0,
            top_organizations=[
                OrgBreakdown(
                    organization_uid=row["decision__organization__uid"],
                    organization_label=row["decision__organization__label"],
                    total_amount=row["total_amount"] or Decimal("0.00"),
                    decision_count=row["decision_count"],
                )
                for row in org_breakdown
            ],
            role_breakdown=[
                RoleBreakdown(
                    role=row["role"],
                    total_amount=row["total_amount"] or Decimal("0.00"),
                    decision_count=row["decision_count"],
                )
                for row in role_breakdown
            ],
        )

    @monitor_query_performance(include_context=True)
    def get_entity_timeline_data(
        self,
        entity: AFMEntity,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        granularity: str = "month",
    ) -> list[TimelinePoint]:
        """
        Get timeline data for entity financial activity.

        Args:
            entity: The AFMEntity to get timeline for
            start_date: Optional start date
            end_date: Optional end date
            granularity: 'day', 'month', or 'year'

        Returns:
            List of TimelinePoint Pydantic models
        """
        qs = self._get_entity_relationships_queryset(
            entity, start_date, end_date, self.MONEY_RECEIVED_ROLES
        )

        # Use precomputed indexed fields instead of Trunc functions to allow
        # direct B-tree index scans rather than per-row function evaluation.
        period_column = {
            "day": "decision__issue_date_day",
            "month": "decision__issue_date_month",
            "year": "decision__issue_date_year",
        }.get(granularity, "decision__issue_date_month")

        timeline = (
            qs.annotate(period=F(period_column))
            .values("period")
            .annotate(
                total_amount=effective_linked_amount_sum(),
                decision_count=Count("decision", distinct=True),
            )
            .order_by("period")
        )

        return [
            TimelinePoint(
                period=(
                    str(item["period"])
                    if granularity == "year"
                    else item["period"].strftime(
                        "%Y-%m-%d" if granularity == "day" else "%Y-%m"
                    )
                ),
                total_amount=float(item["total_amount"] or 0),
                decision_count=item["decision_count"],
            )
            for item in timeline
        ]

    @monitor_query_performance(include_context=True)
    def get_entity_date_range(
        self,
        entity: AFMEntity,
    ) -> EntityDateRange:
        """
        Get the available date range and activity overview for an entity.

        Uses the entity's decision relationships to compute the earliest/latest
        decision dates, data span, and recommended chart granularity.  The
        accurate total amount is computed via DecisionAmountField on only the
        entity's decisions (a small filtered subset).

        Args:
            entity: The AFMEntity to get date range for.

        Returns:
            EntityDateRange Pydantic model.  If no decisions exist, returns an
            empty model with all-zero defaults.
        """
        qs = self._get_entity_relationships_queryset(entity)

        date_stats = qs.aggregate(
            earliest_date=Min("decision__issue_date_day"),
            latest_date=Max("decision__issue_date_day"),
            total_decisions=Count("decision", distinct=True),
        )

        if not date_stats["earliest_date"]:
            return EntityDateRange()

        earliest = date_stats["earliest_date"]
        latest = date_stats["latest_date"]
        span_days = (latest - earliest).days

        # Choose granularity based on data span
        if span_days <= 31:
            granularity = "day"
        elif span_days <= 1825:
            granularity = "month"
        else:
            granularity = "year"

        # Accurate total on only this entity's decisions (small subset)
        from django.db.models.functions import Coalesce
        decision_ids = qs.values_list("decision_id", flat=True).distinct()
        accurate_total = (
            DecisionAmountField.objects.filter(
                decision_id__in=decision_ids,
                associated_relationship__isnull=False,
            ).aggregate(total=Sum(Coalesce("verified_amount", "amount")))["total"]
            or Decimal("0.00")
        )

        return EntityDateRange(
            earliest_date=earliest,
            latest_date=latest,
            span_days=span_days,
            recommended_granularity=granularity,
            total_decisions=date_stats["total_decisions"] or 0,
            total_amount=float(accurate_total),
            avg_daily_decisions=round(
                (date_stats["total_decisions"] or 0) / max(span_days, 1), 2
            ),
            avg_daily_amount=round(float(accurate_total) / max(span_days, 1), 2),
        )

    # =============================================================================
    # ORGANIZATION-BASED CALCULATIONS
    # =============================================================================

    def get_organization_total_expenditures(
        self,
        organization: Organization,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        roles: Optional[List[str]] = None,
    ) -> Decimal:
        """
        Calculate total expenditures by an organization.
        """
        if roles is None:
            roles = self.MONEY_RECEIVED_ROLES  # Money paid TO entities

        qs = self._get_organization_relationships_queryset(
            organization, start_date, end_date, roles
        )
        result = qs.aggregate(total=effective_linked_amount_sum())
        return result["total"] or Decimal("0.00")

    def get_organization_expenditure_breakdown(
        self,
        organization: Organization,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        group_by: str = "entity",
    ) -> List[Dict[str, Any]]:
        """
        Get breakdown of organization expenditures.

        Args:
            organization: Organization to analyze
            start_date: Optional start date
            end_date: Optional end date
            group_by: 'entity', 'month', 'year', or 'decision_type'
        """
        qs = self._get_organization_relationships_queryset(
            organization, start_date, end_date, self.MONEY_RECEIVED_ROLES
        )

        if group_by == "entity":
            breakdown = (
                qs.values("entity__afm", "entity__name")
                .annotate(
                    total_amount=effective_linked_amount_sum(),
                    decision_count=Count("decision", distinct=True),
                )
                .order_by("-total_amount")
            )

        elif group_by in ["month", "year"]:
            period_column = (
                "decision__issue_date_month"
                if group_by == "month"
                else "decision__issue_date_year"
            )
            breakdown = (
                qs.annotate(period=F(period_column))
                .values("period")
                .annotate(
                    total_amount=effective_linked_amount_sum(),
                    decision_count=Count("decision", distinct=True),
                )
                .order_by("period")
            )

        elif group_by == "decision_type":
            breakdown = (
                qs.values(
                    "decision__decision_type__uid", "decision__decision_type__label"
                )
                .annotate(
                    total_amount=effective_linked_amount_sum(),
                    decision_count=Count("decision", distinct=True),
                )
                .order_by("-total_amount")
            )

        else:
            raise ValueError(f"Invalid group_by parameter: {group_by}")

        return list(breakdown)

    @monitor_query_performance(operation="top_counterparts_for_org")
    def get_top_counterparts_for_organization(
        self,
        organization: Organization,
        start_date: datetime,
        end_date: datetime,
        limit: int = 5,
        offset: int = 0,
        roles: Optional[List[str]] = None,
        direct_assignments_only: bool = False,
        search_query: Optional[str] = None,
    ) -> CounterpartPage:
        """
        Get top entities by total amount for an organization in a date range.
        Optimized for pagination with caching support.

        Args:
            organization: Organization to analyze
            start_date: Start of date range
            end_date: End of date range
            limit: Number of results to return
            offset: Pagination offset
            roles: Optional list of roles to filter by (defaults to MONEY_RECEIVED_ROLES)
            direct_assignments_only: If True, filters to direct-assignment decisions only
            search_query: Optional entity name search filter (case-insensitive contains)

        Returns:
            CounterpartPage Pydantic model with 'results', 'total_count', and 'has_more'
        """
        if roles is None:
            roles = self.MONEY_RECEIVED_ROLES

        # Build base filter
        base_filter = dict(
            decision__organization=organization,
            decision__issue_date_day__gte=start_date,
            decision__issue_date_day__lte=end_date,
            role__in=roles,
        )
        if direct_assignments_only:
            base_filter["decision__classification__is_direct_assignment"] = True

        # Apply search filter on counterpart entity names.
        # Scope FTS to only the entities already appearing as counterparts
        # (organization + date range), avoiding an unconstrained search across ALL entities.
        qs = DecisionEntityRelationship.objects.filter(**base_filter)
        if search_query:
            from core.services.search_service import SearchService
            from django.db.models import Q

            counterpart_afms = qs.values_list("entity__afm", flat=True).distinct()

            # Short queries fall back to icontains (FTS needs ≥3 chars for lexemes)
            if SearchService._is_query_too_short_for_fts(search_query):
                matching_afms = AFMEntity.objects.filter(
                    afm__in=counterpart_afms,
                ).filter(
                    Q(name__icontains=search_query)
                    | Q(afm__icontains=search_query)
                ).values_list("afm", flat=True)
            else:
                from django.contrib.postgres.search import SearchQuery

                fts_query = SearchService._build_prefix_search_query(search_query)
                matching_afms = AFMEntity.objects.filter(
                    afm__in=counterpart_afms,
                    search_vector=fts_query,
                ).values_list("afm", flat=True)

            if matching_afms:
                qs = qs.filter(entity__afm__in=matching_afms)
            else:
                return CounterpartPage(results=[], total_count=0, has_more=False)

        # Query with pagination
        results = list(
            qs
            .values("entity__afm", "entity__name", "entity__entity_type")
            .annotate(
                total_amount=effective_linked_amount_sum(),
                decision_count=Count("decision", distinct=True),
                avg_amount=effective_linked_amount_avg(),
                max_amount=effective_linked_amount_max(),
                min_amount=effective_linked_amount_min(),
            )
            .filter(total_amount__gt=0)  # Only entities with amounts
            .order_by("-total_amount")[offset : offset + limit]
        )

        # Get total count for pagination UI
        total_count = (
            qs.values("entity")
            .distinct()
            .count()
        )

        return CounterpartPage(
            results=[
                CounterpartResult(
                    entity_afm=row["entity__afm"],
                    entity_name=row["entity__name"],
                    entity_type=row["entity__entity_type"],
                    total_amount=row["total_amount"] or Decimal("0.00"),
                    decision_count=row["decision_count"],
                    avg_amount=row.get("avg_amount"),
                    max_amount=row.get("max_amount"),
                    min_amount=row.get("min_amount"),
                )
                for row in results
            ],
            total_count=total_count,
            has_more=offset + limit < total_count,
        )

    @monitor_query_performance(operation="top_organizations_for_entity")
    def get_top_organizations_for_entity(
        self,
        entity: AFMEntity,
        start_date: datetime,
        end_date: datetime,
        limit: int = 5,
        offset: int = 0,
        roles: Optional[List[str]] = None,
        direct_assignments_only: bool = False,
        search_query: Optional[str] = None,
    ) -> OrganizationCounterpartPage:
        """
        Get top organizations by total amount for an entity in a date range.

        This is the inverse of get_top_counterparts_for_organization: instead of
        finding which entities received money from an organization, this finds
        which organizations paid money to a specific entity.

        Args:
            entity: AFMEntity to analyze
            start_date: Start of date range
            end_date: End of date range
            limit: Number of results to return
            offset: Pagination offset
            roles: Optional list of roles to filter by (defaults to MONEY_RECEIVED_ROLES)
            direct_assignments_only: If True, filters to direct-assignment decisions only
            search_query: Optional organization name search filter

        Returns:
            OrganizationCounterpartPage with 'results', 'total_count', and 'has_more'
        """
        if roles is None:
            roles = self.MONEY_RECEIVED_ROLES

        # Build base filter
        base_filter = dict(
            entity=entity,
            decision__issue_date_day__gte=start_date,
            decision__issue_date_day__lte=end_date,
            role__in=roles,
        )
        if direct_assignments_only:
            base_filter["decision__classification__is_direct_assignment"] = True

        qs = DecisionEntityRelationship.objects.filter(**base_filter)

        # Apply search filter on counterpart organization names.
        # Scope FTS to only the organizations already appearing as counterparts
        # (entity + date range), avoiding an unconstrained search across ALL orgs.
        if search_query:
            from core.services.search_service import SearchService

            counterpart_uids = qs.values_list(
                "decision__organization__uid", flat=True
            ).distinct()

            # Short queries fall back to icontains (FTS needs ≥3 chars for lexemes)
            if SearchService._is_query_too_short_for_fts(search_query):
                matching_uids = Organization.objects.filter(
                    uid__in=counterpart_uids,
                ).filter(
                    Q(label__icontains=search_query)
                    | Q(latin_name__icontains=search_query)
                ).values_list("uid", flat=True)
            else:
                from django.contrib.postgres.search import SearchQuery

                fts_query = SearchService._build_prefix_search_query(search_query)
                matching_uids = Organization.objects.filter(
                    uid__in=counterpart_uids,
                    search_vector=fts_query,
                ).values_list("uid", flat=True)

            if matching_uids:
                qs = qs.filter(decision__organization__uid__in=matching_uids)
            else:
                return OrganizationCounterpartPage(
                    results=[], total_count=0, has_more=False
                )

        # Query with pagination
        results = list(
            qs
            .values("decision__organization__uid", "decision__organization__label")
            .annotate(
                total_amount=effective_linked_amount_sum(),
                decision_count=Count("decision", distinct=True),
            )
            .filter(total_amount__gt=0)
            .order_by("-total_amount")[offset : offset + limit]
        )

        # Get total count for pagination UI
        total_count = (
            qs.values("decision__organization")
            .distinct()
            .count()
        )

        return OrganizationCounterpartPage(
            results=[
                OrganizationCounterpartResult(
                    organization_uid=row["decision__organization__uid"],
                    organization_label=row["decision__organization__label"],
                    total_amount=row["total_amount"] or Decimal("0.00"),
                    decision_count=row["decision_count"],
                )
                for row in results
            ],
            total_count=total_count,
            has_more=offset + limit < total_count,
        )

    @monitor_query_performance(operation="top_relationship_pairs")
    def get_top_relationship_pairs(
        self,
        start_date: datetime,
        end_date: datetime,
        limit: int = 10,
        offset: int = 0,
        roles: Optional[List[str]] = None,
        direct_assignments_only: bool = False,
    ) -> RelationshipPairPage:
        """
        Get top organization-entity pairs by total amount across all relationships.
        Used for temporal exploration to find which Org×Entity combinations had
        the highest transaction amounts in a date range.

        Args:
            start_date: Start of date range
            end_date: End of date range
            limit: Number of results to return
            offset: Pagination offset
            roles: Optional list of roles to filter by (defaults to MONEY_RECEIVED_ROLES)
            direct_assignments_only: If True, filters to direct-assignment decisions only

        Returns:
            RelationshipPairPage Pydantic model with 'results', 'total_count', and 'has_more'
        """
        if roles is None:
            roles = self.MONEY_RECEIVED_ROLES

        # Build base filter
        base_filter = dict(
            decision__issue_date_day__gte=start_date,
            decision__issue_date_day__lte=end_date,
            role__in=roles,
        )
        if direct_assignments_only:
            base_filter["decision__classification__is_direct_assignment"] = True

        # Query: Group by both organization AND entity
        results = list(
            DecisionEntityRelationship.objects.filter(**base_filter)
            .values(
                "decision__organization__uid",
                "decision__organization__label",
                "entity__afm",
                "entity__name",
                "entity__entity_type",
            )
            .annotate(
                total_amount=effective_linked_amount_sum(),
                decision_count=Count("decision", distinct=True),
            )
            .filter(total_amount__gt=0)
            .order_by("-total_amount")[offset : offset + limit]
        )

        # Get total count of unique org-entity pairs
        total_count = (
            DecisionEntityRelationship.objects.filter(**base_filter)
            .values("decision__organization", "entity")
            .distinct()
            .count()
        )

        return RelationshipPairPage(
            results=[
                RelationshipPairResult(
                    organization_uid=row["decision__organization__uid"],
                    organization_label=row["decision__organization__label"],
                    entity_afm=row["entity__afm"],
                    entity_name=row["entity__name"],
                    entity_type=row["entity__entity_type"],
                    total_amount=row["total_amount"] or Decimal("0.00"),
                    decision_count=row["decision_count"],
                )
                for row in results
            ],
            total_count=total_count,
            has_more=offset + limit < total_count,
        )

    @monitor_query_performance(operation="org_list_with_amounts")
    def get_organization_list_with_amounts(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 50,
    ) -> list[OrganizationAmountSummary]:
        """
        Get organizations with decision activity and accurate financial totals.

        Used by temporal exploration to list organizations active in a date
        range.  Accurate totals are computed via DecisionAmountField on the
        date-filtered subset — not a full table scan.

        Args:
            start_date: Optional start date filter.
            end_date: Optional end date filter.
            limit: Maximum number of organizations to return.

        Returns:
            List of OrganizationAmountSummary Pydantic models, ordered by
            decision count descending.
        """
        from core.services.decision_facets import (
            effective_amount_max,
            effective_amount_sum,
        )

        qs = Decision.objects.all()
        if start_date:
            qs = qs.filter(issue_date_day__gte=start_date)
        if end_date:
            qs = qs.filter(issue_date_day__lte=end_date)

        organizations = (
            qs.values("organization__uid", "organization__label")
            .annotate(
                count=Count("id", distinct=True),
                total_amount=effective_amount_sum(
                    filter=Q(amount_fields__associated_relationship__isnull=False),
                ),
                max_amount=effective_amount_max(),
            )
            .filter(organization__uid__isnull=False)
            .order_by("-count")[:limit]
        )

        return [
            OrganizationAmountSummary(
                uid=org["organization__uid"],
                label=org["organization__label"],
                count=org["count"],
                total_amount=float(org["total_amount"] or 0),
                avg_amount=(
                    float(org["total_amount"] or 0) / org["count"]
                    if org["count"] > 0
                    else 0.0
                ),
                max_amount=float(org["max_amount"] or 0),
            )
            for org in organizations
        ]

    # =============================================================================
    # DECISION-BASED CALCULATIONS
    # =============================================================================

    def get_decision_total_amount(
        self, decision: Decision, include_unlinked: bool = True
    ) -> Decimal:
        """
        Get total amount for a specific decision from all amounts.

        Each ``DecisionAmountField`` may carry a ``verified_amount`` (set by
        the cents-based amount correction service).  The total sums
        ``COALESCE(verified_amount, amount)`` so corrected values take
        precedence automatically.

        Args:
            decision: The decision to calculate for
            include_unlinked: If True (default), includes amounts not linked to entities.
                            If False, only includes amounts linked to entity relationships.

        Returns:
            Total amount as Decimal
        """
        from django.db.models.functions import Coalesce

        qs = DecisionAmountField.objects.filter(decision=decision)

        if not include_unlinked:
            qs = qs.filter(associated_relationship__isnull=False)

        result = qs.aggregate(
            total=Sum(Coalesce("verified_amount", "amount"))
        )
        return result["total"] or Decimal("0.00")

    def get_decision_entity_amounts(self, decision: Decision) -> list[EntityAmount]:
        """
        Get all entity-amount pairs for a decision.
        """
        relationships = (
            DecisionEntityRelationship.objects.filter(decision=decision)
            .select_related("entity")
            .prefetch_related("linked_amounts")
        )

        entity_amounts: list[EntityAmount] = []
        for rel in relationships:
            total_amount = sum(
                amount.verified_amount
                if amount.verified_amount is not None
                else amount.amount
                for amount in rel.linked_amounts.all()
                if amount.amount is not None
            )

            if total_amount > 0:  # Only include entities with actual amounts
                entity_amounts.append(
                    EntityAmount(
                        entity=EntityInfo(
                            afm=rel.entity.afm,
                            name=rel.entity.name,
                            entity_type=rel.entity.entity_type,
                        ),
                        role=rel.role,
                        total_amount=total_amount,
                        amount_count=rel.linked_amounts.count(),
                    )
                )

        return sorted(entity_amounts, key=lambda x: x.total_amount, reverse=True)

    def get_decisions_entity_amounts_batch(
        self, decision_ids: list[int]
    ) -> dict[int, list[EntityAmount]]:
        """
        Batch version: get entity-amount pairs for multiple decisions in one query.

        Eliminates the N+1 pattern when looping over decisions to compute entity amounts.
        Uses a single aggregation query grouped by decision and entity relationship,
        then organizes results by decision_id for fast lookup.

        Args:
            decision_ids: List of Decision primary keys.

        Returns:
            Dict mapping decision_id → list of EntityAmount for that decision.
        """
        if not decision_ids:
            return {}

        relationships = (
            DecisionEntityRelationship.objects.filter(decision_id__in=decision_ids)
            .select_related("entity")
            .annotate(total_amount=effective_linked_amount_sum())
        )

        result: dict[int, list[EntityAmount]] = {did: [] for did in decision_ids}
        for rel in relationships:
            if rel.total_amount and rel.total_amount > 0:
                result[rel.decision_id].append(
                    EntityAmount(
                        entity=EntityInfo(
                            afm=rel.entity.afm,
                            name=rel.entity.name,
                            entity_type=rel.entity.entity_type,
                        ),
                        role=rel.role,
                        total_amount=rel.total_amount,
                        amount_count=DecisionAmountField.objects.filter(
                            associated_relationship=rel
                        ).count(),
                    )
                )

        # Sort each decision's entity amounts by total_amount descending
        for did in result:
            result[did].sort(key=lambda x: x.total_amount, reverse=True)

        return result

    def get_decision_amount_breakdown(self, decision: Decision) -> DecisionAmountBreakdown:
        """
        Get breakdown of amounts for a decision, distinguishing between
        linked (with entities) and unlinked (without entities) amounts.

        This is useful for understanding decisions that have amounts but no counterparts/entities.

        Returns:
            DecisionAmountBreakdown Pydantic model
        """
        all_amounts = DecisionAmountField.objects.filter(decision=decision)

        linked_total = all_amounts.filter(
            associated_relationship__isnull=False
        ).aggregate(total=Sum(Coalesce("verified_amount", "amount")))["total"] or Decimal("0.00")

        unlinked_total = all_amounts.filter(
            associated_relationship__isnull=True
        ).aggregate(total=Sum(Coalesce("verified_amount", "amount")))["total"] or Decimal("0.00")

        entity_count = DecisionEntityRelationship.objects.filter(
            decision=decision
        ).count()

        return DecisionAmountBreakdown(
            decision_ada=decision.ada,
            linked_total=linked_total,
            unlinked_total=unlinked_total,
            total_amount=linked_total + unlinked_total,
            entity_count=entity_count,
            has_entities=entity_count > 0,
            has_unlinked_amounts=unlinked_total > 0,
            all_amounts_linked=unlinked_total == 0,
        )

    @monitor_query_performance(operation="decision_types_breakdown")
    def get_decision_types_breakdown(
        self,
        decisions_qs: QuerySet,
    ) -> list[DecisionTypeBreakdown]:
        """
        Get breakdown of decision types with accurate financial totals.

        The caller is responsible for pre-filtering the queryset (by date range,
        entity, organization, etc.).  This method then groups by decision type
        and computes accurate totals via DecisionAmountField on that filtered
        subset.

        Args:
            decisions_qs: A pre-filtered Decision queryset.

        Returns:
            List of DecisionTypeBreakdown Pydantic models, ordered by decision
            count descending.
        """
        from core.services.decision_facets import (
            effective_amount_max,
            effective_amount_sum,
        )

        decision_types = (
            decisions_qs.values("decision_type__uid", "decision_type__label")
            .annotate(
                count=Count("id", distinct=True),
                total_amount=effective_amount_sum(
                    filter=Q(amount_fields__associated_relationship__isnull=False),
                ),
                max_amount=effective_amount_max(),
            )
            .filter(decision_type__uid__isnull=False)
            .order_by("-count")
        )

        return [
            DecisionTypeBreakdown(
                uid=dt["decision_type__uid"],
                label=dt["decision_type__label"],
                count=dt["count"],
                total_amount=float(dt["total_amount"] or 0),
                avg_amount=(
                    float(dt["total_amount"] or 0) / dt["count"]
                    if dt["count"] > 0
                    else 0.0
                ),
                max_amount=float(dt["max_amount"] or 0),
            )
            for dt in decision_types
        ]

    # =============================================================================
    # UTILITY METHODS
    # =============================================================================

    def _get_entity_relationships_queryset(
        self,
        entity: AFMEntity,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        roles: Optional[List[str]] = None,
    ) -> QuerySet:
        """
        Get optimized queryset for entity relationships with proper prefetching.
        """
        qs = DecisionEntityRelationship.objects.filter(entity=entity)

        if roles:
            qs = qs.filter(role__in=roles)

        if start_date:
            qs = qs.filter(decision__issue_date_day__gte=start_date)

        if end_date:
            qs = qs.filter(decision__issue_date_day__lte=end_date)

        # Optimize with proper joins
        return qs.select_related(
            "decision", "decision__organization", "decision__decision_type", "entity"
        )

    def _get_organization_relationships_queryset(
        self,
        organization: Organization,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        roles: Optional[List[str]] = None,
    ) -> QuerySet:
        """
        Get optimized queryset for organization relationships.
        """
        qs = DecisionEntityRelationship.objects.filter(
            decision__organization=organization
        )

        if roles:
            qs = qs.filter(role__in=roles)

        if start_date:
            qs = qs.filter(decision__issue_date_day__gte=start_date)

        if end_date:
            qs = qs.filter(decision__issue_date_day__lte=end_date)

        return qs.select_related(
            "decision", "decision__organization", "decision__decision_type", "entity"
        )

    def validate_amount_consistency(self, decision: Decision) -> AmountConsistency:
        """
        Validate that amounts are consistent with decision amount field.
        Useful for data integrity checks.

        This now includes both linked and unlinked amounts for full accuracy.
        """
        # Get total from all amounts (linked and unlinked)
        total_from_amount_fields = self.get_decision_total_amount(
            decision, include_unlinked=True
        )

        # Get just linked amounts for comparison
        linked_total = self.get_decision_total_amount(decision, include_unlinked=False)

        # Get decision's primary amount field
        decision_amount = decision.amount or Decimal("0.00")

        # Calculate KAE total for comparison
        kae_total = DecisionAmountKAE.objects.filter(decision=decision).aggregate(
            total=Sum("amount")
        )["total"] or Decimal("0.00")

        # Calculate discrepancy (use total from amount fields, not just linked)
        discrepancy = (
            abs(total_from_amount_fields - decision_amount) if decision_amount else None
        )
        discrepancy_percentage = (
            (discrepancy / decision_amount * 100)
            if decision_amount and discrepancy
            else None
        )

        return AmountConsistency(
            decision_ada=decision.ada,
            total_from_amount_fields=total_from_amount_fields,
            linked_amounts_total=linked_total,
            unlinked_amounts_total=total_from_amount_fields - linked_total,
            decision_amount_field=decision_amount,
            kae_total=kae_total,
            discrepancy=discrepancy,
            discrepancy_percentage=discrepancy_percentage,
            is_consistent=discrepancy is None
            or discrepancy <= Decimal("0.01"),  # 1 cent tolerance
        )

    @monitor_query_performance(operation="global_financial_summary")
    def get_global_financial_summary(self, decisions_queryset=None):
        """
        Get comprehensive financial summary across all decisions in the system
        Uses the new relationship-based calculation approach

        Args:
            decisions_queryset: Optional queryset to filter decisions, defaults to all

        Returns:
            Dict with total_amount, total_decisions, avg_amount, calculation_method
        """
        # Use provided queryset or all decisions
        if decisions_queryset is None:
            decisions_queryset = Decision.objects.all()

        # Get total from DecisionAmountField for all decisions in queryset
        # This represents the most accurate financial data via relationships
        total_amount_accurate = DecisionAmountField.objects.filter(
            decision__in=decisions_queryset
        ).aggregate(total=Sum(Coalesce("verified_amount", "amount")))["total"] or Decimal("0.00")

        # Get decision count and basic stats
        decision_stats = decisions_queryset.aggregate(
            total_decisions=Count("id"), legacy_total=Sum("amount")  # For comparison
        )

        avg_amount = (
            total_amount_accurate / decision_stats["total_decisions"]
            if decision_stats["total_decisions"] > 0
            else Decimal("0.00")
        )

        return GlobalFinancialSummary(
            total_amount=total_amount_accurate,
            total_decisions=decision_stats["total_decisions"],
            avg_amount=avg_amount,
            legacy_total_amount=decision_stats["legacy_total"] or Decimal("0.00"),
            calculation_method="relationship_based",
            accuracy_improvement=abs(
                total_amount_accurate
                - (decision_stats["legacy_total"] or Decimal("0.00"))
            ),
        )

    @monitor_query_performance(operation="global_timeline")
    def get_global_timeline(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        granularity: str = "month",
    ) -> list[TimelinePoint]:
        """
        Get global timeline data for all decisions in a date range.

        Uses DecisionAmountField for accurate total amounts on the filtered
        subset.  Unlike the date-range discovery endpoint (which has no date
        filter and must scan everything), this method requires a date range and
        therefore computes accurate totals efficiently.

        Args:
            start_date: Start of date range (required for performance).
            end_date: End of date range (required for performance).
            granularity: 'day', 'month', or 'year'.

        Returns:
            List of TimelinePoint Pydantic models.
        """
        qs = Decision.objects.all()
        if start_date:
            qs = qs.filter(issue_date_day__gte=start_date)
        if end_date:
            qs = qs.filter(issue_date_day__lte=end_date)

        period_column = {
            "day": "issue_date_day",
            "month": "issue_date_month",
            "year": "issue_date_year",
        }.get(granularity, "issue_date_month")

        from core.services.decision_facets import effective_amount_sum

        # Annotate each decision with accurate total from linked amounts
        timeline = (
            qs.annotate(period=F(period_column))
            .annotate(
                accurate_total=effective_amount_sum(
                    filter=Q(amount_fields__associated_relationship__isnull=False),
                )
            )
            .values("period")
            .annotate(
                total_amount=Sum("accurate_total"),
                decision_count=Count("id"),
            )
            .order_by("period")
        )

        return [
            TimelinePoint(
                period=(
                    str(item["period"])
                    if granularity == "year"
                    else item["period"].strftime(
                        "%Y-%m-%d" if granularity == "day" else "%Y-%m"
                    )
                ),
                total_amount=float(item["total_amount"] or 0),
                decision_count=item["decision_count"],
            )
            for item in timeline
        ]


# Singleton instance for easy importing
financial_service = FinancialCalculationService()
