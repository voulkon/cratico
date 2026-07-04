from datetime import datetime

from core.models.companies import Company
from core.models.entities import AFMEntity, DecisionEntityRelationship
from core.models.organizations import Organization
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db.models import Count, F, Sum
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
def company_transactions_summary(request, afm):
    """
    Get summary of all transactions (money received) for a company identified by AFM.

    Query parameters:
    - period: 'all', '1y', '6m', '3m' (default: '1y')
    - group_by: 'month', 'year', 'organization' (default: 'organization')
    """
    try:
        # Get query parameters
        period = request.GET.get("period", "1y")
        group_by = request.GET.get("group_by", "organization")

        # Calculate date filters based on period
        end_date = datetime.now()
        start_date = None

        if period == "1y":
            start_date = end_date - relativedelta(years=1)
        elif period == "6m":
            start_date = end_date - relativedelta(months=6)
        elif period == "3m":
            start_date = end_date - relativedelta(months=3)
        # For 'all', start_date remains None

        # Find the entity with this AFM
        entity = AFMEntity.objects.filter(afm=afm).first()
        if not entity:
            return Response({"error": f"No entity found with AFM: {afm}"}, status=404)

        # Base query - get all amounts linked to this entity
        base_query = DecisionEntityRelationship.objects.filter(
            entity=entity,
            # Filter by roles that indicate money received (customize as needed)
            role__in=["grantee", "donationReceiver", "sponsorAFMName"],
        ).select_related("decision", "decision__organization")

        if start_date:
            base_query = base_query.filter(decision__issue_date_day__gte=start_date)

        # Prepare results based on group_by parameter
        if group_by == "organization":
            # Group transactions by organization
            result = (
                base_query.values(
                    "decision__organization__uid", "decision__organization__label"
                )
                .annotate(
                    total_amount=Sum("linked_amounts__amount"),
                    decision_count=Count("decision", distinct=True),
                )
                .order_by("-total_amount")
            )

            # Format the response
            formatted_result = [
                {
                    "organization_uid": item["decision__organization__uid"],
                    "organization_name": item["decision__organization__label"],
                    "total_amount": float(item["total_amount"] or 0),
                    "decision_count": item["decision_count"],
                }
                for item in result
            ]

        elif group_by in ["month", "year"]:
            # Use precomputed indexed fields instead of Trunc for direct index scans
            period_column = (
                "decision__issue_date_month"
                if group_by == "month"
                else "decision__issue_date_year"
            )

            result = (
                base_query.annotate(period=F(period_column))
                .values("period")
                .annotate(
                    total_amount=Sum("linked_amounts__amount"),
                    decision_count=Count("decision", distinct=True),
                )
                .order_by("period")
            )

            # Format the response
            formatted_result = [
                {
                    "period": (
                        str(item["period"])
                        if group_by == "year"
                        else item["period"].strftime("%Y-%m")
                    ),
                    "total_amount": float(item["total_amount"] or 0),
                    "decision_count": item["decision_count"],
                }
                for item in result
            ]
        else:
            return Response(
                {"error": f"Invalid group_by parameter: {group_by}"}, status=400
            )

        # Get company info
        company = Company.objects.filter(afm=afm, is_branch=False).first()
        if not company:
            company = Company.objects.filter(afm=afm).first()
        company_name = company.co_name_el if company else entity.name

        return Response(
            {
                "afm": afm,
                "company_name": company_name,
                "period": period,
                "group_by": group_by,
                "total_received": sum(
                    item["total_amount"] for item in formatted_result
                ),
                "total_decisions": sum(
                    item["decision_count"] for item in formatted_result
                ),
                "results": formatted_result,
            }
        )

    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
def organization_expenditures_summary(request, organization_uid):
    """
    Get summary of all expenditures from an organization to various companies.

    Query parameters:
    - period: 'all', '1y', '6m', '3m' (default: '1y')
    - group_by: 'month', 'year', 'company' (default: 'company')
    - min_amount: minimum transaction amount to include (default: 0)
    """
    try:
        # Get query parameters
        period = request.GET.get("period", "1y")
        group_by = request.GET.get("group_by", "company")
        min_amount = float(request.GET.get("min_amount", 0))

        # Calculate date filters based on period
        end_date = datetime.now()
        start_date = None

        if period == "1y":
            start_date = end_date - relativedelta(years=1)
        elif period == "6m":
            start_date = end_date - relativedelta(months=6)
        elif period == "3m":
            start_date = end_date - relativedelta(months=3)

        # Find the organization
        organization = Organization.objects.filter(uid=organization_uid).first()
        if not organization:
            return Response(
                {"error": f"No organization found with UID: {organization_uid}"},
                status=404,
            )

        # Base query - get all decisions from this organization
        base_query = DecisionEntityRelationship.objects.filter(
            decision__organization=organization,
            # Filter by roles that indicate money paid (customize as needed)
            role__in=["grantee", "donationReceiver", "sponsorAFMName"],
        ).select_related("decision", "entity")

        if start_date:
            base_query = base_query.filter(decision__issue_date_day__gte=start_date)

        # Filter by minimum amount
        if min_amount > 0:
            base_query = base_query.filter(linked_amounts__amount__gte=min_amount)

        # Prepare results based on group_by parameter
        if group_by == "company":
            # Group transactions by company (entity)
            result = (
                base_query.values("entity__afm", "entity__name")
                .annotate(
                    total_amount=Sum("linked_amounts__amount"),
                    decision_count=Count("decision", distinct=True),
                )
                .order_by("-total_amount")
            )

            # Format the response with company info
            formatted_result = []
            for item in result:
                afm = item["entity__afm"]
                # Try to get company info
                company = Company.objects.filter(afm=afm).first()

                formatted_result.append(
                    {
                        "afm": afm,
                        "name": item["entity__name"],
                        "company_name": company.co_name_el if company else None,
                        "legal_type": company.legal_type_name if company else None,
                        "total_amount": float(item["total_amount"] or 0),
                        "decision_count": item["decision_count"],
                    }
                )

        elif group_by in ["month", "year"]:
            # Use precomputed indexed fields instead of Trunc for direct index scans
            period_column = (
                "decision__issue_date_month"
                if group_by == "month"
                else "decision__issue_date_year"
            )

            result = (
                base_query.annotate(period=F(period_column))
                .values("period")
                .annotate(
                    total_amount=Sum("linked_amounts__amount"),
                    decision_count=Count("decision", distinct=True),
                )
                .order_by("period")
            )

            # Format the response
            formatted_result = [
                {
                    "period": (
                        str(item["period"])
                        if group_by == "year"
                        else item["period"].strftime("%Y-%m")
                    ),
                    "total_amount": float(item["total_amount"] or 0),
                    "decision_count": item["decision_count"],
                }
                for item in result
            ]
        else:
            return Response(
                {"error": f"Invalid group_by parameter: {group_by}"}, status=400
            )

        return Response(
            {
                "organization_uid": organization_uid,
                "organization_name": organization.label,
                "period": period,
                "group_by": group_by,
                "min_amount": min_amount,
                "total_spent": sum(item["total_amount"] for item in formatted_result),
                "total_decisions": sum(
                    item["decision_count"] for item in formatted_result
                ),
                "results": formatted_result,
            }
        )

    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
def top_transactions(request):
    """
    Get top transactions (highest amounts) between organizations and companies.

    Query parameters:
    - period: 'all', '1y', '6m', '3m' (default: '1y')
    - limit: number of results to return (default: 20, max: 100)
    """
    try:
        # Get query parameters
        period = request.GET.get("period", "1y")
        limit = min(int(request.GET.get("limit", 20)), 100)  # Cap at 100

        # Calculate date filters based on period
        end_date = datetime.now()
        start_date = None

        if period == "1y":
            start_date = end_date - relativedelta(years=1)
        elif period == "6m":
            start_date = end_date - relativedelta(months=6)
        elif period == "3m":
            start_date = end_date - relativedelta(months=3)

        # Base query - get all entity relationships with amounts
        base_query = DecisionEntityRelationship.objects.filter(
            # Filter by roles that indicate money paid/received
            role__in=["grantee", "donationReceiver", "sponsorAFMName"]
        ).select_related("decision", "decision__organization", "entity")

        if start_date:
            base_query = base_query.filter(decision__issue_date_day__gte=start_date)

        # Aggregate and get top transactions
        top_transactions = (
            base_query.values(
                "decision__id",
                "decision__ada",
                "decision__subject",
                "decision__issue_date_day",
                "decision__organization__uid",
                "decision__organization__label",
                "entity__afm",
                "entity__name",
                "role",
            )
            .annotate(total_amount=Sum("linked_amounts__amount"))
            .order_by("-total_amount")[:limit]
        )

        # Format the response
        results = []
        for transaction in top_transactions:
            # Get company info
            afm = transaction["entity__afm"]
            company = Company.objects.filter(afm=afm, is_branch=False).first()
            if not company:
                company = Company.objects.filter(afm=afm).first()
            results.append(
                {
                    "decision_id": transaction["decision__id"],
                    "decision_ada": transaction["decision__ada"],
                    "subject": transaction["decision__subject"],
                    "issue_date": transaction["decision__issue_date_day"],
                    "organization": {
                        "uid": transaction["decision__organization__uid"],
                        "name": transaction["decision__organization__label"],
                    },
                    "entity": {
                        "afm": afm,
                        "name": transaction["entity__name"],
                        "company_name": company.co_name_el if company else None,
                    },
                    "role": transaction["role"],
                    "amount": float(transaction["total_amount"] or 0),
                }
            )

        return Response({"period": period, "results": results})

    except Exception as e:
        return Response({"error": str(e)}, status=500)
