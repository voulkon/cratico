"""
Common utilities for admin views.
Shared functionality across different admin interfaces.
"""

from core.models.companies import Company, CompanyPerson
from core.models.organizations import Organization, Signer, Unit
from core.services.search_service import SearchService
from django.db.models import Q
from django.http import JsonResponse
from loguru import logger


def entity_search_ajax(request):
    """
    Generic AJAX endpoint for searching entities (organizations, signers, units, companies, company persons).
    Used by Select2 dropdowns across multiple admin interfaces.

    GET Parameters:
        q: Search query string
        entity_type: Type of entity to search ('organization', 'signer', 'unit', 'company', 'company_person')

    Returns:
        JSON response with results array
    """
    query = request.GET.get("q", "")
    entity_type = request.GET.get("entity_type", "organization")

    results = []

    if query and len(query) >= 2:
        try:
            if entity_type == "organization":
                # Use SearchService for consistency
                search_service = SearchService()
                organizations = search_service.search_organizations(query)

                results = [
                    {
                        "id": org.uid,
                        "text": org.label,
                        "latin_name": org.latin_name,
                    }
                    for org in organizations
                ]

            elif entity_type == "signer":
                # Use SearchService for consistency
                search_service = SearchService()
                signers = search_service.search_signers(query)

                results = [
                    {
                        "id": signer.uid,
                        "text": f"{signer.last_name}, {signer.first_name}",
                        "last_name": signer.last_name,
                        "first_name": signer.first_name,
                        "organization": (
                            signer.organization.label if signer.organization else None
                        ),
                        "organization_id": (
                            signer.organization.uid if signer.organization else None
                        ),
                    }
                    for signer in signers
                ]

            elif entity_type == "unit":
                # Use SearchService for consistency
                search_service = SearchService()
                units = search_service.search_units(query)

                results = [
                    {
                        "id": unit.uid,
                        "text": unit.label,
                        "latin_name": None,
                        "organization": (
                            unit.organization.label if unit.organization else None
                        ),
                        "organization_id": (
                            unit.organization.uid if unit.organization else None
                        ),
                    }
                    for unit in units
                ]

            elif entity_type == "company":
                # Search companies by name
                companies = Company.objects.filter(
                    Q(co_name_el__icontains=query) | Q(co_name_en__icontains=query)
                ).order_by("co_name_el")[:20]

                results = [
                    {
                        "id": company.ar_gemi,
                        "text": company.co_name_el or company.co_name_en or "No name",
                        "ar_gemi": company.ar_gemi,
                    }
                    for company in companies
                ]

            elif entity_type == "company_person":
                # Search company persons by name
                persons = CompanyPerson.objects.filter(
                    Q(person_name__icontains=query) | Q(business_name__icontains=query)
                ).order_by("person_name")[:20]

                results = [
                    {
                        "id": str(person.id),
                        "text": person.person_name or person.business_name or "No name",
                        "business_name": person.business_name,
                    }
                    for person in persons
                ]

        except Exception as e:
            logger.error(f"Error searching entities: {e}")

    return JsonResponse({"results": results})


def get_entity_display_name(entity_type, entity_id):
    """
    Get the display name for an entity.

    Args:
        entity_type: Type of entity ('organization', 'signer', 'unit', 'company', 'company_person')
        entity_id: UID or ID of the entity

    Returns:
        Display name string or None if not found
    """
    try:
        if entity_type == "organization":
            entity = Organization.objects.get(uid=entity_id)
            return entity.label
        elif entity_type == "signer":
            entity = Signer.objects.get(uid=entity_id)
            return f"{entity.first_name} {entity.last_name}"
        elif entity_type == "unit":
            entity = Unit.objects.get(uid=entity_id)
            return entity.label
        elif entity_type == "company":
            entity = Company.objects.get(ar_gemi=entity_id)
            return entity.co_name_el or entity.co_name_en or "No name"
        elif entity_type == "company_person":
            entity = CompanyPerson.objects.get(id=entity_id)
            return entity.person_name or entity.business_name or "No name"
    except Exception as e:
        logger.error(f"Error getting entity display name: {e}")
        return None

    return None
