from core.models.companies import Company
from core.models.decision_ai_analysis import DecisionAIAnalysis
from core.models.decisions import Decision
from core.models.document_analysis import DocumentExtraction, ProcessingStatus
from core.models.entities import DecisionAmountField, DecisionEntityRelationship
from core.schemas.decision_detail import DecisionDetailResponse
from core.services.decision_facets import effective_linked_amount_sum
from api.utils.decision_refs import resolve_decision
from api.utils.response import pydantic_response
from django.conf import settings
from django.db.models import Count, F, Q
from rest_framework.decorators import api_view, permission_classes
from api.permissions import PublicReadOnly
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([PublicReadOnly])
def decision_detail(request, decision_ref):
    """Get detailed decision information with all relationships.

    ``decision_ref`` is either the integer PK or the ΑΔΑ (ADA).
    """
    try:
        decision = resolve_decision(
            decision_ref,
            Decision.objects.select_related("organization", "decision_type")
            .prefetch_related("signers", "units", "kae_amounts", "attachments"),
        )

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
        # ── Single pass over DecisionAmountField ────────────────────────
        # The per-decision amount-field set is tiny (a handful of rows), so
        # fetch it ONCE and derive everything in Python:
        #   - effective total: COALESCE(verified_amount, amount), excluding
        #     rows flagged as non-monetary values (counterpart ΑΦΜ / ΚΑΕ
        #     mis-recorded as amount).  The denormalised Decision.amount is
        #     NEVER used directly: it may be NULL, a typo, or non-monetary.
        #   - has_corrected_amounts / corrected_amount (verified-aware total)
        #   - invalid-amount state for the UI warning
        # This avoids three separate aggregate/exists queries against the
        # same table (and duplicates work the /entities/ endpoint does).
        amount_fields = list(
            DecisionAmountField.objects.filter(decision=decision).only(
                "amount", "verified_amount", "invalid_amount_reason",
                "invalid_amount_value",
            )
        )

        effective_total = sum(
            (f.verified_amount if f.verified_amount is not None else f.amount)
            for f in amount_fields
            if not f.invalid_amount_reason
            and (f.verified_amount is not None or f.amount is not None)
        ) or None

        corrected_fields = [
            f for f in amount_fields if f.verified_amount is not None
        ]
        has_corrected = bool(corrected_fields)
        # Verified-aware total: same sum but WITHOUT excluding invalid rows'
        # verified values — invalid rows never carry a verified_amount, so
        # the effective total above already equals the corrected total.
        corrected_total = effective_total if has_corrected else None

        invalid_field = next(
            (f for f in amount_fields if f.invalid_amount_reason), None
        )

        decision_data = {
            "id": decision.id,
            "ada": decision.ada,
            # TODO: Do I need these?
            "version_id": decision.version_id,
            "corrected_version_id": decision.corrected_version_id,
            "protocol_number": decision.protocol_number,
            "subject": decision.subject,
            # TODO: Do I need these?
            "amount": float(effective_total) if effective_total is not None else None,
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

        # Amount-correction state — computed from the single amount_fields
        # pass above (no extra queries).
        decision_data["has_corrected_amounts"] = has_corrected
        decision_data["corrected_amount"] = (
            float(corrected_total)
            if has_corrected and corrected_total is not None
            else None
        )

        # Non-monetary amount state — the recorded amount is really a
        # counterpart AFM (ΑΦΜ) or a budget KAE (ΚΑΕ), so it is not money and
        # the real amount is unknown.  The facet layer already excludes such
        # rows from every aggregation; this tells the UI to say so instead of
        # rendering a bogus 9-figure amount.
        decision_data["has_invalid_amount"] = invalid_field is not None
        decision_data["invalid_amount_reason"] = (
            invalid_field.invalid_amount_reason if invalid_field else None
        )
        decision_data["invalid_amount_value"] = (
            invalid_field.invalid_amount_value if invalid_field else None
        )

        return pydantic_response(DecisionDetailResponse(**decision_data))

    except Decision.DoesNotExist:
        return Response({"error": "Decision not found"}, status=404)
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
@permission_classes([PublicReadOnly])
def decision_entities(request, decision_ref):
    """
    Return entity relationships for a decision with the **total amount per entity**
    calculated in SQL via the new FK `associated_relationship`.

    ``decision_ref`` is either the integer PK or the ΑΔΑ (ADA).
    """
    try:
        # Ensure the decision exists
        decision = resolve_decision(decision_ref, Decision.objects.only("id", "ada"))
    except Decision.DoesNotExist:
        return Response({"error": "Decision not found"}, status=404)

    # ------------------------------------------------------------------
    # 1. Aggregate amounts per (role, entity) in one SQL query
    # ------------------------------------------------------------------
    totals_qs = (
        DecisionEntityRelationship.objects.filter(decision=decision)
        .values("role", "entity")  # GROUP BY role, entity
        .annotate(
            total_amount=effective_linked_amount_sum(),
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
        DecisionEntityRelationship.objects.filter(decision=decision)
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
            "decision_id": decision.id,
            "decision_ada": decision.ada,
            "relationships": list(grouped.values()),
            "total_entities": len(grouped),
        }
    )


@api_view(["GET"])
@permission_classes([PublicReadOnly])
def decision_companies(request, decision_ref):
    """Get all companies associated with a decision (integer PK or ΑΔΑ)."""
    try:
        decision = resolve_decision(decision_ref)

        # Get all AFMs from this decision's entities
        entity_afms = DecisionEntityRelationship.objects.filter(
            decision=decision
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
                    decision=decision, entity__afm=company.afm
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
                "decision_id": decision.id,
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
@permission_classes([PublicReadOnly])
def decision_related(request, decision_ref):
    """Get related decisions — same organization or decision type, most recent.

    ``decision_ref`` is either the integer PK or the ΑΔΑ (ADA).

    Deliberately simple: a "related" sidebar does not justify the
    effective-amount aggregate (a correlated subquery per candidate row that
    cost ~1s even on a 200-row capped set).  We filter on the cheap indexed
    columns (org / type) and order by recency — no amount annotation, no
    similarity matching.  Amounts are omitted from the payload.
    """
    try:
        decision = resolve_decision(
            decision_ref,
            Decision.objects.select_related("organization", "decision_type"),
        )

        related_query = Q()
        if decision.organization:
            related_query |= Q(organization=decision.organization)
        if decision.decision_type:
            related_query |= Q(decision_type=decision.decision_type)

        related_decisions = (
            Decision.objects.filter(related_query)
            .exclude(id=decision.id)
            .select_related("organization", "decision_type")
            .order_by("-issue_date_day")[:20]
        )

        results = [
            {
                "id": rel.id,
                "ada": rel.ada,
                "subject": rel.subject,
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
                "decision_id": decision.id,
                "total_related": len(results),
                "results": results,
            }
        )

    except Decision.DoesNotExist:
        return Response({"error": "Decision not found"}, status=404)
    except Exception as e:
        return Response({"error": str(e)}, status=500)
