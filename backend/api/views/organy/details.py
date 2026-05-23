from datetime import datetime

from core.models.companies import Company
from core.models.entities import AFMEntity, DecisionEntityRelationship
from core.models.organizations import Organization
from dateutil.relativedelta import relativedelta
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
def organization_entity_transactions(request, organization_uid, afm=None):
    """
    Get detailed transaction history between an organization and an entity (company).

    Parameters:
    - organization_uid: The organization's UID
    - afm (optional): The entity's AFM. If not provided, returns transactions for all entities.

    Query parameters:
    - period: 'all', '1y', '6m', '3m' (default: '1y')
    - sort_by: 'date', 'amount' (default: 'date')
    - sort_order: 'asc', 'desc' (default: 'desc')
    - limit: number of results to return (default: 50, max: 200)
    - offset: pagination offset (default: 0)
    """
    try:
        # Get query parameters
        period = request.GET.get("period", "1y")
        sort_by = request.GET.get("sort_by", "date")
        sort_order = request.GET.get("sort_order", "desc")
        limit = min(int(request.GET.get("limit", 50)), 200)  # Cap at 200
        offset = int(request.GET.get("offset", 0))
        direct_assignments_only = request.GET.get(
            "direct_assignments_only", ""
        ).lower() in ["true", "1", "yes"]

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

        # Base query - filter by organization
        base_query = (
            DecisionEntityRelationship.objects.filter(
                decision__organization=organization,
                # Filter by roles that indicate money paid (customize as needed)
                role__in=["grantee", "donationReceiver", "sponsorAFMName"],
            )
            .select_related("decision", "entity")
            .prefetch_related("linked_amounts")
        )

        # Apply entity filter if AFM is provided
        if afm:
            entity = AFMEntity.objects.filter(afm=afm).first()
            if not entity:
                return Response(
                    {"error": f"No entity found with AFM: {afm}"}, status=404
                )
            base_query = base_query.filter(entity=entity)

        # Apply date filter if period is specified
        if start_date:
            base_query = base_query.filter(decision__issue_date__gte=start_date)

        # Apply direct assignments filter
        if direct_assignments_only:
            base_query = base_query.filter(
                decision__classification__is_direct_assignment=True
            )

        # Apply sorting
        if sort_by == "date":
            order_field = "decision__issue_date"
        elif sort_by == "amount":
            # This is a bit tricky since amounts are in a related model
            # We'll apply this manually after the query
            order_field = "decision__issue_date"  # Default fallback
        else:
            order_field = "decision__issue_date"

        # Apply sort direction
        if sort_order == "asc":
            order_by = order_field
        else:
            order_by = f"-{order_field}"

        # Execute query with pagination
        relationships = base_query.order_by(order_by)[offset : offset + limit]

        # Count total results for pagination info
        total_count = base_query.count()

        # Format detailed results
        transactions = []
        for rel in relationships:
            # Calculate total amount for this relationship
            total_amount = sum(
                float(amount.amount or 0) for amount in rel.linked_amounts.all()
            )

            # Get company info if available
            company = None
            if rel.entity.afm:
                # Filter out branches
                company = Company.objects.filter(
                    afm=rel.entity.afm, is_branch=False
                ).first()

                # If no non-branch found, try to get any company
                if not company:
                    company = Company.objects.filter(afm=rel.entity.afm).first()

            transactions.append(
                {
                    "decision": {
                        "id": rel.decision.id,
                        "ada": rel.decision.ada,
                        "subject": rel.decision.subject,
                        "issue_date": rel.decision.issue_date,
                        "url": rel.decision.url,
                        "status": rel.decision.status,
                    },
                    "entity": {
                        "afm": rel.entity.afm,
                        "name": rel.entity.name,
                        "entity_type": rel.entity.entity_type,
                        "company_info": (
                            {
                                "name": company.co_name_el if company else None,
                                "legal_type": (
                                    company.legal_type_name if company else None
                                ),
                                "status": company.status_name if company else None,
                                "is_branch": company.is_branch if company else None,
                            }
                            if company
                            else None
                        ),
                    },
                    "role": rel.role,
                    "amount": total_amount,
                    "context": {
                        "parent_key_path": rel.parent_key_path,
                        "source_field": rel.source_field_name,
                        "raw_context": rel.raw_context,
                    },
                }
            )

        # If sorting by amount was requested, do it manually
        if sort_by == "amount":
            transactions.sort(key=lambda x: x["amount"], reverse=(sort_order == "desc"))

        # Get entity info if AFM was provided
        entity_info = None
        if afm:
            entity = AFMEntity.objects.filter(afm=afm).first()
            if entity:
                # Get non-branch company info
                company = Company.objects.filter(afm=afm, is_branch=False).first()
                if not company:
                    company = Company.objects.filter(afm=afm).first()

                entity_info = {
                    "afm": entity.afm,
                    "name": entity.name,
                    "entity_type": entity.entity_type,
                    "total_appearances": entity.total_appearances,
                    "company_info": (
                        {
                            "name": company.co_name_el if company else None,
                            "legal_type": company.legal_type_name if company else None,
                            "status": company.status_name if company else None,
                            "is_branch": company.is_branch if company else None,
                        }
                        if company
                        else None
                    ),
                }

        # Calculate financial summary
        total_amount = sum(transaction["amount"] for transaction in transactions)

        return Response(
            {
                "organization": {
                    "uid": organization.uid,
                    "name": organization.label,
                },
                "entity": entity_info,
                "period": period,
                "pagination": {
                    "total": total_count,
                    "limit": limit,
                    "offset": offset,
                    "has_more": (offset + limit) < total_count,
                },
                "total_amount": total_amount,
                "transaction_count": len(transactions),
                "transactions": transactions,
            }
        )

    except Exception as e:
        return Response({"error": str(e)}, status=500)
