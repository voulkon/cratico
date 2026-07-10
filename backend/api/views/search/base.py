from core.models.decisions import Decision
from core.models.entities import AFMEntity
from core.models.organizations import Organization, Signer, SignerUnit, Unit
from django.db import models


def get_entity_decisions_queryset(entity_type, entity_id):
    """Helper to get decisions queryset for any entity type"""
    if entity_type == "organization":
        return Decision.objects.filter(organization__uid=entity_id)
    elif entity_type == "signer":
        return Decision.objects.filter(signers__uid=entity_id)
    elif entity_type == "unit":
        return Decision.objects.filter(units__uid=entity_id)
    elif entity_type == "afm":
        return Decision.objects.filter(
            entity_relationships__entity__afm=entity_id
        ).distinct()

    else:
        raise ValueError(f"Invalid entity type: {entity_type}")


def get_entity_info(entity_type, entity_id):
    """Get basic entity information"""
    if entity_type == "afm":
        afm_entity = AFMEntity.objects.get(afm=entity_id)
        return {
            "id": entity_id,
            "name": afm_entity.name or entity_id,
            "type": entity_type,
            "metadata": {
                "afm": afm_entity.afm,
                "name": afm_entity.name,
                "entity_type": afm_entity.entity_type,
                "total_appearances": afm_entity.total_appearances,
                "first_seen": afm_entity.first_seen,
                "last_seen": afm_entity.last_seen,
            },
        }
    elif entity_type == "organization":
        org = Organization.objects.get(uid=entity_id)
        return {
            "id": entity_id,
            "name": org.label,
            "type": entity_type,
            "metadata": {
                "uid": org.uid,
                "label": org.label,
                "category": org.category,
                "status": org.status,
            },
        }
    elif entity_type == "signer":
        signer = Signer.objects.get(uid=entity_id)

        # Get all organizations this signer has worked with and their positions
        signer_organizations = []

        # Get organizations through decisions (with position info)
        from core.models.decisions import Decision

        org_positions = (
            Decision.objects.filter(signers=signer)
            .values("organization__uid", "organization__label")
            .annotate(
                decision_count=models.Count("id"),
                latest_decision=models.Max("issue_date_day"),
                earliest_decision=models.Min("issue_date_day"),
            )
            .distinct()
        )

        # Get position information from signer's units and positions
        signer_units = SignerUnit.objects.filter(signer=signer).select_related(
            "unit", "unit__organization", "position"
        )

        # Build comprehensive organization list with positions
        org_position_map = {}

        # First, add positions from SignerUnit relationships
        for signer_unit in signer_units:
            org_uid = signer_unit.unit.organization.uid
            if org_uid not in org_position_map:
                org_position_map[org_uid] = {
                    "organization": {
                        "uid": signer_unit.unit.organization.uid,
                        "label": signer_unit.unit.organization.label,
                    },
                    "positions": [],
                }

            # Add position if not already present
            position_data = {
                "uid": signer_unit.position.uid,
                "label": signer_unit.position.label,
                "unit": signer_unit.unit.label,
                "status": "active",  # You might want to add status to SignerUnit model
            }

            # Avoid duplicates
            if position_data not in org_position_map[org_uid]["positions"]:
                org_position_map[org_uid]["positions"].append(position_data)

        # Merge with decision data
        for org_data in org_positions:
            org_uid = org_data["organization__uid"]
            if org_uid not in org_position_map:
                org_position_map[org_uid] = {
                    "organization": {
                        "uid": org_uid,
                        "label": org_data["organization__label"],
                    },
                    "positions": [],
                }

            # Add decision statistics
            org_position_map[org_uid].update(
                {
                    "decision_count": org_data["decision_count"],
                    "latest_decision": (
                        org_data["latest_decision"].isoformat()
                        if org_data["latest_decision"]
                        else None
                    ),
                    "earliest_decision": (
                        org_data["earliest_decision"].isoformat()
                        if org_data["earliest_decision"]
                        else None
                    ),
                }
            )

        signer_organizations = list(org_position_map.values())

        # Get primary organization (most decisions or most recent)
        primary_org = None
        if signer_organizations:
            primary_org = max(
                signer_organizations,
                key=lambda x: (
                    x.get("decision_count", 0),
                    x.get("latest_decision", ""),
                ),
            )

        return {
            "id": entity_id,
            "name": f"{signer.first_name} {signer.last_name}",
            "type": entity_type,
            "metadata": {
                "first_name": signer.first_name,
                "last_name": signer.last_name,
                "uid": signer.uid,
                # Primary organization (for backward compatibility)
                "organization": (
                    primary_org["organization"]["label"] if primary_org else None
                ),
                "organization_id": (
                    primary_org["organization"]["uid"] if primary_org else None
                ),
                # Enhanced organization and position data
                "organizations": signer_organizations,
                "total_organizations": len(signer_organizations),
                "total_positions": sum(
                    len(org.get("positions", [])) for org in signer_organizations
                ),
            },
        }
    elif entity_type == "unit":
        unit = Unit.objects.get(uid=entity_id)
        return {
            "id": entity_id,
            "name": unit.label,
            "type": entity_type,
            "metadata": {
                "uid": unit.uid,
                "label": unit.label,
                "organization": unit.organization.label if unit.organization else None,
                "organization_id": unit.organization.uid if unit.organization else None,
                "status": unit.status if hasattr(unit, "status") else "active",
            },
        }
    else:
        raise ValueError(f"Invalid entity type: {entity_type}")


def serialize_decision_with_content_info(decision):
    """Serialize a decision with content availability info"""
    # Get KAE amounts
    kae_amounts = []
    kae_total = None

    if hasattr(decision, "kae_amounts") and decision.kae_amounts.exists():
        kae_amounts = [
            {"kae": kae.kae, "amount": float(kae.amount)}
            for kae in decision.kae_amounts.all()
        ]
        kae_total = sum(kae.amount for kae in decision.kae_amounts.all())

    # Prefer calculated_amount (sum of amount_fields) over the
    # denormalised Decision.amount which may be NULL.
    raw_amount = (
        decision.calculated_amount
        if hasattr(decision, "calculated_amount") and decision.calculated_amount is not None
        else decision.amount
    )
    primary_amount = float(raw_amount) if raw_amount else 0
    has_discrepancy = False
    discrepancy_percentage = 0

    if kae_total and primary_amount and kae_total != primary_amount:
        has_discrepancy = True
        discrepancy_percentage = abs(
            (float(kae_total) - primary_amount) / primary_amount * 100
        )

    # Check if document content exists
    has_document_content = False
    if hasattr(decision, "text_extraction") and decision.text_extraction:
        has_document_content = (
            decision.text_extraction.extraction_status == "COMPLETED"
            and bool(decision.text_extraction.raw_text)
        )

    # Serialize signers
    signers_data = []
    if hasattr(decision, "signers"):
        signers_data = [
            {
                "uid": signer.uid,
                "first_name": signer.first_name,
                "last_name": signer.last_name,
            }
            for signer in decision.signers.all()
        ]

    return {
        "id": decision.id,
        "ada": decision.ada,
        "subject": decision.subject,
        "issue_date": decision.issue_date_day if decision.issue_date_day else None,
        "amount": float(raw_amount) if raw_amount else None,
        "decision_type": {
            "uid": decision.decision_type.uid if decision.decision_type else None,
            "label": decision.decision_type.label if decision.decision_type else None,
        },
        "status": decision.status,
        "document_url": decision.document_url or "",
        "url": f"https://diavgeia.gov.gr/luminapi/api/decisions/{decision.ada}",
        "organization": (
            {
                "uid": decision.organization.uid if decision.organization else None,
                "label": decision.organization.label if decision.organization else None,
            }
            if decision.organization
            else None
        ),
        "signers": signers_data,
        "kae_amounts": kae_amounts,
        "kae_total": float(kae_total) if kae_total else None,
        "has_amount_discrepancy": has_discrepancy,
        "discrepancy_percentage": round(discrepancy_percentage, 2),
        "has_document_content": has_document_content,
    }


def serialize_decision_with_entities(decision, entity_relationships=None):
    """
    Serialize a decision with entity relationship data included.
    This optimized version includes entity amounts and main recipient upfront,
    avoiding the need for separate API calls per decision.
    """
    # Start with base serialization
    data = serialize_decision_with_content_info(decision)

    # Add entity relationship data if provided
    if entity_relationships is not None:
        # Find main recipient (sponsor/creditor with amount)
        main_recipient = None
        total_entity_amount = 0

        for rel in entity_relationships:
            # Skip org entities (usually 0 amount)
            if rel.get("role", "").lower() == "org":
                continue

            amount = rel.get("total_amount", 0)
            if amount:
                total_entity_amount += amount

                # Prioritize sponsors/creditors
                if not main_recipient or rel.get("role", "").lower() in [
                    "sponsorafmname",
                    "creditor",
                    "sponsor",
                ]:
                    main_recipient = {
                        "afm": rel.get("entity", {}).get("afm"),
                        "name": rel.get("entity", {}).get("name"),
                        "amount": amount,
                        "role": rel.get("role"),
                    }

        # Add entity data to response
        data["entity_amount"] = total_entity_amount if total_entity_amount > 0 else None
        data["main_recipient"] = main_recipient
        data["entity_count"] = len(
            [r for r in entity_relationships if r.get("role", "").lower() != "org"]
        )

    return data
