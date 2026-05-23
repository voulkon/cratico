"""
Centralized sorting utilities for decision queries.

This module provides reusable functions to apply consistent sorting logic
across different views, particularly for handling NULL amounts properly.
"""

from django.db import models


def apply_decision_sorting(
    queryset, sort_by, amount_field="amount", date_field="issue_date"
):
    """
    Apply sorting to a queryset of decisions with proper NULL handling.

    When sorting by amount, NULL/zero values are placed LAST (not first),
    which is more intuitive for users.

    Args:
        queryset: Django QuerySet to sort
        sort_by: Sort parameter ('recent', 'oldest', 'amount_desc', 'amount_asc')
        amount_field: Field name for amount (default: 'amount')
        date_field: Field name for date (default: 'issue_date')

    Returns:
        Sorted QuerySet

    Example:
        queryset = apply_decision_sorting(decisions, 'amount_desc')
    """
    if sort_by == "recent":
        return queryset.order_by(f"-{date_field}")

    elif sort_by == "oldest":
        return queryset.order_by(date_field)

    elif sort_by == "amount_desc":
        # Sort by amount descending, NULL values last
        return queryset.annotate(
            sort_amount=models.Case(
                models.When(
                    **{f"{amount_field}__isnull": False}, then=models.F(amount_field)
                ),
                default=models.Value(-999999999),
                output_field=models.DecimalField(),
            )
        ).order_by("-sort_amount", f"-{date_field}")

    elif sort_by == "amount_asc":
        # Sort by amount ascending, NULL values last
        return queryset.annotate(
            sort_amount=models.Case(
                models.When(
                    **{f"{amount_field}__isnull": False}, then=models.F(amount_field)
                ),
                default=models.Value(999999999),
                output_field=models.DecimalField(),
            )
        ).order_by("sort_amount", f"-{date_field}")

    else:
        # Default to recent
        return queryset.order_by(f"-{date_field}")


def apply_aggregated_amount_sorting(
    queryset, sort_by, aggregation_annotation="total_amount", date_field="issue_date"
):
    """
    Apply sorting when using aggregated amounts (Sum, Avg, etc.).

    This is useful for queries that use annotations like Sum('linked_amounts__amount').
    NULL aggregated values are placed LAST when sorting by amount.

    Args:
        queryset: Django QuerySet (should already have the aggregation annotation)
        sort_by: Sort parameter ('recent', 'oldest', 'amount_desc', 'amount_asc')
        aggregation_annotation: Name of the annotated field to sort by
        date_field: Field name for date (default: 'issue_date')

    Returns:
        Sorted QuerySet

    Example:
        queryset = queryset.annotate(total_amount=Sum('linked_amounts__amount'))
        queryset = apply_aggregated_amount_sorting(queryset, 'amount_desc', 'total_amount')
    """
    if sort_by == "recent":
        return queryset.order_by(f"-{date_field}")

    elif sort_by == "oldest":
        return queryset.order_by(date_field)

    elif sort_by == "amount_desc":
        # Sort by aggregated amount descending, NULL values last
        return queryset.annotate(
            sort_amount=models.Case(
                models.When(
                    **{f"{aggregation_annotation}__isnull": False},
                    then=models.F(aggregation_annotation),
                ),
                default=models.Value(-999999999),
                output_field=models.DecimalField(),
            )
        ).order_by("-sort_amount", f"-{date_field}")

    elif sort_by == "amount_asc":
        # Sort by aggregated amount ascending, NULL values last
        return queryset.annotate(
            sort_amount=models.Case(
                models.When(
                    **{f"{aggregation_annotation}__isnull": False},
                    then=models.F(aggregation_annotation),
                ),
                default=models.Value(999999999),
                output_field=models.DecimalField(),
            )
        ).order_by("sort_amount", f"-{date_field}")

    else:
        # Default to recent
        return queryset.order_by(f"-{date_field}")
