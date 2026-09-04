import re

from core.services.search_service import SearchService
from core.services.transliteration import TransliterationService
from core.utils.search_trace import finish_search_trace, start_search_trace


def determine_matched_field(entity_type, entity, query):
    """
    Determine which field likely matched the search query
    """
    query_lower = query.lower()

    if entity_type == "organization":
        if query_lower in entity.label.lower():
            return "name"
        elif entity.latin_name and query_lower in entity.latin_name.lower():
            return "latin_name"
        elif entity.category and query_lower in entity.category.lower():
            return "category"
        elif entity.vat_number and query_lower in entity.vat_number.lower():
            return "vat_number"
    elif entity_type == "signer":
        if (
            query_lower in entity.first_name.lower()
            or query_lower in entity.last_name.lower()
        ):
            return "name"
    elif entity_type == "unit":
        if query_lower in entity.label.lower():
            return "name"
        elif entity.category and query_lower in entity.category.lower():
            return "category"
    elif entity_type == "company":
        if entity.co_name_el and query_lower in entity.co_name_el.lower():
            return "name"
        elif entity.afm and query_lower in entity.afm:
            return "afm"
        elif str(entity.ar_gemi) in query:
            return "gemi"
    elif entity_type == "company_person":
        if entity.person_name and query_lower in entity.person_name.lower():
            return "person_name"
        elif entity.business_name and query_lower in entity.business_name.lower():
            return "business_name"
        elif entity.role and query_lower in entity.role.lower():
            return "role"
    elif entity_type == "afmentity":
        if entity.name and query_lower in entity.name.lower():
            return "name"
        elif entity.afm and query_lower in entity.afm:
            return "afm"

    return "other"


def highlight_query_in_text(text, query, max_length=300):
    """
    Highlight query terms in text and return a truncated excerpt
    """
    if not text or not query:
        return (
            text[:max_length] + ("..." if len(text) > max_length else "")
            if text
            else ""
        )

    # Simple highlighting - wrap matching terms in <mark> tags
    # This is a basic implementation - you might want to use more sophisticated highlighting
    query_terms = query.strip().split()
    highlighted_text = text

    for term in query_terms:
        if len(term) > 2:  # Only highlight terms longer than 2 characters
            pattern = re.compile(re.escape(term), re.IGNORECASE)
            highlighted_text = pattern.sub(f"<mark>{term}</mark>", highlighted_text)

    # Truncate if needed
    if len(highlighted_text) > max_length:
        # Try to find a good breaking point near a highlight
        mark_pos = highlighted_text.find("<mark>")
        if mark_pos > -1 and mark_pos < max_length:
            # Start excerpt a bit before the highlight
            start = max(0, mark_pos - 50)
            end = min(len(highlighted_text), start + max_length)
            excerpt = highlighted_text[start:end]
            if start > 0:
                excerpt = "..." + excerpt
            if end < len(highlighted_text):
                excerpt = excerpt + "..."
            return excerpt
        else:
            return highlighted_text[:max_length] + "..."

    return highlighted_text


# TODO: Protocol on response to be able to replace it with a function that searches the db
def get_administrative_terms_autocomplete(query_prefix=""):
    """
    Get autocomplete suggestions for Greek administrative terms.

    Args:
        query_prefix: Optional prefix to filter suggestions (automatically transliterated)

    # Common Greek administrative terms for autocomplete
    """
    # Transliterate the query prefix if provided
    if query_prefix:
        query_prefix = TransliterationService.transliterate_query(query_prefix).upper()

    GREEK_ADMINISTRATIVE_TERMS = [
        {"text": "ΔΗΜΟΣ", "category": "organization", "description": "Municipality"},
        {"text": "ΠΕΡΙΦΕΡΕΙΑ", "category": "organization", "description": "Region"},
        {"text": "ΥΠΟΥΡΓΕΙΟ", "category": "organization", "description": "Ministry"},
        {
            "text": "ΓΕΝΙΚΗ ΓΡΑΜΜΑΤΕΙΑ",
            "category": "organization",
            "description": "General Secretariat",
        },
        {"text": "ΝΟΜΑΡΧΙΑ", "category": "organization", "description": "Prefecture"},
        {
            "text": "ΔΗΜΟΤΙΚΗ ΕΠΙΧΕΙΡΗΣΗ",
            "category": "organization",
            "description": "Municipal Enterprise",
        },
        {"text": "ΚΟΙΝΟΤΗΤΑ", "category": "organization", "description": "Community"},
        {
            "text": "ΝΠΔΔ",
            "category": "organization",
            "description": "Legal Entity under Public Law",
        },
        {
            "text": "ΝΠΙΔ",
            "category": "organization",
            "description": "Legal Entity under Private Law",
        },
        {"text": "ΑΕ", "category": "company", "description": "Société Anonyme"},
        {
            "text": "ΕΠΕ",
            "category": "company",
            "description": "Limited Liability Company",
        },
        {"text": "ΟΕ", "category": "company", "description": "General Partnership"},
        {"text": "ΙΚΕ", "category": "company", "description": "Private Company"},
    ]
    return GREEK_ADMINISTRATIVE_TERMS


def _merge_deduped_results(primary_results, fallback_results, id_getter, limit):
    """
    Merge two lists of entity results, deduplicating by ID.
    Primary results (from transliterated query) come first.
    Fallback results (from original query) fill in missing entities.
    """
    seen = set()
    merged = []

    for obj in primary_results:
        obj_id = id_getter(obj)
        if obj_id not in seen:
            seen.add(obj_id)
            merged.append(obj)

    for obj in fallback_results:
        obj_id = id_getter(obj)
        if obj_id not in seen:
            seen.add(obj_id)
            merged.append(obj)
            if len(merged) >= limit:
                break

    return merged[:limit]


def get_entities_fast(query, **kwargs):
    """
    Fast entity search - returns organizations, signers, units, companies, and company_persons
    This uses PostgreSQL queries and is typically much faster than document search

    Searches with BOTH the transliterated query (for Greek/Greeklish matches, e.g. "DHMOS" -> "ΔΗΜΟΣ")
    AND the original query (for Latin/English matches, e.g. "nova"). Results are merged and deduplicated.
    """
    # Compute transliterated version for Greeklish input (e.g., "DHMOS" -> "ΔΗΜΟΣ")
    transliterated_query = TransliterationService.transliterate_query(query)

    search_service = SearchService()

    # Start a per-request trace (no-op unless DEBUG_SEARCH_SERVICE=1)
    trace = start_search_trace(query)
    if trace is not None:
        trace.add(
            "transliteration",
            transliterated=transliterated_query,
            changed=(transliterated_query != query),
        )

    # Extract parameters
    entity_types = kwargs.get(
        "entity_types", ["organization", "signer", "unit", "company", "company_person"]
    )
    organization_id = kwargs.get("organization_id")
    company_id = kwargs.get("company_id")
    limit = kwargs.get("limit", 5)

    results = {"query": query, "results": {}, "total_count": 0, "type": "entities"}

    if not query:
        finish_search_trace(trace)
        return results

    # Search entities based on requested types
    # For each type, search with transliterated query (Greek) and supplement with
    # original query (Latin/English) results, deduplicating by entity ID.
    if "organization" in entity_types:
        orgs = list(search_service.search_organizations(transliterated_query, limit))
        if transliterated_query != query:
            fallback = list(search_service.search_organizations(query, limit))
            if trace is not None:
                trace.add(
                    "fallback_search",
                    type="organization",
                    reason="transliteration_changed",
                    fallback_count=len(fallback),
                )
            orgs = _merge_deduped_results(
                orgs, fallback, lambda o: o.uid, limit
            )
        results["results"]["organizations"] = [
            format_organization(org, query) for org in orgs
        ]
        results["total_count"] += len(orgs)

    if "signer" in entity_types:
        signers = list(
            search_service.search_signers(transliterated_query, organization_id, limit)
        )
        if transliterated_query != query:
            fallback = list(
                search_service.search_signers(query, organization_id, limit)
            )
            if trace is not None:
                trace.add(
                    "fallback_search",
                    type="signer",
                    reason="transliteration_changed",
                    fallback_count=len(fallback),
                )
            signers = _merge_deduped_results(
                signers, fallback, lambda s: s.uid, limit
            )
        results["results"]["signers"] = [
            format_signer(signer, query) for signer in signers
        ]
        results["total_count"] += len(signers)

    if "unit" in entity_types:
        units = list(
            search_service.search_units(transliterated_query, organization_id, limit)
        )
        if transliterated_query != query:
            fallback = list(
                search_service.search_units(query, organization_id, limit)
            )
            if trace is not None:
                trace.add(
                    "fallback_search",
                    type="unit",
                    reason="transliteration_changed",
                    fallback_count=len(fallback),
                )
            units = _merge_deduped_results(
                units, fallback, lambda u: u.uid, limit
            )
        results["results"]["units"] = [format_unit(unit, query) for unit in units]
        results["total_count"] += len(units)

    if "company" in entity_types:
        companies = list(search_service.search_companies(transliterated_query, limit))
        if transliterated_query != query:
            fallback = list(search_service.search_companies(query, limit))
            if trace is not None:
                trace.add(
                    "fallback_search",
                    type="company",
                    reason="transliteration_changed",
                    fallback_count=len(fallback),
                )
            companies = _merge_deduped_results(
                companies, fallback, lambda c: c.ar_gemi, limit
            )
        results["results"]["companies"] = [
            format_company(company, query) for company in companies
        ]
        results["total_count"] += len(companies)

    if "company_person" in entity_types:
        company_persons = list(
            search_service.search_company_persons(
                transliterated_query, company_id, limit
            )
        )
        if transliterated_query != query:
            fallback = list(
                search_service.search_company_persons(query, company_id, limit)
            )
            if trace is not None:
                trace.add(
                    "fallback_search",
                    type="company_person",
                    reason="transliteration_changed",
                    fallback_count=len(fallback),
                )
            company_persons = _merge_deduped_results(
                company_persons, fallback, lambda p: p.pk, limit
            )
        results["results"]["company_persons"] = [
            format_company_person(person, query) for person in company_persons
        ]
        results["total_count"] += len(company_persons)

    if "afmentity" in entity_types:
        afm_entities = list(
            search_service.search_afm_entities(transliterated_query, limit)
        )
        if transliterated_query != query:
            fallback = list(search_service.search_afm_entities(query, limit))
            if trace is not None:
                trace.add(
                    "fallback_search",
                    type="afm_entity",
                    reason="transliteration_changed",
                    fallback_count=len(fallback),
                )
            afm_entities = _merge_deduped_results(
                afm_entities, fallback, lambda e: e.pk, limit
            )
        results["results"]["afm_entities"] = [
            format_afmentity(entity, query) for entity in afm_entities
        ]
        results["total_count"] += len(afm_entities)

    if trace is not None:
        trace.add("done", total_count=results["total_count"])
    finish_search_trace(trace)
    return results


def get_documents_slow(query, limit=5):
    """
    Slow document search - queries OpenSearch for document content
    This is typically slower than entity search and may not always be needed

    Automatically transliterates English letters to Greek (e.g., "DHMOS" -> "ΔΗΜΟΣ")
    """
    # Transliterate English letters to Greek if needed
    # I'm not sure I want this here. If someone is looking for "mydata", I don't want to transliterate it to "μυδατα". Maybe we should only transliterate if the query is all uppercase and matches common patterns for Greek words?
    # Yet again, there time that I want it
    # query = TransliterationService.transliterate_query(query)

    search_service = SearchService()

    results = {"query": query, "results": {}, "total_count": 0, "type": "documents"}

    if not query:
        return results

    try:
        doc_results = search_service.search_documents(query, limit=limit)
        serialized_docs = []

        for doc in doc_results["results"]:
            # Handle both OpenSearch results (dict with 'extraction' key) and PostgreSQL results
            if isinstance(doc, dict) and "extraction" in doc:
                # OpenSearch result format
                extraction = doc["extraction"]
                decision = extraction.decision

                doc_data = {
                    "id": extraction.id,
                    "type": "document",
                    "title": (
                        decision.subject[:100]
                        + ("..." if len(decision.subject) > 100 else "")
                        if decision
                        else "Untitled Document"
                    ),
                    "subtitle": f"By {decision.organization.label if decision and decision.organization else 'Unknown Organization'}",
                    "description": doc.get("text_excerpt", "No preview available"),
                    "details": {
                        "decision_id": decision.id if decision else None,
                        "ada": decision.ada if decision else None,
                        "organization": (
                            decision.organization.label
                            if decision and decision.organization
                            else None
                        ),
                        "organization_id": (
                            decision.organization.uid
                            if decision and decision.organization
                            else None
                        ),
                        "decision_type": (
                            decision.get_decision_type_label() if decision else None
                        ),
                        "issue_date": (
                            decision.issue_date.isoformat()
                            if decision and decision.issue_date
                            else None
                        ),
                        "amount": (
                            str(decision.amount)
                            if decision and decision.amount
                            else None
                        ),
                        "currency": decision.currency if decision else None,
                        "status": decision.status if decision else None,
                        "provider": extraction.extraction_provider,
                        "is_scanned": extraction.is_scanned_document,
                        "protocol_number": (
                            decision.protocol_number if decision else None
                        ),
                        "signers": [
                            f"{s.first_name} {s.last_name}"
                            for s in doc.get("signers", [])
                        ],
                    },
                    "search_score": doc.get("search_score", 0),
                    "highlights": doc.get("highlights", {}),
                    "source": "opensearch",
                    "matched_field": "content",
                    "icon": "document",
                }
                serialized_docs.append(doc_data)
            else:
                # PostgreSQL fallback result format
                extraction = doc["extraction"] if isinstance(doc, dict) else doc
                decision = extraction.decision

                doc_data = {
                    "id": extraction.id,
                    "type": "document",
                    "title": (
                        decision.subject[:100]
                        + ("..." if len(decision.subject) > 100 else "")
                        if decision
                        else "Untitled Document"
                    ),
                    "subtitle": f"By {decision.organization.label if decision and decision.organization else 'Unknown Organization'}",
                    "description": (
                        extraction.raw_text[:300]
                        + ("..." if len(extraction.raw_text or "") > 300 else "")
                        if hasattr(extraction, "raw_text") and extraction.raw_text
                        else "No preview available"
                    ),
                    "details": {
                        "decision_id": decision.id if decision else None,
                        "ada": decision.ada if decision else None,
                        "organization": (
                            decision.organization.label
                            if decision and decision.organization
                            else None
                        ),
                        "organization_id": (
                            decision.organization.uid
                            if decision and decision.organization
                            else None
                        ),
                        "decision_type": (
                            decision.get_decision_type_label() if decision else None
                        ),
                        "issue_date": (
                            decision.issue_date.isoformat()
                            if decision and decision.issue_date
                            else None
                        ),
                        "amount": (
                            str(decision.amount)
                            if decision and decision.amount
                            else None
                        ),
                        "currency": decision.currency if decision else None,
                        "status": decision.status if decision else None,
                        "provider": extraction.extraction_provider,
                        "is_scanned": extraction.is_scanned_document,
                        "protocol_number": (
                            decision.protocol_number if decision else None
                        ),
                        "signers": (
                            [
                                f"{s.first_name} {s.last_name}"
                                for s in decision.signers.all()
                            ]
                            if decision
                            else []
                        ),
                    },
                    "search_score": (
                        doc.get("search_score", 1.0) if isinstance(doc, dict) else 1.0
                    ),
                    "highlights": (
                        doc.get("highlights", {}) if isinstance(doc, dict) else {}
                    ),
                    "source": "postgresql",
                    "matched_field": "content",
                    "icon": "document",
                }
                serialized_docs.append(doc_data)

        results["results"]["documents"] = serialized_docs
        results["total_count"] = doc_results["count"]
    except Exception as e:
        # If OpenSearch fails, return empty results but don't crash
        print(f"Document search failed: {e}")
        results["results"]["documents"] = []
        results["error"] = str(e)

    return results


def format_organization(org, query=None):
    """Format an Organization object for API response"""
    return {
        "id": org.uid,
        "text": org.label,
        "type": "organization",
        "title": highlight_query_in_text(org.label, query, 100) if query else org.label,
        "subtitle": f"{org.category} • {org.latin_name}",
        "description": f"VAT: {org.vat_number or 'N/A'} • Status: {org.status.title()}",
        "details": {
            "latin_name": org.latin_name,
            "category": org.category,
            "vat_number": org.vat_number,
            "status": org.status,
            "website": org.website,
            "supervisor": org.supervisor_org_name,
        },
        "matched_field": (
            determine_matched_field("organization", org, query) if query else None
        ),
        "icon": "building",
    }


def format_signer(signer, query=None):
    """Format a Signer object for API response"""
    return {
        "id": signer.uid,
        "text": f"{signer.last_name}, {signer.first_name}",
        "type": "signer",
        "title": (
            highlight_query_in_text(
                f"{signer.first_name} {signer.last_name}", query, 100
            )
            if query
            else f"{signer.first_name} {signer.last_name}"
        ),
        "subtitle": (
            signer.organization.label if signer.organization else "No organization"
        ),
        "description": f"Signer • {'Active' if signer.active else 'Inactive'}",
        "details": {
            "first_name": signer.first_name,
            "last_name": signer.last_name,
            "organization": signer.organization.label if signer.organization else None,
            "organization_id": signer.organization.uid if signer.organization else None,
            "active": signer.active,
            "has_org_sign_rights": signer.has_organization_sign_rights,
            "active_from": (
                signer.active_from.isoformat() if signer.active_from else None
            ),
            "active_until": (
                signer.active_until.isoformat() if signer.active_until else None
            ),
        },
        "matched_field": (
            determine_matched_field("signer", signer, query) if query else None
        ),
        "icon": "user",
    }


def format_unit(unit, query=None):
    """Format a Unit object for API response"""
    return {
        "id": unit.uid,
        "text": unit.label,
        "type": "unit",
        "title": (
            highlight_query_in_text(unit.label, query, 100) if query else unit.label
        ),
        "subtitle": unit.organization.label if unit.organization else "No organization",
        "description": f"Unit • {unit.category} • {'Active' if unit.active else 'Inactive'}",
        "details": {
            "organization": unit.organization.label if unit.organization else None,
            "organization_id": unit.organization.uid if unit.organization else None,
            "category": unit.category,
            "active": unit.active,
            "active_from": unit.active_from.isoformat() if unit.active_from else None,
            "active_until": (
                unit.active_until.isoformat() if unit.active_until else None
            ),
            "parent_unit": unit.parent.label if unit.parent else None,
        },
        "matched_field": (
            determine_matched_field("unit", unit, query) if query else None
        ),
        "icon": "department",
    }


def format_company(company, query=None):
    """Format a Company object for API response"""
    return {
        "id": company.ar_gemi,
        "text": company.co_name_el or "No name",
        "type": "company",
        "title": (
            highlight_query_in_text(company.co_name_el or "No name", query, 100)
            if query
            else company.co_name_el or "No name"
        ),
        "subtitle": f"{company.legal_type_name or 'Company'} • {company.municipality_name or 'Unknown location'}",
        "afm": f"{company.afm or 'N/A'}",
        "description": f"AFM: {company.afm or 'N/A'} • Status: {company.status_name or 'Unknown'}",
        "details": {
            "co_name_el": company.co_name_el,
            "co_names_en": company.co_names_en,
            "co_titles_el": company.co_titles_el,
            "co_titles_en": company.co_titles_en,
            "afm": company.afm,
            "ar_gemi": company.ar_gemi,
            "legal_type": company.legal_type_name,
            "municipality_name": company.municipality_name,
            "prefecture_name": company.prefecture_name,
            "status_name": company.status_name,
            "incorporation_date": company.incorporation_date,
            "website": company.url,
            "email": company.email,
        },
        "matched_field": (
            determine_matched_field("company", company, query) if query else None
        ),
        "icon": "company",
    }


def format_company_person(person, query=None):
    """Format a CompanyPerson object for API response"""
    return {
        "id": person.id,
        "text": person.person_name or person.business_name or "No name",
        "type": "company_person",
        "title": (
            highlight_query_in_text(
                person.person_name or person.business_name or "No name", query, 100
            )
            if query
            else person.person_name or person.business_name or "No name"
        ),
        "subtitle": f"{person.role or 'Unknown role'} at {person.company.co_name_el if person.company else 'Unknown company'}",
        "description": f"Company Person • {person.date_from or 'Date unknown'}",
        "details": {
            "person_name": person.person_name,
            "business_name": person.business_name,
            "role": person.role,
            "company_name": person.company.co_name_el if person.company else None,
            "company_id": person.company.ar_gemi if person.company else None,
            "date_from": person.date_from,
            "date_to": person.date_to,
            "is_representative_alone": person.is_representative_alone,
            "is_representative_in_common": person.is_representative_in_common,
        },
        "matched_field": (
            determine_matched_field("company_person", person, query) if query else None
        ),
        "icon": "user-tie",
    }


def format_afmentity(entity, query=None):
    """Format an AFMEntity object for API response"""
    entity_type_display = entity.get_entity_type_display() if entity.entity_type else "Unknown"
    return {
        "id": entity.id,
        "text": entity.name or f"AFM: {entity.afm}",
        "type": "afmentity",
        "title": (
            highlight_query_in_text(entity.name or f"AFM: {entity.afm}", query, 100)
            if query
            else entity.name or f"AFM: {entity.afm}"
        ),
        "subtitle": f"AFM: {entity.afm} • {entity_type_display}",
        "description": (
            f"Appeared in {entity.total_appearances} decision(s) • "
            f"First seen: {entity.first_seen.strftime('%Y-%m-%d') if entity.first_seen else 'N/A'}"
        ),
        "details": {
            "afm": entity.afm,
            "entity_type": entity.entity_type,
            "entity_type_display": entity_type_display,
            "total_appearances": entity.total_appearances,
            "first_seen": entity.first_seen.isoformat() if entity.first_seen else None,
            "last_seen": entity.last_seen.isoformat() if entity.last_seen else None,
            "gemi_lookup_success": entity.gemi_lookup_success,
            "gemi_companies_count": entity.gemi_companies_count,
        },
        "matched_field": (
            determine_matched_field("afmentity", entity, query) if query else None
        ),
        "icon": "fingerprint",
    }
