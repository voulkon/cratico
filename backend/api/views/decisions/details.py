from core.models.companies import Company
from core.models.decision_ai_analysis import DecisionAIAnalysis
from core.models.decisions import Decision
from core.models.document_analysis import DocumentExtraction, ProcessingStatus
from core.models.entities import DecisionEntityRelationship
from core.schemas.decision_detail import DecisionDetailResponse
from api.utils.response import pydantic_response
from django.conf import settings
from django.db.models import Count, F, Q, Sum
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
def decision_detail(request, decision_id):
    """Get detailed decision information with all relationships."""
    try:
        decision = (
            Decision.objects.select_related("organization", "decision_type")
            .prefetch_related("signers", "units", "kae_amounts", "attachments")
            .get(id=decision_id)
        )  # Using integer ID

        # Document content availability (so the frontend can decide whether to
        # show the "view extracted content" action or a "request extraction" CTA).
        has_document_content = False
        try:
            extraction = DocumentExtraction.objects.get(decision=decision)
            has_document_content = (
                extraction.extraction_status == ProcessingStatus.COMPLETED
                and bool(extraction.raw_text)
            )
        except DocumentExtraction.DoesNotExist:
            has_document_content = False

        # AI analyses — all completed, newest first
        ai_analyses_data = []
        try:
            ai_analyses = (
                DecisionAIAnalysis.objects
                .filter(decision=decision, status="COMPLETED")
                .exclude(summary="")
                .order_by("-created_at")
            )
            for ai in ai_analyses:
                ai_analyses_data.append({
                    "id": ai.id,
                    "status": ai.status,
                    "summary": ai.summary,
                    "cost_usd": str(ai.cost_usd) if ai.cost_usd else None,
                    "model_used": ai.model_used,
                    "completed_at": ai.completed_at,
                    "error_message": ai.error_message,
                })
        except DecisionAIAnalysis.DoesNotExist:
            ai_analyses_data = []

        # Serialize decision data
        decision_data = {
            "id": decision.id,
            "ada": decision.ada,
            # TODO: Do I need these?
            "version_id": decision.version_id,
            "corrected_version_id": decision.corrected_version_id,
            "protocol_number": decision.protocol_number,
            "subject": decision.subject,
            # TODO: Do I need these?
            "amount": float(decision.amount) if decision.amount else None,
            "currency": decision.currency,
            "financial_year": decision.financial_year,
            "issue_date": decision.issue_date_day,
            "publish_timestamp": decision.publish_timestamp,
            "submission_timestamp": decision.submission_timestamp,
            "status": decision.status,
            "document_url": decision.document_url,
            "document_checksum": decision.document_checksum,
            "url": decision.url,
            # User-friendly Diavgeia page (matches DecisionCard) instead of the
            # raw luminapi JSON endpoint.
            "diavgeia_page_url": (
                f"https://diavgeia.gov.gr/decision/view/{decision.ada}"
                if decision.ada
                else None
            ),
            "diavgeia_doc_url": (
                f"https://diavgeia.gov.gr/doc/{decision.ada}?inline=true"
                if decision.ada
                else None
            ),
            "has_document_content": has_document_content,
            "ai_analyses": ai_analyses_data,
            "warnings": decision.warnings,
            "has_private_data": decision.has_private_data,
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
            "signers": [
                {
                    "uid": signer.uid,
                    "first_name": signer.first_name,
                    "last_name": signer.last_name,
                    "active": signer.active,
                    "has_organization_sign_rights": signer.has_organization_sign_rights,
                }
                for signer in decision.signers.all()
            ],
            "units": [
                {
                    "uid": unit.uid,
                    "label": unit.label,
                    "active": unit.active,
                    "category": unit.category,
                }
                for unit in decision.units.all()
            ],
            "kae_amounts": [
                {"kae": kae.kae, "amount": float(kae.amount)}
                for kae in decision.kae_amounts.all()
            ],
            "attachments": [
                {
                    "attachment_id": att.attachment_id,
                    "filename": att.filename,
                    "mime_type": att.mime_type,
                    "description": att.description,
                    "checksum": att.checksum,
                }
                for att in decision.attachments.all()
            ],
            # Thematic categories
            "thematic_category_ids": decision.thematic_category_ids,
        }

        return pydantic_response(DecisionDetailResponse(**decision_data))

    except Decision.DoesNotExist:
        return Response({"error": "Decision not found"}, status=404)
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
def decision_entities(request, decision_id):
    """
    Return entity relationships for a decision with the **total amount per entity**
    calculated in SQL via the new FK `associated_relationship`.
    """
    try:
        # Ensure the decision exists
        decision = Decision.objects.only("id", "ada").get(id=decision_id)
    except Decision.DoesNotExist:
        return Response({"error": "Decision not found"}, status=404)

    # ------------------------------------------------------------------
    # 1. Aggregate amounts per (role, entity) in one SQL query
    # ------------------------------------------------------------------
    totals_qs = (
        DecisionEntityRelationship.objects.filter(decision_id=decision_id)
        .values("role", "entity")  # GROUP BY role, entity
        .annotate(
            total_amount=Sum("linked_amounts__amount"),
            occurrences=Count("id"),
            currency=F("linked_amounts__currency"),  # pick first currency
        )
    )

    # Build a quick lookup: (role, entity_id) → {total_amount, occurrences, currency}
    totals_map = {
        (row["role"], row["entity"]): {
            "total_amount": float(row["total_amount"] or 0),
            "occurrences": row["occurrences"],
            "currency": row["currency"] or "EUR",
        }
        for row in totals_qs
    }

    # ------------------------------------------------------------------
    # 2. Fetch relationships + entity + companies in a second query
    # ------------------------------------------------------------------
    relationships = (
        DecisionEntityRelationship.objects.filter(decision_id=decision_id)
        .select_related("entity")
        .order_by("role", "entity__afm")
    )

    grouped = {}
    for rel in relationships:
        key = (rel.role, rel.entity_id)
        if key not in grouped:
            grouped[key] = {
                "role": rel.role,
                "entity": {
                    "afm": rel.entity.afm,
                    "name": rel.entity.name,
                    "entity_type": rel.entity.entity_type,
                    "total_appearances": rel.entity.total_appearances,
                    "first_seen": rel.entity.first_seen,
                    "last_seen": rel.entity.last_seen,
                    "gemi_lookup_success": rel.entity.gemi_lookup_success,
                    "gemi_companies_count": rel.entity.gemi_companies_count,
                },
                "companies": list(
                    Company.objects.filter(afm=rel.entity.afm).values(
                        "ar_gemi",
                        "afm",
                        "co_name_el",
                        "co_names_en",
                        "legal_type_name",
                        "status_name",
                        "municipality_name",
                        "prefecture_name",
                        "city",
                        "street",
                        "street_number",
                        "zip_code",
                        "url",
                        "email",
                        "is_branch",
                        "incorporation_date",
                        "last_updated",
                    )
                ),
                "parent_key_paths": [],
                **totals_map.get(
                    key, {"total_amount": 0.0, "occurrences": 0, "currency": "EUR"}
                ),
            }
        grouped[key]["parent_key_paths"].append(rel.parent_key_path)

    return Response(
        {
            "decision_id": decision_id,
            "decision_ada": decision.ada,
            "relationships": list(grouped.values()),
            "total_entities": len(grouped),
        }
    )


@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
def decision_companies(request, decision_id):
    """Get all companies associated with a decision."""
    try:
        decision = Decision.objects.get(id=decision_id)

        # Get all AFMs from this decision's entities
        entity_afms = DecisionEntityRelationship.objects.filter(
            decision_id=decision_id
        ).values_list("entity__afm", flat=True)

        # Get all companies with these AFMs
        companies = (
            Company.objects.filter(afm__in=entity_afms)
            .prefetch_related("activities", "persons", "capital", "stocks")
            .all()
        )

        companies_data = []
        for company in companies:
            # Get the relationship info for this company's AFM
            relationships = (
                DecisionEntityRelationship.objects.filter(
                    decision_id=decision_id, entity__afm=company.afm
                )
                .select_related("entity")
                .all()
            )

            company_data = {
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
                            float(capital.capital_stock)
                            if capital.capital_stock
                            else None
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
                # Roles in this decision
                "decision_roles": [rel.role for rel in relationships],
            }

            companies_data.append(company_data)

        return Response(
            {
                "decision_id": decision_id,
                "decision_ada": decision.ada,
                "companies": companies_data,
                "total_companies": len(companies_data),
            }
        )

    except Decision.DoesNotExist:
        return Response({"error": "Decision not found"}, status=404)
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
def decision_related(request, decision_id):
    """Get related decisions based on organization, amount, type, etc."""
    try:
        decision = Decision.objects.select_related("organization", "decision_type").get(
            id=decision_id
        )

        # Build related decisions query
        related_query = Q()

        # Same organization
        if decision.organization:
            related_query |= Q(organization=decision.organization)

        # Similar decision type
        if decision.decision_type:
            related_query |= Q(decision_type=decision.decision_type)

        # Similar amount range (±50%)
        if decision.amount:
            min_amount = float(decision.amount) * 0.5
            max_amount = float(decision.amount) * 1.5
            related_query |= Q(amount__gte=min_amount, amount__lte=max_amount)

        # Exclude the current decision
        related_decisions = (
            Decision.objects.filter(related_query)
            .exclude(id=decision_id)
            .select_related("organization", "decision_type")
            .order_by("-issue_date_day")[:20]
        )

        results = [
            {
                "id": rel.id,
                "ada": rel.ada,
                "subject": rel.subject,
                "amount": float(rel.amount) if rel.amount else None,
                "issue_date": rel.issue_date_day,
                "organization": (
                    {"uid": rel.organization.uid, "label": rel.organization.label}
                    if rel.organization
                    else None
                ),
                "decision_type": (
                    {"uid": rel.decision_type.uid, "label": rel.decision_type.label}
                    if rel.decision_type
                    else None
                ),
            }
            for rel in related_decisions
        ]

        return Response(
            {
                "decision_id": decision_id,
                "total_related": len(results),
                "results": results,
            }
        )

    except Decision.DoesNotExist:
        return Response({"error": "Decision not found"}, status=404)
    except Exception as e:
        return Response({"error": str(e)}, status=500)
