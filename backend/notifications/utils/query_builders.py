"""
Query builders for decision filtering.

This module contains the business logic for building Django Q objects
and filtering decisions based on subscription criteria.
"""

from core.models.decisions import Decision
from django.db import models
from notifications.constants import (
    KEYWORD_OPERATOR_OR,
    SUBSCRIPTION_TYPE_ENTITY,
    SUBSCRIPTION_TYPE_FILTER,
    SUBSCRIPTION_TYPE_ORGANIZATION,
    SUBSCRIPTION_TYPE_PERSON,
    SUBSCRIPTION_TYPE_RELATIONSHIP,
    SUBSCRIPTION_TYPE_SIGNER,
)


def build_keyword_q_filter(keyword, field_names=None):
    """
    Build a Q filter for keyword matching that handles Greek word inflections.

    For Greek (and other inflected languages), we need to match word stems
    since the same word can have different endings based on grammatical case.

    Examples:
        - διαγωνισμός (nominative) should match διαγωνισμού (genitive)
        - σύμβαση should match Σύμβαση (case-insensitive)

    Strategy:
        1. First try exact substring match (handles most cases)
        2. For longer keywords (>5 chars), also match word stems by removing
           last 1-2 characters to handle case endings

    Args:
        keyword: The keyword to match
        field_names: List of field names to search in (default: ['subject', 'text_extraction__raw_text'])

    Returns:
        Q object with the appropriate filter conditions
    """
    if field_names is None:
        field_names = ["subject", "text_extraction__raw_text"]

    q_filter = models.Q()

    for field_name in field_names:
        # Always include exact substring match (case-insensitive)
        q_filter |= models.Q(**{f"{field_name}__icontains": keyword})

        # For longer keywords, also try stem matching to handle inflections
        # This is especially important for Greek where word endings change based on case
        if len(keyword) > 5:
            # Create stems by removing last 1-2 characters
            # This handles most Greek case endings (ός/ού/ό, ση/σης/ση, ια/ιας, etc.)
            stem_variants = []

            # Try removing last 2 chars (handles ός->ού/ό, ση->σης, ια->ιας, etc.)
            if len(keyword) > 6:
                stem = keyword[:-2]
                if len(stem) >= 4:  # Minimum stem length to avoid false positives
                    stem_variants.append(stem)

            # Try removing last 1 char (handles η->ης, ο->ου, etc.)
            if len(keyword) > 5:
                stem = keyword[:-1]
                if len(stem) >= 4:
                    stem_variants.append(stem)

            # Add stem variants as case-insensitive substring matches
            # Don't use word boundaries as they don't work reliably with Unicode
            for stem in stem_variants:
                q_filter |= models.Q(**{f"{field_name}__icontains": stem})

    return q_filter


def find_matching_decisions(subscription, check_since):
    """
    Find decisions that match the subscription criteria since the last check.

    This function applies subscription type filters (organization, entity, etc.)
    and then applies optional filters (keywords, amounts, decision types).

    Args:
        subscription: NotificationSubscription instance
        check_since: datetime - only check decisions published after this time

    Returns:
        QuerySet of matching Decision objects
    """
    queryset = Decision.objects.filter(publish_timestamp__gte=check_since)

    # Apply subscription type filters
    subscription_type = subscription.subscription_type

    if subscription_type == SUBSCRIPTION_TYPE_ORGANIZATION:
        queryset = queryset.filter(organization=subscription.organization)

    elif subscription_type == SUBSCRIPTION_TYPE_ENTITY:
        # Check if entity appears in any decision through entity_relationships
        entity_afm = subscription.entity.afm
        queryset = queryset.filter(entity_relationships__entity__afm=entity_afm)

    elif subscription_type == SUBSCRIPTION_TYPE_RELATIONSHIP:
        # Check for relationship between org and entity
        entity_afm = subscription.relationship_entity.afm
        queryset = queryset.filter(
            organization=subscription.relationship_org,
            entity_relationships__entity__afm=entity_afm,
        )

    elif subscription_type == SUBSCRIPTION_TYPE_PERSON:
        # Find companies where this person is associated
        from core.models.companies import CompanyPerson

        # Get AFMs of companies where this person appears
        company_afms = (
            CompanyPerson.objects.filter(
                person_name__icontains=subscription.person_name
            )
            .values_list("company__afm", flat=True)
            .distinct()
        )

        # Find decisions involving entities with those AFMs
        queryset = queryset.filter(entity_relationships__entity__afm__in=company_afms)

    elif subscription_type == SUBSCRIPTION_TYPE_SIGNER:
        # Find decisions signed by this person
        queryset = _apply_signer_filter(queryset, subscription.signer_name)

    elif subscription_type == SUBSCRIPTION_TYPE_FILTER:
        # Filter-only subscription - no target restrictions
        # queryset already filtered by publish_timestamp, will apply filters below
        pass

    # Apply optional filters (keywords, amounts, decision types, signer)
    # These apply to ALL subscription types

    # Signer filter - can be used with any subscription type
    # (e.g., org + signer means "decisions from this org signed by this person")
    if subscription.signer_name and subscription_type != SUBSCRIPTION_TYPE_SIGNER:
        queryset = _apply_signer_filter(queryset, subscription.signer_name)

    # Keyword filter
    if subscription.keywords:
        queryset = _apply_keyword_filter(
            queryset, subscription.keywords, subscription.keyword_match_operator
        )

    # Amount filters
    if subscription.amount_min is not None or subscription.amount_max is not None:
        if subscription.amount_min:
            queryset = queryset.filter(amount__gte=subscription.amount_min)
        if subscription.amount_max:
            queryset = queryset.filter(amount__lte=subscription.amount_max)

    # Decision type filter
    if subscription.decision_types:
        queryset = queryset.filter(decision_type_id__in=subscription.decision_types)

    return queryset.distinct()


def _apply_signer_filter(queryset, signer_name):
    """
    Apply signer name filter to a queryset.

    Handles multi-part names by trying different combinations.

    Args:
        queryset: Decision queryset to filter
        signer_name: The name to search for

    Returns:
        Filtered queryset
    """
    signer_name_parts = signer_name.split()

    if len(signer_name_parts) >= 2:
        # Try to match by building full name from first_name and last_name
        signer_query = models.Q()

        # Try different combinations in case name is in different order
        for i in range(len(signer_name_parts)):
            for j in range(i + 1, len(signer_name_parts) + 1):
                name_part = " ".join(signer_name_parts[i:j])
                signer_query |= models.Q(signers__first_name__icontains=name_part)
                signer_query |= models.Q(signers__last_name__icontains=name_part)

        queryset = queryset.filter(signer_query)
    else:
        # Single name part - search in both first and last name
        queryset = queryset.filter(
            models.Q(signers__first_name__icontains=signer_name)
            | models.Q(signers__last_name__icontains=signer_name)
        )

    return queryset


def _apply_keyword_filter(queryset, keywords, operator):
    """
    Apply keyword filter to a queryset.

    Supports both AND and OR operators with stem matching for Greek inflections.
    Searches in both decision subject and extracted document text.

    Args:
        queryset: Decision queryset to filter
        keywords: List of keywords to search for
        operator: 'AND' or 'OR' - how to combine keywords

    Returns:
        Filtered queryset
    """
    # Search in both decision subject and extracted document text
    search_fields = ["subject", "text_extraction__raw_text"]

    if operator == KEYWORD_OPERATOR_OR:
        # OR logic: any keyword matches (at least one keyword must be present)
        keyword_filter = models.Q()
        for keyword in keywords:
            keyword_filter |= build_keyword_q_filter(keyword, search_fields)
        queryset = queryset.filter(keyword_filter)
    else:  # AND logic (default)
        # AND logic: all keywords must match (every keyword must be present)
        for keyword in keywords:
            queryset = queryset.filter(build_keyword_q_filter(keyword, search_fields))

    return queryset
