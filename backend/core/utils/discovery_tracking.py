"""
Utilities for tracking how decisions were discovered from different sources.

This module provides helpers to tag decisions with their discovery source metadata,
allowing analysis of which search strategies find which decisions.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger


class DiscoverySource:
    """Constants for discovery source types"""

    DEFAULT_SEARCH = "default_search"
    ORG_SPECIFIC = "org_specific"
    UNIT_SPECIFIC = "unit_specific"
    SIGNER_SPECIFIC = "signer_specific"
    MANUAL_IMPORT = "manual_import"
    BACKFILL = "backfill"


def create_discovery_metadata(
    source_type: str,
    search_params: Optional[Dict[str, Any]] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a standardized discovery source metadata object.

    Args:
        source_type: Type of search that found this decision (use DiscoverySource constants)
        search_params: The actual search parameters used
        notes: Optional notes about this discovery

    Returns:
        Dictionary with discovery metadata

    Example:
        >>> create_discovery_metadata(
        ...     DiscoverySource.ORG_SPECIFIC,
        ...     search_params={"org": "6115;dimosthivas", "from_date": "2023-01-01"},
        ...     notes="Targeted organization sweep"
        ... )
    """
    return {
        "source_type": source_type,
        "discovered_at": datetime.utcnow().isoformat(),
        "search_params": search_params or {},
        "notes": notes,
    }


def add_discovery_source_to_decision(
    decision,
    source_type: str,
    search_params: Optional[Dict[str, Any]] = None,
    notes: Optional[str] = None,
    save: bool = True,
) -> None:
    """
    Add a discovery source to a decision's discovery tracking.

    This appends to the list of sources (allowing multiple discoveries)
    and sets first_discovery_source if this is the first one.

    Args:
        decision: Decision model instance
        source_type: Type of search (use DiscoverySource constants)
        search_params: Search parameters used
        notes: Optional notes
        save: Whether to save the decision after updating

    Example:
        >>> from core.models.decisions import Decision
        >>> decision = Decision.objects.get(ada="ΨΧΩΙ123-ΩΛΨ")
        >>> add_discovery_source_to_decision(
        ...     decision,
        ...     DiscoverySource.ORG_SPECIFIC,
        ...     search_params={"org": "6115;dimosthivas"},
        ...     notes="Found in org-specific sweep"
        ... )
    """
    # Create metadata
    metadata = create_discovery_metadata(source_type, search_params, notes)

    # Initialize discovery_sources if None
    if decision.discovery_sources is None:
        decision.discovery_sources = []

    # Check if we already have this source type (prevent duplicates)
    existing_types = [s.get("source_type") for s in decision.discovery_sources]
    if source_type in existing_types:
        logger.debug(
            f"Decision {decision.ada} already has source type {source_type}, skipping"
        )
        return

    # Add to list
    decision.discovery_sources.append(metadata)

    # Set first discovery source if not already set
    if not decision.first_discovery_source:
        decision.first_discovery_source = source_type
        logger.debug(f"Decision {decision.ada} first discovered via: {source_type}")

    if save:
        decision.save(update_fields=["discovery_sources", "first_discovery_source"])


def tag_decisions_batch(
    decisions: List,
    source_type: str,
    search_params: Optional[Dict[str, Any]] = None,
    notes: Optional[str] = None,
) -> Dict[str, int]:
    """
    Tag a batch of decisions with the same discovery source.

    Args:
        decisions: List of Decision model instances
        source_type: Type of search
        search_params: Search parameters
        notes: Optional notes

    Returns:
        Stats dictionary with counts
    """
    stats = {"tagged": 0, "already_tagged": 0, "errors": 0}

    metadata = create_discovery_metadata(source_type, search_params, notes)

    for decision in decisions:
        try:
            # Initialize if needed
            if decision.discovery_sources is None:
                decision.discovery_sources = []

            # Check for duplicates
            existing_types = [s.get("source_type") for s in decision.discovery_sources]
            if source_type in existing_types:
                stats["already_tagged"] += 1
                continue

            # Add source
            decision.discovery_sources.append(metadata)

            # Set first discovery if needed
            if not decision.first_discovery_source:
                decision.first_discovery_source = source_type

            stats["tagged"] += 1

        except Exception as e:
            logger.error(f"Error tagging decision {decision.ada}: {e}")
            stats["errors"] += 1

    # Bulk update
    if stats["tagged"] > 0:
        from core.models.decisions import Decision

        Decision.objects.bulk_update(
            [d for d in decisions if d.pk],
            ["discovery_sources", "first_discovery_source"],
            batch_size=100,
        )

        logger.debug(f"Tagged {stats['tagged']} decisions with source: {source_type}")

    return stats


def get_decisions_by_discovery_source(source_type: str, limit: Optional[int] = None):
    """
    Query decisions discovered by a specific source type.

    Args:
        source_type: The source type to filter by
        limit: Optional limit on results

    Returns:
        QuerySet of decisions

    Example:
        >>> # Find all decisions discovered via default search
        >>> from core.utils.discovery_tracking import get_decisions_by_discovery_source, DiscoverySource
        >>> default_decisions = get_decisions_by_discovery_source(DiscoverySource.DEFAULT_SEARCH)
        >>> print(f"Found {default_decisions.count()} decisions from default search")
    """
    from core.models.decisions import Decision

    queryset = Decision.objects.filter(
        discovery_sources__contains=[{"source_type": source_type}]
    )

    if limit:
        queryset = queryset[:limit]

    return queryset


def analyze_discovery_overlap():
    """
    Analyze which decisions appear in multiple sources.

    Returns:
        Dictionary with overlap statistics
    """
    from core.models.decisions import Decision
    from django.db.models import Count
    from django.db.models.functions import JSONLength

    # Get decisions with multiple sources
    multi_source = Decision.objects.annotate(
        source_count=JSONLength("discovery_sources")
    ).filter(source_count__gt=1)

    # Count by first discovery source
    first_source_counts = (
        Decision.objects.values("first_discovery_source")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    # Decisions only in default vs only in org-specific
    only_default = (
        Decision.objects.filter(first_discovery_source=DiscoverySource.DEFAULT_SEARCH)
        .annotate(source_count=JSONLength("discovery_sources"))
        .filter(source_count=1)
    )

    only_org_specific = (
        Decision.objects.filter(first_discovery_source=DiscoverySource.ORG_SPECIFIC)
        .annotate(source_count=JSONLength("discovery_sources"))
        .filter(source_count=1)
    )

    return {
        "total_decisions": Decision.objects.count(),
        "multi_source_count": multi_source.count(),
        "multi_source_percentage": (
            (multi_source.count() / Decision.objects.count() * 100)
            if Decision.objects.count() > 0
            else 0
        ),
        "first_source_breakdown": list(first_source_counts),
        "only_default_count": only_default.count(),
        "only_org_specific_count": only_org_specific.count(),
    }
