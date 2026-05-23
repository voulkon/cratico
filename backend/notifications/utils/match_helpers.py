"""
Match helpers for determining why decisions matched subscriptions.

This module contains business logic for analyzing decision-subscription matches
and generating match reasons and details.
"""

from notifications.constants import (
    KEYWORD_OPERATOR_AND,
    SUBSCRIPTION_TYPE_ENTITY,
    SUBSCRIPTION_TYPE_FILTER,
    SUBSCRIPTION_TYPE_ORGANIZATION,
    SUBSCRIPTION_TYPE_PERSON,
    SUBSCRIPTION_TYPE_RELATIONSHIP,
    SUBSCRIPTION_TYPE_SIGNER,
)


def determine_match_reason(subscription, decision):
    """
    Determine why this decision matched and provide details.

    Analyzes the subscription and decision to determine the primary match reason
    and collect detailed information about what criteria were matched.

    Args:
        subscription: NotificationSubscription instance
        decision: Decision instance that matched

    Returns:
        tuple: (match_reason, match_details)
            - match_reason: string indicating primary reason (e.g., 'organization', 'keyword_match')
            - match_details: dict with detailed match information
    """
    match_details = {}

    # Determine primary match reason based on subscription type
    subscription_type = subscription.subscription_type

    # Add subscription type to match details
    match_details["subscription_type"] = subscription_type

    # Check keyword matches in both subject and document text
    if subscription.keywords:
        found_keywords = []
        found_in_locations = []

        subject_text = (decision.subject or "").lower()

        # Get document text if available
        document_text = ""
        if hasattr(decision, "text_extraction") and decision.text_extraction:
            document_text = (decision.text_extraction.raw_text or "").lower()

        for keyword in subscription.keywords:
            keyword_lower = keyword.lower()
            if keyword_lower in subject_text:
                found_keywords.append(keyword)
                if "subject" not in found_in_locations:
                    found_in_locations.append("subject")
            if document_text and keyword_lower in document_text:
                if keyword not in found_keywords:
                    found_keywords.append(keyword)
                if "document_text" not in found_in_locations:
                    found_in_locations.append("document_text")

        if found_keywords:
            match_details["keywords_found"] = list(set(found_keywords))
            match_details["keywords_found_in"] = found_in_locations
            match_details["keyword_match_operator"] = getattr(
                subscription, "keyword_match_operator", KEYWORD_OPERATOR_AND
            )

    # Check amount match
    if subscription.amount_min or subscription.amount_max:
        if hasattr(decision, "amount") and decision.amount:
            match_details["amount"] = str(decision.amount)
            match_details["amount_in_range"] = True

    # Check decision type match
    if subscription.decision_types:
        if decision.decision_type_id in subscription.decision_types:
            match_details["decision_type_matched"] = decision.decision_type_id

    # Determine primary match reason based on subscription type and filters
    # Priority: subscription type first, then specific filters
    if subscription_type == SUBSCRIPTION_TYPE_ORGANIZATION:
        match_reason = SUBSCRIPTION_TYPE_ORGANIZATION
        match_details["organization_uid"] = (
            subscription.organization.uid if subscription.organization else None
        )
    elif subscription_type == SUBSCRIPTION_TYPE_ENTITY:
        match_reason = SUBSCRIPTION_TYPE_ENTITY
        match_details["entity_afm"] = (
            subscription.entity.afm if subscription.entity else None
        )
    elif subscription_type == SUBSCRIPTION_TYPE_RELATIONSHIP:
        match_reason = SUBSCRIPTION_TYPE_RELATIONSHIP
        match_details["relationship_org_uid"] = (
            subscription.relationship_org.uid if subscription.relationship_org else None
        )
        match_details["relationship_entity_afm"] = (
            subscription.relationship_entity.afm
            if subscription.relationship_entity
            else None
        )
    elif subscription_type == SUBSCRIPTION_TYPE_PERSON:
        match_reason = SUBSCRIPTION_TYPE_PERSON
        match_details["person_name"] = subscription.person_name
    elif subscription_type == SUBSCRIPTION_TYPE_SIGNER:
        match_reason = SUBSCRIPTION_TYPE_SIGNER
        match_details["signer_name"] = subscription.signer_name
    elif subscription_type == SUBSCRIPTION_TYPE_FILTER:
        # For filter-only subscriptions, determine match reason by what matched
        if match_details.get("keywords_found"):
            match_reason = "keyword_match"
        elif match_details.get("amount_in_range"):
            match_reason = "amount_match"
        elif match_details.get("decision_type_matched"):
            match_reason = SUBSCRIPTION_TYPE_FILTER
        else:
            match_reason = SUBSCRIPTION_TYPE_FILTER
    else:
        # Fallback
        match_reason = SUBSCRIPTION_TYPE_FILTER

    return match_reason, match_details
