from datetime import datetime

from core.models.companies import Company, CompanyPerson
from core.models.entities import AFMEntity, DecisionEntityRelationship
from core.services.feature_flag_service import feature_flags
from core.services.financial_calculation_service import financial_service
from core.utils.performance_monitoring import monitor_query_performance
from django.conf import settings
from django.db.models import Count, Max, Min
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
def company_detail(request, company_id):
    """Get detailed company information."""
    # Check if company enrichment is enabled
    if not feature_flags.is_enabled("HAVE_AFM_FETCH_JOB"):
        return Response(
            {
                "error": "Company data enrichment is currently disabled",
                "feature_disabled": True,
                "message": "Company details are not available. Only AFM entity information is maintained.",
            },
            status=503,
        )

    try:
        company = Company.objects.prefetch_related(
            "activities", "persons", "capital", "stocks"
        ).get(id=company_id)

        company_data = {
            "id": company.id,
            "ar_gemi": company.ar_gemi,
            "afm": company.afm,
            "co_name_el": company.co_name_el,
            "co_names_en": company.co_names_en,
            "co_titles_el": company.co_titles_el,
            "co_titles_en": company.co_titles_en,
            "legal_type_name": company.legal_type_name,
            "status_name": company.status_name,
            "municipality_name": company.municipality_name,
            "prefecture_name": company.prefecture_name,
            "city": company.city,
            "street": company.street,
            "street_number": company.street_number,
            "zip_code": company.zip_code,
            "url": company.url,
            "email": company.email,
            "is_branch": company.is_branch,
            "objective": company.objective,
            "incorporation_date": company.incorporation_date,
            "last_updated": company.last_updated,
            # Related data
            "activities": [
                {
                    "activity_id": activity.activity_id,
                    "activity_name": activity.activity_name,
                    "activity_type": activity.activity_type,
                    "date_from": activity.date_from,
                    "date_to": activity.date_to,
                }
                for activity in company.activities.all()
            ],
            "persons": [
                {
                    "person_name": person.person_name,
                    "business_name": person.business_name,
                    "role": person.role,
                    "date_from": person.date_from,
                    "date_to": person.date_to,
                    "is_representative_alone": person.is_representative_alone,
                    "is_representative_in_common": person.is_representative_in_common,
                }
                for person in company.persons.all()
            ],
            "capital": [
                {
                    "capital_stock": (
                        float(capital.capital_stock) if capital.capital_stock else None
                    ),
                    "currency": capital.currency,
                    "ecsokefalaiikes": (
                        float(capital.ecsokefalaiikes)
                        if capital.ecsokefalaiikes
                        else None
                    ),
                    "eggiitikes": (
                        float(capital.eggiitikes) if capital.eggiitikes else None
                    ),
                }
                for capital in company.capital.all()
            ],
        }

        return Response(company_data)

    except Company.DoesNotExist:
        return Response({"error": "Company not found"}, status=404)
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
def company_by_afm(request, afm):
    """Get the main (non-branch) company for a given AFM, with all related data."""

    try:
        company = (
            Company.objects.prefetch_related("activities", "persons", "capital", "stocks")
            .filter(afm=afm, is_branch=False)
            .first()
        )
        if company is None:
            return Response({"error": "Company not found"}, status=404)

        data = {
            "id": company.id,
            "ar_gemi": company.ar_gemi,
            "afm": company.afm,
            "co_name_el": company.co_name_el,
            "co_names_en": company.co_names_en,
            "co_titles_el": company.co_titles_el,
            "co_titles_en": company.co_titles_en,
            "legal_type_name": company.legal_type_name,
            "status_name": company.status_name,
            "municipality_name": company.municipality_name,
            "prefecture_name": company.prefecture_name,
            "city": company.city,
            "street": company.street,
            "street_number": company.street_number,
            "zip_code": company.zip_code,
            "po_box": company.po_box,
            "url": company.url,
            "email": company.email,
            "is_branch": company.is_branch,
            "objective": company.objective,
            "gemi_office_name": company.gemi_office_name,
            "incorporation_date": company.incorporation_date,
            "last_status_change": company.last_status_change,
            "auto_registered": company.auto_registered,
            "branch_gemi_numbers": company.branch_gemi_numbers,
            "last_updated": company.last_updated,
            "activities": [
                {
                    "activity_id": a.activity_id,
                    "activity_name": a.activity_name,
                    "activity_type": a.activity_type,
                    "date_from": a.date_from,
                    "date_to": a.date_to,
                }
                for a in company.activities.all()
            ],
            "persons": [
                {
                    "person_name": p.person_name,
                    "business_name": p.business_name,
                    "role": p.role,
                    "date_from": p.date_from,
                    "date_to": p.date_to,
                    "is_representative_alone": p.is_representative_alone,
                    "is_representative_in_common": p.is_representative_in_common,
                }
                for p in company.persons.all()
            ],
            "capital": [
                {
                    "capital_stock": float(c.capital_stock) if c.capital_stock else None,
                    "currency": c.currency,
                    "ecsokefalaiikes": float(c.ecsokefalaiikes) if c.ecsokefalaiikes else None,
                    "eggiitikes": float(c.eggiitikes) if c.eggiitikes else None,
                }
                for c in company.capital.all()
            ],
            "stocks": [
                {
                    "stock_type": s.stock_type,
                    "amount": float(s.amount) if s.amount else None,
                    "nominal_price": float(s.nominal_price) if s.nominal_price else None,
                }
                for s in company.stocks.all()
            ],
        }
        return Response(data)

    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
def person_companies(request, person_name):
    """Get all companies where a person (by name) is involved."""
    try:
        involvements = (
            CompanyPerson.objects
            .filter(person_name=person_name)
            .select_related("company")
            .order_by("company__co_name_el")
        )

        if not involvements.exists():
            return Response({"error": "Person not found"}, status=404)

        results = []
        for inv in involvements:
            c = inv.company
            results.append({
                "company": {
                    "id": c.id,
                    "ar_gemi": c.ar_gemi,
                    "afm": c.afm,
                    "co_name_el": c.co_name_el,
                    "co_names_en": c.co_names_en,
                    "legal_type_name": c.legal_type_name,
                    "status_name": c.status_name,
                    "city": c.city,
                    "is_branch": c.is_branch,
                },
                "role": inv.role,
                "date_from": inv.date_from,
                "date_to": inv.date_to,
                "is_representative_alone": inv.is_representative_alone,
                "is_representative_in_common": inv.is_representative_in_common,
                "business_name": inv.business_name,
            })

        return Response({"person_name": person_name, "involvements": results})

    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
@monitor_query_performance(include_context=True)
def company_decisions(request, company_id):
    """Get all decisions related to a specific company."""
    # Check if company enrichment is enabled
    if not feature_flags.is_enabled("HAVE_AFM_FETCH_JOB"):
        return Response(
            {
                "error": "Company data enrichment is currently disabled",
                "feature_disabled": True,
                "message": "Company details are not available. Only AFM entity information is maintained.",
            },
            status=503,
        )

    try:
        company = Company.objects.get(id=company_id)

        # Find the AFM entity for this company
        try:
            afm_entity = AFMEntity.objects.get(afm=company.afm)
        except AFMEntity.DoesNotExist:
            return Response(
                {
                    "company_id": company_id,
                    "company_name": company.co_name_el,
                    "afm": company.afm,
                    "decisions": [],
                    "total_decisions": 0,
                    "message": "No AFM entity found for this company",
                }
            )

        # Get all decision relationships for this AFM entity with optimized queries
        direct_assignments_only = request.GET.get(
            "direct_assignments_only", ""
        ).lower() in ["true", "1", "yes"]

        relationships = (
            DecisionEntityRelationship.objects.filter(entity=afm_entity)
            .select_related(
                "decision", "decision__organization", "decision__decision_type"
            )
            .prefetch_related("linked_amounts")
        )

        # Apply direct assignments filter
        if direct_assignments_only:
            relationships = relationships.filter(
                decision__classification__is_direct_assignment=True
            )

        decisions_data = []
        for rel in relationships:
            decision = rel.decision

            # Calculate total amount from linked amounts (new approach)
            total_linked_amount = sum(
                amount.amount
                for amount in rel.linked_amounts.all()
                if amount.amount is not None
            )

            decision_data = {
                "id": decision.id,
                "ada": decision.ada,
                "subject": decision.subject,
                "amount": (
                    float(total_linked_amount) if total_linked_amount > 0 else None
                ),
                "legacy_amount": (
                    float(decision.amount) if decision.amount else None
                ),  # Keep for comparison
                "currency": decision.currency,
                "financial_year": decision.financial_year,
                "issue_date": decision.issue_date_day,
                "publish_timestamp": decision.publish_timestamp,
                "status": decision.status,
                "url": decision.url,
                "entity_role": rel.role,  # Role of the company in this decision
                "amount_count": rel.linked_amounts.count(),  # Number of amount fields linked
                "organization": (
                    {
                        "uid": decision.organization.uid,
                        "label": decision.organization.label,
                        "latin_name": decision.organization.latin_name,
                        "category": decision.organization.category,
                    }
                    if decision.organization
                    else None
                ),
                "decision_type": (
                    {
                        "uid": decision.decision_type.uid,
                        "label": decision.decision_type.label,
                    }
                    if decision.decision_type
                    else None
                ),
                # Company's role in this decision
                "company_role": rel.role,
                "parent_key_path": rel.parent_key_path,
                "confidence_score": rel.confidence_score,
            }

            decisions_data.append(decision_data)

        # Sort by issue date descending
        decisions_data.sort(key=lambda x: x["issue_date"] or "", reverse=True)

        return Response(
            {
                "company_id": company_id,
                "company_name": company.co_name_el,
                "company_ar_gemi": company.ar_gemi,
                "afm": company.afm,
                "decisions": decisions_data,
                "total_decisions": len(decisions_data),
                "roles_summary": _get_roles_summary(relationships),
            }
        )

    except Company.DoesNotExist:
        return Response({"error": "Company not found"}, status=404)
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
@monitor_query_performance(include_context=True)
def company_decision_stats(request, company_id):
    """Get comprehensive decision statistics for a company using the financial service."""
    # Check if company enrichment is enabled
    if not feature_flags.is_enabled("HAVE_AFM_FETCH_JOB"):
        return Response(
            {
                "error": "Company data enrichment is currently disabled",
                "feature_disabled": True,
                "message": "Company statistics are not available. Only AFM entity information is maintained.",
            },
            status=503,
        )

    try:
        company = Company.objects.get(id=company_id)

        # Find the AFM entity for this company
        try:
            afm_entity = AFMEntity.objects.get(afm=company.afm)
        except AFMEntity.DoesNotExist:
            return Response(
                {
                    "company_id": company_id,
                    "error": "No AFM entity found for this company",
                },
                status=404,
            )

        # Use financial service for comprehensive statistics
        financial_summary = financial_service.get_entity_financial_summary(afm_entity)

        # Get additional company-specific data
        relationships = DecisionEntityRelationship.objects.filter(
            entity=afm_entity
        ).select_related("decision")

        # Calculate date range
        date_stats = relationships.filter(decision__issue_date_day__isnull=False).aggregate(
            first_date=Min("decision__issue_date_day"),
            last_date=Max("decision__issue_date_day"),
        )

        # Get decision type breakdown
        type_stats = (
            relationships.filter(decision__decision_type__isnull=False)
            .values("decision__decision_type__uid", "decision__decision_type__label")
            .annotate(count=Count("decision__decision_type", distinct=True))
            .order_by("-count")[:10]
        )

        return Response(
            {
                "company_id": company_id,
                "company_name": company.co_name_el,
                "company_ar_gemi": company.ar_gemi,
                "afm": company.afm,
                "financial_summary": {
                    "total_received": float(financial_summary["total_received"]),
                    "decision_count": financial_summary["decision_count"],
                    "avg_amount": float(financial_summary["avg_amount"]),
                    "unique_organizations": financial_summary["unique_organizations"],
                    "top_organizations": financial_summary["top_organizations"],
                    "role_breakdown": financial_summary["role_breakdown"],
                },
                "activity_period": {
                    "first_decision": date_stats["first_date"],
                    "last_decision": date_stats["last_date"],
                    "days_active": (
                        (date_stats["last_date"] - date_stats["first_date"]).days
                        if date_stats["first_date"] and date_stats["last_date"]
                        else 0
                    ),
                },
                "decision_types": list(type_stats),
                "entity_info": financial_summary["entity_info"],
            }
        )

    except Company.DoesNotExist:
        return Response({"error": "Company not found"}, status=404)
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
@monitor_query_performance(include_context=True)
def company_financial_timeline(request, company_id):
    """Get financial timeline for a company using the financial service."""
    # Check if company enrichment is enabled
    if not feature_flags.is_enabled("HAVE_AFM_FETCH_JOB"):
        return Response(
            {
                "error": "Company data enrichment is currently disabled",
                "feature_disabled": True,
                "message": "Company financial timeline is not available. Only AFM entity information is maintained.",
            },
            status=503,
        )

    try:
        company = Company.objects.get(id=company_id)

        # Find the AFM entity for this company
        try:
            afm_entity = AFMEntity.objects.get(afm=company.afm)
        except AFMEntity.DoesNotExist:
            return Response(
                {
                    "company_id": company_id,
                    "error": "No AFM entity found for this company",
                },
                status=404,
            )

        # Get query parameters
        granularity = request.GET.get("granularity", "month")  # day, month, year
        start_date_str = request.GET.get("start_date")
        end_date_str = request.GET.get("end_date")

        # Parse dates
        start_date = None
        end_date = None
        if start_date_str:
            try:
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
            except ValueError:
                return Response(
                    {"error": "Invalid start_date format. Use YYYY-MM-DD"}, status=400
                )

        if end_date_str:
            try:
                end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
            except ValueError:
                return Response(
                    {"error": "Invalid end_date format. Use YYYY-MM-DD"}, status=400
                )

        # Use financial service for timeline data
        timeline_data = financial_service.get_entity_timeline_data(
            afm_entity,
            start_date=start_date,
            end_date=end_date,
            granularity=granularity,
        )

        return Response(
            {
                "company_id": company_id,
                "company_name": company.co_name_el,
                "afm": company.afm,
                "granularity": granularity,
                "timeline": timeline_data,
                "summary": {
                    "total_periods": len(timeline_data),
                    "total_amount": sum(
                        period["total_amount"] for period in timeline_data
                    ),
                    "total_decisions": sum(
                        period["decision_count"] for period in timeline_data
                    ),
                },
            }
        )

    except Company.DoesNotExist:
        return Response({"error": "Company not found"}, status=404)
    except Exception as e:
        return Response({"error": str(e)}, status=500)

    except Company.DoesNotExist:
        return Response({"error": "Company not found"}, status=404)
    except Exception as e:
        return Response({"error": str(e)}, status=500)


def _get_roles_summary(relationships):
    """Helper function to summarize roles."""
    roles = {}
    for rel in relationships:
        role = rel.role
        if role in roles:
            roles[role] += 1
        else:
            roles[role] = 1
    return roles
