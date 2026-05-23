"""
Search History Service

Redis-based service for tracking and retrieving personal search history.
Provides fast access to recent searches for both authenticated users and anonymous IPs.

Benefits over DB-only approach:
- Ultra-fast retrieval for autocomplete/suggestions
- Automatic expiration (90 days)
- Sorted list with timestamps
- Deduplication of searches
- Privacy-friendly (can be cleared on demand)

Architecture:
- Redis Sorted Set per user/IP: stores query + metadata as JSON
- Score = timestamp (for chronological ordering)
- Automatically expires after 90 days
- Complements SearchAnalytics model (which persists all searches)
"""

import json
import time
from typing import Any, Dict, List, Optional

from api.redis_keys import (
    SEARCH_HISTORY_EXPIRE,
    get_ip_search_history_key,
    get_user_search_history_key,
)
from core.services.feature_flag_service import feature_flags
from django_redis import get_redis_connection
from loguru import logger


class SearchHistoryService:
    """
    Manages personal search history using Redis Sorted Sets.

    Data structure:
    - Key: search_history:user:<user_id> or search_history:ip:<ip>
    - Type: Sorted Set (ZADD, ZRANGE, ZREVRANGE)
    - Member: JSON string with query and metadata
    - Score: Unix timestamp

    Example usage:
        service = SearchHistoryService()

        # Track a search
        service.track_search(
            query="Δημοτικό Συμβούλιο",
            user_id=123,
            results_count=45,
            search_types=['organization', 'signer']
        )

        # Get recent searches
        history = service.get_user_history(user_id=123, limit=10)

        # Get unique queries for autocomplete
        recent_queries = service.get_recent_queries(user_id=123, limit=5)
    """

    def __init__(self):
        """Initialize Redis connection using Django's connection pool"""
        # Use default cache connection (DB 1)
        self.redis_client = get_redis_connection("default")
        logger.debug("SearchHistoryService initialized with Redis connection pool")

    def track_search(
        self,
        query: str,
        user_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        results_count: Optional[int] = None,
        search_types: Optional[List[str]] = None,
        entity_type: Optional[str] = None,
        filters_applied: Optional[Dict[str, Any]] = None,
        is_selection: bool = False,
        selected_item_id: Optional[str] = None,
        selected_item_name: Optional[str] = None,
        selected_item_url: Optional[str] = None,
    ) -> bool:
        """
        Track a search in Redis history.

        Args:
            query: The search query string
            user_id: User ID (for authenticated users)
            ip_address: IP address (for anonymous users or as fallback)
            results_count: Number of results returned
            search_types: Types of entities searched (e.g., ['organization', 'signer'])
            entity_type: Primary entity type searched
            filters_applied: Any filters applied to the search
            is_selection: Whether this is a user selection/click (vs just typing)
            selected_item_id: ID of the selected item (for selections)
            selected_item_name: Name/title of the selected item (for selections)
            selected_item_url: URL path of the selected item (for selections)

        Returns:
            True if successfully tracked, False otherwise
        """
        # Check recording mode from feature flag
        recording_mode = feature_flags.get_value(
            "SEARCH_HISTORY_RECORDING_MODE", default="filtered"
        )

        # Handle 'none' mode - don't record anything
        if recording_mode == "none":
            logger.debug("Search history recording disabled (mode=none)")
            return False

        # Handle 'selections_only' mode - only record when user clicks/selects
        if recording_mode == "selections_only" and not is_selection:
            logger.debug(
                "Skipping search recording - selections_only mode requires is_selection=True"
            )
            return False

        if not query or not query.strip():
            return False

        normalized_query = query.strip().lower()
        timestamp = time.time()

        # Build metadata
        metadata = {
            "query": query.strip(),  # Keep original casing
            "normalized_query": normalized_query,
            "timestamp": timestamp,
            "is_selection": is_selection,  # Flag to distinguish clicks from typing
        }

        if results_count is not None:
            metadata["results_count"] = results_count
        if search_types:
            metadata["search_types"] = search_types
        if entity_type:
            metadata["entity_type"] = entity_type
        if filters_applied:
            metadata["filters_applied"] = filters_applied

        # Add selection-specific metadata
        if is_selection:
            if selected_item_id:
                metadata["selected_item_id"] = selected_item_id
            if selected_item_name:
                metadata["selected_item_name"] = selected_item_name
            if selected_item_url:
                metadata["selected_item_url"] = selected_item_url

        success = False

        # Get recording mode to pass to _add_to_history
        recording_mode = feature_flags.get_value(
            "SEARCH_HISTORY_RECORDING_MODE", default="filtered"
        )

        # Track for authenticated user
        if user_id:
            success = (
                self._add_to_history(
                    key=get_user_search_history_key(user_id),
                    query=normalized_query,
                    metadata=metadata,
                    timestamp=timestamp,
                    recording_mode=recording_mode,
                )
                or success
            )

        # Track for IP (always track, useful for anonymous users)
        if ip_address:
            success = (
                self._add_to_history(
                    key=get_ip_search_history_key(ip_address),
                    query=normalized_query,
                    metadata=metadata,
                    timestamp=timestamp,
                    recording_mode=recording_mode,
                )
                or success
            )

        return success

    def _add_to_history(
        self,
        key: str,
        query: str,
        metadata: Dict[str, Any],
        timestamp: float,
        recording_mode: str = "filtered",
    ) -> bool:
        """
        Add a search to a Redis sorted set with configurable filtering.

        Filtering rules (based on recording_mode):
        - 'filtered' (default): Don't track queries < 2 characters, skip duplicates within 5 seconds
        - 'all': Record everything, no filtering
        """
        try:
            # Apply filters based on recording_mode
            if recording_mode == "filtered":
                # Filter 1: Ignore very short queries (typing noise)
                if len(query.strip()) < 2:
                    logger.debug(f"Skipping short query '{query}' (< 2 chars)")
                    return False

                # Filter 2: Check for recent duplicate (same query in last 5 seconds)
                # Get the most recent entry for this normalized query
                recent_entries = self.redis_client.zrevrangebyscore(
                    key, "+inf", timestamp - 5, start=0, num=10  # Last 5 seconds
                )

                for entry_bytes in recent_entries:
                    try:
                        entry_data = json.loads(entry_bytes.decode("utf-8"))
                        if entry_data.get("normalized_query") == query:
                            # Same query was searched within last 5 seconds - skip
                            logger.debug(
                                f"Skipping duplicate query '{query}' "
                                f"(searched {timestamp - entry_data.get('timestamp', 0):.1f}s ago)"
                            )
                            return False
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
            # For 'all' mode: no filtering, record everything

            # Serialize metadata
            member = json.dumps(metadata)

            # Add to sorted set (score = timestamp)
            self.redis_client.zadd(key, {member: timestamp})

            # Set expiration on the key
            self.redis_client.expire(key, SEARCH_HISTORY_EXPIRE)

            # Trim to keep only last 100 searches per user/IP
            self.redis_client.zremrangebyrank(key, 0, -101)

            logger.debug(f"[OK] Tracked search '{query}' in {key}")
            return True

        except Exception as e:
            logger.error(f"Failed to track search in {key}: {e}")
            return False

    def get_user_history(
        self, user_id: int, limit: int = 20, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Get a user's search history (most recent first).

        Args:
            user_id: User ID
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            List of search metadata dicts, sorted by timestamp (newest first)
        """
        key = get_user_search_history_key(user_id)
        return self._get_history(key, limit, offset)

    def get_ip_history(
        self, ip_address: str, limit: int = 20, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Get an IP's search history (most recent first).

        Args:
            ip_address: IP address
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            List of search metadata dicts, sorted by timestamp (newest first)
        """
        key = get_ip_search_history_key(ip_address)
        return self._get_history(key, limit, offset)

    def _get_history(self, key: str, limit: int, offset: int) -> List[Dict[str, Any]]:
        """
        Retrieve history from a Redis sorted set.

        Returns most recent searches first (reverse chronological order).
        """
        try:
            # ZREVRANGE: get members in reverse order (highest score first)
            # withscores=True returns (member, score) tuples
            start = offset
            end = offset + limit - 1

            members = self.redis_client.zrevrange(key, start, end, withscores=True)

            history = []
            for member_bytes, score in members:
                try:
                    metadata = json.loads(member_bytes.decode("utf-8"))
                    # Score is the timestamp
                    if "timestamp" not in metadata:
                        metadata["timestamp"] = score
                    history.append(metadata)
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    logger.warning(f"Failed to decode history entry: {e}")
                    continue

            return history

        except Exception as e:
            logger.error(f"Failed to retrieve history from {key}: {e}")
            return []

    def get_recent_queries(
        self,
        user_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        limit: int = 10,
        unique: bool = True,
    ) -> List[str]:
        """
        Get recent query strings (for autocomplete suggestions).

        Args:
            user_id: User ID (optional)
            ip_address: IP address (optional)
            limit: Maximum number of queries
            unique: If True, deduplicate queries (default: True)

        Returns:
            List of query strings (most recent first)
        """
        history = []

        if user_id:
            history.extend(self.get_user_history(user_id, limit=limit * 2))

        if ip_address:
            history.extend(self.get_ip_history(ip_address, limit=limit * 2))

        # Extract queries
        queries = [item.get("query", "") for item in history if item.get("query")]

        # Deduplicate while preserving order
        if unique:
            seen = set()
            unique_queries = []
            for q in queries:
                normalized = q.lower()
                if normalized not in seen:
                    seen.add(normalized)
                    unique_queries.append(q)
            queries = unique_queries

        return queries[:limit]

    def get_recently_visited(
        self,
        user_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        limit: int = 10,
        unique: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Get recently visited items (items that were actually clicked/selected).

        This filters the search history to only include entries with is_selection=True,
        providing a clean "Recently Visited" list for users.

        Args:
            user_id: User ID (optional)
            ip_address: IP address (optional)
            limit: Maximum number of items
            unique: If True, deduplicate by selected_item_id (default: True)

        Returns:
            List of visited item metadata dicts (most recent first)
        """
        history = []

        # Fetch more items than needed to ensure we have enough after filtering
        fetch_limit = limit * 5

        if user_id:
            history.extend(self.get_user_history(user_id, limit=fetch_limit))

        if ip_address:
            history.extend(self.get_ip_history(ip_address, limit=fetch_limit))

        # Sort by timestamp (most recent first) since we may have merged user + IP history
        history.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

        # Filter to only selections (clicks)
        visited = [
            item
            for item in history
            if item.get("is_selection", False) and item.get("selected_item_id")
        ]

        # Deduplicate while preserving order (most recent occurrence wins)
        if unique:
            seen = set()
            unique_visited = []
            for item in visited:
                # Use entity_type + selected_item_id as unique key
                item_key = (
                    f"{item.get('entity_type', '')}:{item.get('selected_item_id', '')}"
                )
                if item_key not in seen:
                    seen.add(item_key)
                    unique_visited.append(item)
            visited = unique_visited

        # Enrich items with entity details if missing
        enriched_visited = self._enrich_visited_items(visited)

        return enriched_visited[:limit]

    def _enrich_visited_items(
        self, visited: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Enrich visited items with entity details (name, URL) if missing.

        This handles cases where:
        - Data was tracked before name/URL fields were added
        - The frontend didn't send name/URL when tracking
        - Name/URL were empty strings

        For each item, if selected_item_name or selected_item_url is missing,
        we look up the entity from the database and populate these fields.

        Args:
            visited: List of visited item dicts

        Returns:
            List of enriched visited item dicts
        """
        from core.models import Organization, Signer, Unit

        enriched = []

        for item in visited:
            # Check if enrichment is needed
            has_name = bool(item.get("selected_item_name"))
            has_url = bool(item.get("selected_item_url"))

            if has_name and has_url:
                # Already has all needed fields
                enriched.append(item)
                continue

            # Need to enrich - look up entity
            entity_type = item.get("entity_type")
            entity_id = item.get("selected_item_id")

            if not entity_type or not entity_id:
                # Can't enrich without these
                enriched.append(item)
                continue

            try:
                # Look up entity based on type
                entity_name = None
                entity_url = None

                if entity_type == "organization":
                    try:
                        org = Organization.objects.get(uid=entity_id)
                        entity_name = org.label
                        entity_url = f"/entity/organization/{entity_id}"
                    except Organization.DoesNotExist:
                        logger.warning(
                            f"Organization {entity_id} not found for enrichment"
                        )

                elif entity_type == "unit":
                    try:
                        unit = Unit.objects.get(uid=entity_id)
                        entity_name = unit.label
                        entity_url = f"/entity/unit/{entity_id}"
                    except Unit.DoesNotExist:
                        logger.warning(f"Unit {entity_id} not found for enrichment")

                elif entity_type == "signer":
                    try:
                        signer = Signer.objects.get(uid=entity_id)
                        entity_name = f"{signer.first_name} {signer.last_name}"
                        entity_url = f"/entity/signer/{entity_id}"
                    except Signer.DoesNotExist:
                        logger.warning(f"Signer {entity_id} not found for enrichment")

                # Add enriched fields if found
                if entity_name and not has_name:
                    item["selected_item_name"] = entity_name
                if entity_url and not has_url:
                    item["selected_item_url"] = entity_url

                enriched.append(item)

            except Exception as e:
                logger.error(f"Error enriching item {entity_type}:{entity_id}: {e}")
                # Keep item even if enrichment fails
                enriched.append(item)

        return enriched

    def delete_single_item(
        self,
        item_timestamp: float,
        user_id: Optional[int] = None,
        ip_address: Optional[str] = None,
    ) -> bool:
        """
        Delete a single item from search history by timestamp.

        Args:
            item_timestamp: Unix timestamp of the item to delete
            user_id: User ID (for authenticated users)
            ip_address: IP address (for anonymous users or as fallback)

        Returns:
            True if successfully deleted, False otherwise
        """
        try:
            deleted = False

            # Delete from user history
            if user_id:
                key = get_user_search_history_key(user_id)
                # Get all items with this timestamp
                members = self.redis_client.zrangebyscore(
                    key, item_timestamp, item_timestamp
                )
                for member_bytes in members:
                    try:
                        member = member_bytes.decode("utf-8")
                        # Remove this specific member
                        self.redis_client.zrem(key, member)
                        deleted = True
                        logger.debug(
                            f"Deleted item from user {user_id} history at timestamp {item_timestamp}"
                        )
                    except (UnicodeDecodeError, Exception) as e:
                        logger.warning(f"Failed to delete item from user history: {e}")
                        continue

            # Delete from IP history
            if ip_address:
                key = get_ip_search_history_key(ip_address)
                # Get all items with this timestamp
                members = self.redis_client.zrangebyscore(
                    key, item_timestamp, item_timestamp
                )
                for member_bytes in members:
                    try:
                        member = member_bytes.decode("utf-8")
                        # Remove this specific member
                        self.redis_client.zrem(key, member)
                        deleted = True
                        logger.debug(
                            f"Deleted item from IP {ip_address} history at timestamp {item_timestamp}"
                        )
                    except (UnicodeDecodeError, Exception) as e:
                        logger.warning(f"Failed to delete item from IP history: {e}")
                        continue

            return deleted

        except Exception as e:
            logger.error(f"Failed to delete single history item: {e}")
            return False

    def clear_user_history(self, user_id: int) -> bool:
        """Clear all search history for a user (privacy feature)."""
        key = get_user_search_history_key(user_id)
        try:
            self.redis_client.delete(key)
            logger.info(f"Cleared search history for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to clear history for user {user_id}: {e}")
            return False

    def clear_ip_history(self, ip_address: str) -> bool:
        """Clear all search history for an IP."""
        key = get_ip_search_history_key(ip_address)
        try:
            self.redis_client.delete(key)
            logger.info(f"Cleared search history for IP {ip_address}")
            return True
        except Exception as e:
            logger.error(f"Failed to clear history for IP {ip_address}: {e}")
            return False

    def get_history_stats(
        self, user_id: Optional[int] = None, ip_address: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get statistics about search history.

        Returns:
            Dict with total searches, date range, top search types, etc.
        """
        history = []

        if user_id:
            history.extend(self.get_user_history(user_id, limit=100))

        if ip_address:
            history.extend(self.get_ip_history(ip_address, limit=100))

        if not history:
            return {
                "total_searches": 0,
                "unique_queries": 0,
                "date_range": None,
                "top_search_types": [],
            }

        # Calculate stats
        from collections import Counter

        unique_queries = set(item.get("normalized_query", "") for item in history)
        timestamps = [
            item.get("timestamp", 0) for item in history if item.get("timestamp")
        ]

        search_types_counter = Counter()
        for item in history:
            types = item.get("search_types", [])
            if isinstance(types, list):
                search_types_counter.update(types)

        return {
            "total_searches": len(history),
            "unique_queries": len(unique_queries),
            "date_range": {
                "earliest": min(timestamps) if timestamps else None,
                "latest": max(timestamps) if timestamps else None,
            },
            "top_search_types": search_types_counter.most_common(5),
        }
