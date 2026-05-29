"""
Decision Fetch and Reconciliation Service

This service centralizes all the logic for:
1. Fetching decisions from Diavgeia API with pagination
2. Respecting feature flags (e.g., FILTER_DECISION_TYPES)
3. Reconciling counts with official Diavgeia API
4. Providing a single source of truth for fetch parameters

This eliminates duplication across:
- tasks_decisions_import.py
- decision_ingestion_service.py
- tasks_org_decisions.py
- complete_partial_import.py
"""

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import requests
from core.constants.decision_import_constants import (
    DIAVGEIA_OFFICIAL_COUNTS_URL,
    DiavgeiaSearchFields,
)
from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from diavgeia_api.models.decisions import Decision
from diavgeia_api.models.search import SearchResponse
from loguru import logger


class DecisionFetchReconcileService:
    """
    Centralized service for fetching and reconciling decisions from Diavgeia API.
    
    This service ensures consistency across all parts of the codebase that fetch
    decisions, and provides built-in reconciliation with official API counts.
    """

    def __init__(
        self,
        fetcher: Optional[DiavgeiaFetcher] = None,
        use_submission_date: bool = True,
    ):
        """
        Initialize the fetch and reconcile service.
        
        Args:
            fetcher: Optional DiavgeiaFetcher instance (creates new one if not provided)
            use_submission_date: If True, use from_date/to_date (submission date).
                                If False, use from_issue_date/to_issue_date (issue date).
                                Default is True to match official API counts.
        """
        self.fetcher = fetcher or DiavgeiaFetcher()
        self.use_submission_date = use_submission_date

    def _get_date_fields(self) -> tuple[str, str]:
        """
        Get the appropriate date field names based on configuration.
        
        Returns:
            Tuple of (from_field, to_field) field names
        """
        if self.use_submission_date:
            return DiavgeiaSearchFields.FROM_DATE, DiavgeiaSearchFields.TO_DATE
        else:
            return (
                DiavgeiaSearchFields.FROM_ISSUE_DATE,
                DiavgeiaSearchFields.TO_ISSUE_DATE,
            )

    def build_search_params(
        self,
        target_date: date,
        additional_params: Optional[Dict[str, Any]] = None,
        include_feature_flags: bool = True,
    ) -> Dict[str, Any]:
        """
        Build search parameters for a single day with all proper settings.
        
        This method:
        - Uses the correct date field names (submission vs issue date)
        - Applies feature flag filtering (FILTER_DECISION_TYPES)
        - Sets proper pagination defaults
        - Merges with any additional parameters
        
        Args:
            target_date: Date to fetch decisions for
            additional_params: Optional dict of additional search parameters
                              (e.g., org, unit, signer filters)
            include_feature_flags: Whether to apply feature flag filtering
        
        Returns:
            Complete search parameters dict ready for DiavgeiaFetcher
        """
        from_field, to_field = self._get_date_fields()

        # Base parameters with date range for a single day
        search_params = {
            from_field: target_date.isoformat(),
            to_field: (target_date + timedelta(days=1)).isoformat(),
            DiavgeiaSearchFields.PAGE: DiavgeiaSearchFields.DEFAULT_PAGE,
            DiavgeiaSearchFields.SIZE: DiavgeiaSearchFields.DEFAULT_PAGE_SIZE,
        }

        # Apply feature flag filtering for decision types
        if include_feature_flags:
            from core.services.feature_flag_service import feature_flags

            filtered_types = feature_flags.get_value("FILTER_DECISION_TYPES")
            if (
                filtered_types
                and isinstance(filtered_types, list)
                and len(filtered_types) > 0
            ):
                # Join types with semicolon (API supports this for multiple types)
                search_params[DiavgeiaSearchFields.TYPE] = ";".join(filtered_types)
                logger.info(
                    f"Applied feature flag FILTER_DECISION_TYPES: {filtered_types} "
                    f"(joined as: {search_params[DiavgeiaSearchFields.TYPE]})"
                )

        # Merge with additional parameters (e.g., org, unit, signer)
        if additional_params:
            # Filter out internal parameters that aren't part of the API
            internal_params = {"force", "chunk_size", "job_id", "distributed"}
            api_params = {
                k: v for k, v in additional_params.items() if k not in internal_params
            }
            search_params.update(api_params)

            # Log any entity filters
            entity_filters = [
                f"{key}={val}"
                for key in [
                    DiavgeiaSearchFields.ORG,
                    DiavgeiaSearchFields.UNIT,
                    DiavgeiaSearchFields.SIGNER,
                ]
                if (val := api_params.get(key))
            ]
            if entity_filters:
                logger.info(f"Entity filters applied: {', '.join(entity_filters)}")

        return search_params

    def fetch_decisions_for_day(
        self,
        target_date: date,
        additional_params: Optional[Dict[str, Any]] = None,
        include_feature_flags: bool = True,
    ) -> tuple[List[Decision], int]:
        """
        Fetch ALL decisions for a single day with automatic pagination.
        
        This is the main method that should be used across the codebase for
        fetching decisions for a day. It handles:
        - Proper date field usage
        - Feature flag filtering
        - Automatic pagination
        - Error handling
        
        Args:
            target_date: Date to fetch decisions for
            additional_params: Optional additional search parameters
            include_feature_flags: Whether to apply feature flag filtering
        
        Returns:
            Tuple of (decisions_list, total_count)
            - decisions_list: List of all fetched Decision DTOs
            - total_count: Total count from API (may differ from len(decisions_list)
                          if there are duplicates or API inconsistencies)
        """
        search_params = self.build_search_params(
            target_date=target_date,
            additional_params=additional_params,
            include_feature_flags=include_feature_flags,
        )

        all_decisions = []
        page = 0
        total_pages = 1
        api_total_count = 0

        logger.info(
            f"Fetching decisions for {target_date} using "
            f"{'submission date' if self.use_submission_date else 'issue date'}"
        )

        while page < total_pages:
            search_params[DiavgeiaSearchFields.PAGE] = page
            response: Optional[SearchResponse] = self.fetcher.fetch_decisions(
                **search_params
            )

            if response and response.info:
                # On first page, calculate total pages
                if page == 0 and response.info.total > 0:
                    api_total_count = response.info.total
                    page_size = search_params.get(
                        DiavgeiaSearchFields.SIZE,
                        DiavgeiaSearchFields.DEFAULT_PAGE_SIZE,
                    )
                    total_pages = (api_total_count + page_size - 1) // page_size
                    logger.info(
                        f"Found {api_total_count} decisions, {total_pages} pages for {target_date}"
                    )

                all_decisions.extend(response.decisions)
                page += 1

                # Check if we've reached the last page
                if response.info.actualSize < search_params.get(
                    DiavgeiaSearchFields.SIZE, DiavgeiaSearchFields.DEFAULT_PAGE_SIZE
                ):
                    logger.debug(
                        f"Reached last page (actualSize {response.info.actualSize})"
                    )
                    break
            else:
                logger.warning(f"No response for page {page}")
                break

        logger.success(
            f"Fetched {len(all_decisions)} decisions for {target_date} "
            f"(API reported {api_total_count} total)"
        )

        return all_decisions, api_total_count

    def get_official_count_for_date(
        self, target_date: date, timeout: int = 30
    ) -> Optional[int]:
        """
        Get the official decision count from Diavgeia API for a specific date.
        
        This queries the official endpoint that provides daily counts for the last month.
        Note: This endpoint uses submission/upload date, not issue date.
        
        Args:
            target_date: Date to get count for
            timeout: Request timeout in seconds
        
        Returns:
            Official count if found, None otherwise
        """
        try:
            response = requests.get(DIAVGEIA_OFFICIAL_COUNTS_URL, timeout=timeout)
            response.raise_for_status()

            official_data = response.json()

            # Format date to match API format (ISO with timezone)
            target_timestamp = target_date.strftime("%Y-%m-%dT00:00:00Z")

            # Search for matching date in results
            for item in official_data.get("facetsResults", []):
                if item["label"] == target_timestamp:
                    return item["counter"]

            logger.warning(f"No official count found for {target_date}")
            return None

        except Exception as e:
            logger.error(f"Failed to get official count for {target_date}: {e}")
            return None

    @classmethod
    def get_all_official_daily_counts(cls, timeout: int = 30) -> List[Dict[str, Any]]:
        """
        Get all daily counts from the official Diavgeia API (last 30 days).
        
        This is useful for finding low-volume days for testing or analysis.
        
        Args:
            timeout: Request timeout in seconds
        
        Returns:
            List of dicts with 'date' and 'count' keys, sorted by date descending.
            Returns empty list on error.
            
        Example:
            [
                {"date": date(2026, 5, 1), "count": 313},
                {"date": date(2026, 4, 30), "count": 30473},
                ...
            ]
        """
        try:
            response = requests.get(DIAVGEIA_OFFICIAL_COUNTS_URL, timeout=timeout)
            response.raise_for_status()

            official_data = response.json()
            
            results = []
            for item in official_data.get("facetsResults", []):
                # Parse date from "2026-05-01T00:00:00Z" format
                date_str = item["label"]
                parsed_date = datetime.strptime(date_str, "%Y-%m-%dT00:00:00Z").date()
                
                results.append({
                    "date": parsed_date,
                    "count": item["counter"],
                })
            
            # Sort by date descending (most recent first)
            results.sort(key=lambda x: x["date"], reverse=True)
            
            return results

        except Exception as e:
            logger.error(f"Failed to get official daily counts: {e}")
            return []

    @classmethod
    def find_lowest_volume_date(
        cls,
        min_count: int = 100,
        max_count: int = 1000,
        exclude_weekends: bool = True,
        timeout: int = 30,
    ) -> Optional[date]:
        """
        Find the date with the lowest decision count from recent data.
        
        This is particularly useful for testing - we want a low-volume day to
        keep test execution fast, but not too low (which might indicate an anomaly).
        
        Args:
            min_count: Minimum acceptable count (avoid anomalies/holidays)
            max_count: Maximum acceptable count (want low volume)
            exclude_weekends: If True, skip Saturday/Sunday (often have lower counts)
            timeout: Request timeout in seconds
        
        Returns:
            Date with lowest count meeting criteria, or None if not found
            
        Example:
            # Find a good test date
            test_date = DecisionFetchReconcileService.find_lowest_volume_date()
            # Returns something like date(2026, 5, 1) with ~313 decisions
        """
        all_counts = cls.get_all_official_daily_counts(timeout=timeout)
        
        if not all_counts:
            logger.warning("No official counts available")
            return None
        
        # Filter by criteria
        candidates = []
        for item in all_counts:
            count = item["count"]
            day_date = item["date"]
            
            # Check count range
            if not (min_count <= count <= max_count):
                continue
            
            # Check if weekend
            if exclude_weekends and day_date.weekday() >= 5:  # 5=Saturday, 6=Sunday
                continue
            
            candidates.append(item)
        
        if not candidates:
            logger.warning(
                f"No dates found with count between {min_count} and {max_count}"
            )
            return None
        
        # Find lowest among candidates
        lowest = min(candidates, key=lambda x: x["count"])
        
        logger.info(
            f"Found lowest volume date: {lowest['date']} with {lowest['count']} decisions"
        )
        
        return lowest["date"]

    def reconcile_counts(
        self, 
        target_date: date, 
        our_count: int,
        api_reported_total: Optional[int] = None,
        filters_applied: bool = False,
    ) -> Dict[str, Any]:
        """
        Reconcile our fetched count with the official API count.
        
        This provides detailed three-way comparison:
        1. Official count (from daily stats endpoint) - only when no filters
        2. API reported total (from response.info.total during pagination)
        3. Actual fetched count (len(all_decisions))
        
        IMPORTANT: When filters are applied (FILTER_DECISION_TYPES, org, unit, signer),
        the official count represents ALL decisions, while our query is filtered.
        In this case, we skip official count comparison and only validate pagination.
        
        Args:
            target_date: Date that was fetched
            our_count: Number of decisions we actually fetched
            api_reported_total: Optional count from response.info.total (pagination info)
            filters_applied: If True, filters are active and official count comparison is skipped
        
        Returns:
            Dict with reconciliation results:
            {
                "date": "2026-05-01",
                "official_count": 313,  # None if filters_applied=True
                "api_reported_total": 313,
                "our_count": 313,
                "difference": 0,
                "percentage_diff": 0.0,
                "api_vs_official_diff": 0,
                "our_vs_api_diff": 0,
                "filters_applied": True,  # NEW: indicates if filters were active
                "status": "match"|"discrepancy"|"no_official_data"|"pagination_mismatch"|"filtered_query"
            }
        """
        # If filters are applied, skip official count check
        # (official count is for ALL decisions, while we're querying a filtered subset)
        if filters_applied:
            logger.info(
                f"Filters applied for {target_date}, skipping official count comparison "
                f"(official counts are for all decisions, not filtered subset)"
            )
            
            result = {
                "date": target_date.isoformat(),
                "official_count": None,
                "api_reported_total": api_reported_total,
                "our_count": our_count,
                "difference": None,
                "percentage_diff": None,
                "api_vs_official_diff": None,
                "our_vs_api_diff": None,
                "filters_applied": True,
                "status": "filtered_query",
            }
            
            # Still check pagination consistency
            if api_reported_total is not None:
                our_vs_api_diff = our_count - api_reported_total
                result["our_vs_api_diff"] = our_vs_api_diff
                
                if our_vs_api_diff == 0:
                    logger.success(
                        f"Pagination OK for filtered query on {target_date}: "
                        f"API_reported={api_reported_total}, Our={our_count}"
                    )
                else:
                    result["status"] = "filtered_query_pagination_mismatch"
                    logger.warning(
                        f"Pagination mismatch in filtered query for {target_date}! "
                        f"API reported {api_reported_total}, but fetched {our_count} "
                        f"(diff: {our_vs_api_diff})"
                    )
            
            return result
        
        # No filters - proceed with full three-way reconciliation
        official_count = self.get_official_count_for_date(target_date)

        if official_count is None:
            # No official data, but still check pagination consistency
            result = {
                "date": target_date.isoformat(),
                "official_count": None,
                "api_reported_total": api_reported_total,
                "our_count": our_count,
                "difference": None,
                "percentage_diff": None,
                "api_vs_official_diff": None,
                "our_vs_api_diff": None,
                "filters_applied": False,
                "status": "no_official_data",
            }
            
            # Check pagination consistency even without official data
            if api_reported_total is not None:
                our_vs_api_diff = our_count - api_reported_total
                result["our_vs_api_diff"] = our_vs_api_diff
                
                if our_vs_api_diff != 0:
                    result["status"] = "pagination_mismatch"
                    logger.warning(
                        f"Pagination mismatch for {target_date}! "
                        f"API reported {api_reported_total}, but fetched {our_count} "
                        f"(diff: {our_vs_api_diff})"
                    )
            
            return result

        # Calculate main comparison: our_count vs official_count
        difference = our_count - official_count
        percentage_diff = (
            (difference / official_count * 100) if official_count > 0 else 0
        )

        # Calculate additional comparisons if API reported total is available
        api_vs_official_diff = None
        our_vs_api_diff = None
        
        if api_reported_total is not None:
            api_vs_official_diff = api_reported_total - official_count
            our_vs_api_diff = our_count - api_reported_total

        # Determine status
        status = "match" if abs(percentage_diff) <= 1.0 else "discrepancy"
        
        # Check for pagination mismatch (our_count != api_reported_total)
        if our_vs_api_diff is not None and our_vs_api_diff != 0:
            if status == "match":
                status = "pagination_mismatch"  # Pagination issue but matches official
            else:
                status = "discrepancy_with_pagination_mismatch"

        # Logging
        log_msg = (
            f"Reconciliation for {target_date}: "
            f"Official={official_count}, "
            f"Our={our_count}, "
            f"Diff={difference} ({percentage_diff:.2f}%)"
        )
        
        if api_reported_total is not None:
            log_msg += (
                f" | API_reported={api_reported_total}, "
                f"API_vs_Official={api_vs_official_diff}, "
                f"Our_vs_API={our_vs_api_diff}"
            )
        
        logger.info(log_msg)

        if "discrepancy" in status:
            logger.warning(
                f"[WARN] Discrepancy detected for {target_date}! "
                f"Difference: {difference} ({percentage_diff:.2f}%)"
            )
        
        if our_vs_api_diff is not None and our_vs_api_diff != 0:
            logger.warning(
                f"[WARN] Pagination mismatch for {target_date}! "
                f"API reported {api_reported_total}, but fetched {our_count} "
                f"(diff: {our_vs_api_diff})"
            )

        return {
            "date": target_date.isoformat(),
            "official_count": official_count,
            "api_reported_total": api_reported_total,
            "our_count": our_count,
            "difference": difference,
            "percentage_diff": percentage_diff,
            "api_vs_official_diff": api_vs_official_diff,
            "our_vs_api_diff": our_vs_api_diff,
            "filters_applied": False,
            "status": status,
        }

    def fetch_and_reconcile(
        self,
        target_date: date,
        additional_params: Optional[Dict[str, Any]] = None,
        include_feature_flags: bool = True,
    ) -> tuple[List[Decision], Dict[str, Any]]:
        """
        Convenience method that fetches decisions and reconciles counts in one call.
        
        Args:
            target_date: Date to fetch decisions for
            additional_params: Optional additional search parameters
            include_feature_flags: Whether to apply feature flag filtering
        
        Returns:
            Tuple of (decisions_list, reconciliation_result)
        """
        decisions, api_count = self.fetch_decisions_for_day(
            target_date=target_date,
            additional_params=additional_params,
            include_feature_flags=include_feature_flags,
        )

        # Determine if filters are applied
        filters_applied = self._check_if_filters_applied(
            additional_params=additional_params,
            include_feature_flags=include_feature_flags,
        )

        reconciliation = self.reconcile_counts(
            target_date=target_date, 
            our_count=len(decisions),
            api_reported_total=api_count,
            filters_applied=filters_applied,
        )

        return decisions, reconciliation
    
    def _check_if_filters_applied(
        self,
        additional_params: Optional[Dict[str, Any]] = None,
        include_feature_flags: bool = True,
    ) -> bool:
        """
        Check if any filters are applied that would make official count comparison invalid.
        
        Filters include:
        - FILTER_DECISION_TYPES feature flag
        - Entity filters (org, unit, signer)
        - Decision type filters in additional_params
        
        Args:
            additional_params: Optional additional search parameters
            include_feature_flags: Whether feature flags are being applied
        
        Returns:
            True if filters are active, False otherwise
        """
        # Check for feature flag filtering
        if include_feature_flags:
            from core.services.feature_flag_service import feature_flags
            
            filtered_types = feature_flags.get_value("FILTER_DECISION_TYPES")
            if filtered_types and isinstance(filtered_types, list) and len(filtered_types) > 0:
                return True
        
        # Check for entity or type filters in additional params
        if additional_params:
            filter_keys = [
                DiavgeiaSearchFields.ORG,
                DiavgeiaSearchFields.UNIT,
                DiavgeiaSearchFields.SIGNER,
                DiavgeiaSearchFields.TYPE,
            ]
            
            for key in filter_keys:
                if key in additional_params and additional_params[key]:
                    return True
        
        return False
