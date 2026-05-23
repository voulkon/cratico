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
from core.utils.performance_monitoring import monitor_query_performance
from django.db.models import Avg, Count, QuerySet, Sum
from django.db.models.functions import TruncDay, TruncMonth, TruncYear


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
        result = qs.aggregate(total=Sum("linked_amounts__amount"))
        return result["total"] or Decimal("0.00")

    @monitor_query_performance(include_context=True)
    def get_entity_financial_summary(
        self,
        entity: AFMEntity,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Get comprehensive financial summary for an entity.

        Returns:
            Dictionary with financial statistics
        """
        received_qs = self._get_entity_relationships_queryset(
            entity, start_date, end_date, self.MONEY_RECEIVED_ROLES
        )

        # Aggregate at database level for performance
        received_stats = received_qs.aggregate(
            total_received=Sum("linked_amounts__amount"),
            decision_count=Count("decision", distinct=True),
            avg_amount=Avg("linked_amounts__amount"),
            unique_organizations=Count("decision__organization", distinct=True),
        )

        # Get organization breakdown
        org_breakdown = (
            received_qs.values(
                "decision__organization__uid", "decision__organization__label"
            )
            .annotate(
                total_amount=Sum("linked_amounts__amount"),
                decision_count=Count("decision", distinct=True),
            )
            .order_by("-total_amount")[:10]
        )  # Top 10 organizations

        # Get role breakdown
        role_breakdown = (
            received_qs.values("role")
            .annotate(
                total_amount=Sum("linked_amounts__amount"),
                decision_count=Count("decision", distinct=True),
            )
            .order_by("-total_amount")
        )

        return {
            "total_received": received_stats["total_received"] or Decimal("0.00"),
            "decision_count": received_stats["decision_count"] or 0,
            "avg_amount": received_stats["avg_amount"] or Decimal("0.00"),
            "unique_organizations": received_stats["unique_organizations"] or 0,
            "top_organizations": list(org_breakdown),
            "role_breakdown": list(role_breakdown),
            "entity_info": {
                "afm": entity.afm,
                "name": entity.name,
                "entity_type": entity.entity_type,
            },
        }

    @monitor_query_performance(include_context=True)
    def get_entity_timeline_data(
        self,
        entity: AFMEntity,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        granularity: str = "month",
    ) -> List[Dict[str, Any]]:
        """
        Get timeline data for entity financial activity.

        Args:
            entity: The AFMEntity to get timeline for
            start_date: Optional start date
            end_date: Optional end date
            granularity: 'day', 'month', or 'year'

        Returns:
            List of timeline data points
        """
        qs = self._get_entity_relationships_queryset(
            entity, start_date, end_date, self.MONEY_RECEIVED_ROLES
        )

        # Choose truncation function based on granularity
        trunc_function = {"day": TruncDay, "month": TruncMonth, "year": TruncYear}.get(
            granularity, TruncMonth
        )

        timeline = (
            qs.annotate(period=trunc_function("decision__issue_date"))
            .values("period")
            .annotate(
                total_amount=Sum("linked_amounts__amount"),
                decision_count=Count("decision", distinct=True),
            )
            .order_by("period")
        )

        return [
            {
                "period": item["period"].strftime(
                    "%Y-%m-%d"
                    if granularity == "day"
                    else "%Y-%m" if granularity == "month" else "%Y"
                ),
                "total_amount": float(item["total_amount"] or 0),
                "decision_count": item["decision_count"],
            }
            for item in timeline
        ]

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
        result = qs.aggregate(total=Sum("linked_amounts__amount"))
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
                    total_amount=Sum("linked_amounts__amount"),
                    decision_count=Count("decision", distinct=True),
                )
                .order_by("-total_amount")
            )

        elif group_by in ["month", "year"]:
            trunc_function = TruncMonth if group_by == "month" else TruncYear
            breakdown = (
                qs.annotate(period=trunc_function("decision__issue_date"))
                .values("period")
                .annotate(
                    total_amount=Sum("linked_amounts__amount"),
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
                    total_amount=Sum("linked_amounts__amount"),
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
    ) -> Dict[str, Any]:
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

        Returns:
            Dict with 'results', 'total_count', and 'has_more' for pagination
        """
        if roles is None:
            roles = self.MONEY_RECEIVED_ROLES

        # Query with pagination
        results = list(
            DecisionEntityRelationship.objects.filter(
                decision__organization=organization,
                decision__issue_date__gte=start_date,
                decision__issue_date__lte=end_date,
                role__in=roles,
            )
            .values("entity__afm", "entity__name", "entity__entity_type")
            .annotate(
                total_amount=Sum("linked_amounts__amount"),
                decision_count=Count("decision", distinct=True),
            )
            .filter(total_amount__gt=0)  # Only entities with amounts
            .order_by("-total_amount")[offset : offset + limit]
        )

        # Get total count for pagination UI
        total_count = (
            DecisionEntityRelationship.objects.filter(
                decision__organization=organization,
                decision__issue_date__gte=start_date,
                decision__issue_date__lte=end_date,
                role__in=roles,
            )
            .values("entity")
            .distinct()
            .count()
        )

        return {
            "results": results,
            "total_count": total_count,
            "has_more": offset + limit < total_count,
        }

    @monitor_query_performance(operation="top_relationship_pairs")
    def get_top_relationship_pairs(
        self,
        start_date: datetime,
        end_date: datetime,
        limit: int = 10,
        offset: int = 0,
        roles: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
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

        Returns:
            Dict with 'results', 'total_count', and 'has_more' for pagination
        """
        if roles is None:
            roles = self.MONEY_RECEIVED_ROLES

        # Query: Group by both organization AND entity
        results = list(
            DecisionEntityRelationship.objects.filter(
                decision__issue_date__gte=start_date,
                decision__issue_date__lte=end_date,
                role__in=roles,
            )
            .values(
                "decision__organization__uid",
                "decision__organization__label",
                "entity__afm",
                "entity__name",
                "entity__entity_type",
            )
            .annotate(
                total_amount=Sum("linked_amounts__amount"),
                decision_count=Count("decision", distinct=True),
            )
            .filter(total_amount__gt=0)
            .order_by("-total_amount")[offset : offset + limit]
        )

        # Get total count of unique org-entity pairs
        total_count = (
            DecisionEntityRelationship.objects.filter(
                decision__issue_date__gte=start_date,
                decision__issue_date__lte=end_date,
                role__in=roles,
            )
            .values("decision__organization", "entity")
            .distinct()
            .count()
        )

        return {
            "results": results,
            "total_count": total_count,
            "has_more": offset + limit < total_count,
        }

    # =============================================================================
    # DECISION-BASED CALCULATIONS
    # =============================================================================

    def get_decision_total_amount(
        self, decision: Decision, include_unlinked: bool = True
    ) -> Decimal:
        """
        Get total amount for a specific decision from all amounts.

        Args:
            decision: The decision to calculate for
            include_unlinked: If True (default), includes amounts not linked to entities.
                            If False, only includes amounts linked to entity relationships.

        Returns:
            Total amount as Decimal
        """
        qs = DecisionAmountField.objects.filter(decision=decision)

        if not include_unlinked:
            qs = qs.filter(associated_relationship__isnull=False)

        result = qs.aggregate(total=Sum("amount"))
        return result["total"] or Decimal("0.00")

    def get_decision_entity_amounts(self, decision: Decision) -> List[Dict[str, Any]]:
        """
        Get all entity-amount pairs for a decision.
        """
        relationships = (
            DecisionEntityRelationship.objects.filter(decision=decision)
            .select_related("entity")
            .prefetch_related("linked_amounts")
        )

        entity_amounts = []
        for rel in relationships:
            total_amount = sum(
                amount.amount
                for amount in rel.linked_amounts.all()
                if amount.amount is not None
            )

            if total_amount > 0:  # Only include entities with actual amounts
                entity_amounts.append(
                    {
                        "entity": {
                            "afm": rel.entity.afm,
                            "name": rel.entity.name,
                            "entity_type": rel.entity.entity_type,
                        },
                        "role": rel.role,
                        "total_amount": total_amount,
                        "amount_count": rel.linked_amounts.count(),
                    }
                )

        return sorted(entity_amounts, key=lambda x: x["total_amount"], reverse=True)

    def get_decision_amount_breakdown(self, decision: Decision) -> Dict[str, Any]:
        """
        Get breakdown of amounts for a decision, distinguishing between
        linked (with entities) and unlinked (without entities) amounts.

        This is useful for understanding decisions that have amounts but no counterparts/entities.

        Returns:
            Dictionary with linked_total, unlinked_total, total, has_entities, etc.
        """
        all_amounts = DecisionAmountField.objects.filter(decision=decision)

        linked_total = all_amounts.filter(
            associated_relationship__isnull=False
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        unlinked_total = all_amounts.filter(
            associated_relationship__isnull=True
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        entity_count = DecisionEntityRelationship.objects.filter(
            decision=decision
        ).count()

        return {
            "decision_ada": decision.ada,
            "linked_total": linked_total,
            "unlinked_total": unlinked_total,
            "total_amount": linked_total + unlinked_total,
            "entity_count": entity_count,
            "has_entities": entity_count > 0,
            "has_unlinked_amounts": unlinked_total > 0,
            "all_amounts_linked": unlinked_total == 0,
        }

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
            qs = qs.filter(decision__issue_date__gte=start_date)

        if end_date:
            qs = qs.filter(decision__issue_date__lte=end_date)

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
            qs = qs.filter(decision__issue_date__gte=start_date)

        if end_date:
            qs = qs.filter(decision__issue_date__lte=end_date)

        return qs.select_related(
            "decision", "decision__organization", "decision__decision_type", "entity"
        )

    def validate_amount_consistency(self, decision: Decision) -> Dict[str, Any]:
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

        return {
            "decision_ada": decision.ada,
            "total_from_amount_fields": total_from_amount_fields,
            "linked_amounts_total": linked_total,
            "unlinked_amounts_total": total_from_amount_fields - linked_total,
            "decision_amount_field": decision_amount,
            "kae_total": kae_total,
            "discrepancy": discrepancy,
            "discrepancy_percentage": discrepancy_percentage,
            "is_consistent": discrepancy is None
            or discrepancy <= Decimal("0.01"),  # 1 cent tolerance
        }

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
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        # Get decision count and basic stats
        decision_stats = decisions_queryset.aggregate(
            total_decisions=Count("id"), legacy_total=Sum("amount")  # For comparison
        )

        avg_amount = (
            total_amount_accurate / decision_stats["total_decisions"]
            if decision_stats["total_decisions"] > 0
            else Decimal("0.00")
        )

        return {
            "total_amount": total_amount_accurate,
            "total_decisions": decision_stats["total_decisions"],
            "avg_amount": avg_amount,
            "legacy_total_amount": decision_stats["legacy_total"] or Decimal("0.00"),
            "calculation_method": "relationship_based",
            "accuracy_improvement": abs(
                total_amount_accurate
                - (decision_stats["legacy_total"] or Decimal("0.00"))
            ),
        }


# Singleton instance for easy importing
financial_service = FinancialCalculationService()
