import json
from typing import Any, Dict, List, Optional

from core.constants.search_service import SearchMethod
from core.models.companies import Company, CompanyPerson
from core.models.document_analysis import DocumentExtraction, ProcessingStatus
from core.models.organizations import Organization, Signer, Unit
from core.services.feature_flag_service import feature_flags
from core.services.opensearch_service import OpenSearchService
from core.services.prerequisite_check_service import prerequisite_check
from core.services.transliteration import TransliterationService
from core.utils.performance import query_debugger
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.core.cache import cache
from django.db.models import F, Q, QuerySet
from loguru import logger


class SearchService:
    """Centralized service for all search functionality"""

    def __init__(self):
        self.cache_timeout = 300  # 5 minutes
        self.opensearch_service = OpenSearchService()

    # ==================== PREREQUISITE CHECKING ====================

    def _get_validated_search_method(self, requested_method: str) -> str:
        """
        Validate that the requested search method's prerequisites are met.
        Falls back to POSTGRES_SIMPLE if prerequisites are not satisfied.

        Args:
            requested_method: The search method to validate

        Returns:
            The validated method (may be downgraded to POSTGRES_SIMPLE)
        """
        # If simple search requested, always honor it (no prerequisites)
        if requested_method == SearchMethod.POSTGRES_SIMPLE:
            return SearchMethod.POSTGRES_SIMPLE

        # Check prerequisites for each method
        if requested_method == SearchMethod.POSTGRES_FTS:
            # For entity searches, check if prerequisites are met (migration + backfill)
            # Note: INDEX_THE_POSTGRES is only for document content, not entities
            prereq = prerequisite_check.check_postgres_fts_prerequisites()
            if not prereq["available"]:
                logger.warning(
                    f"POSTGRES_FTS requested but prerequisites not met: {prereq['reason']}. "
                    f"Falling back to {SearchMethod.POSTGRES_SIMPLE}"
                )
                return SearchMethod.POSTGRES_SIMPLE
            return SearchMethod.POSTGRES_FTS

        elif requested_method == SearchMethod.OPENSEARCH:
            # OpenSearch requires INDEX_THE_OPENSEARCH to be enabled
            if not feature_flags.is_enabled("INDEX_THE_OPENSEARCH"):
                logger.warning(
                    f"OPENSEARCH requested but INDEX_THE_OPENSEARCH is disabled. "
                    f"Falling back to {SearchMethod.POSTGRES_SIMPLE}"
                )
                return SearchMethod.POSTGRES_SIMPLE
            return SearchMethod.OPENSEARCH

        else:
            # Unknown method - fall back to simple
            logger.warning(
                f"Unknown search method '{requested_method}'. "
                f"Falling back to {SearchMethod.POSTGRES_SIMPLE}"
            )
            return SearchMethod.POSTGRES_SIMPLE

    @staticmethod
    def check_method_prerequisites(method: str) -> Dict[str, Any]:
        """
        Check if prerequisites for a search method are met.
        Useful for validation before setting feature flags.

        Args:
            method: The search method to check

        Returns:
            Dict with 'available' (bool), 'reason' (str), and optional 'details' keys
        """
        if method == SearchMethod.POSTGRES_SIMPLE:
            return {"available": True, "reason": "No prerequisites required"}

        elif method == SearchMethod.POSTGRES_FTS:
            # Use the shared prerequisite check service (cached)
            return prerequisite_check.check_postgres_fts_prerequisites()

        elif method == SearchMethod.OPENSEARCH:
            if feature_flags.is_enabled("INDEX_THE_OPENSEARCH"):
                return {"available": True, "reason": "OpenSearch indexing is enabled"}
            return {
                "available": False,
                "reason": "Requires INDEX_THE_OPENSEARCH feature flag to be enabled",
            }

        else:
            return {"available": False, "reason": f"Unknown search method: {method}"}

    # ==================== ORGANIZATION SEARCH (3-TIER) ====================

    @query_debugger
    def search_organizations(self, query: str, limit: int = 20) -> QuerySet:
        """
        Search organizations using the configured search method.

        Supports three tiers:
        1. postgres_simple: Basic icontains search (default)
        2. postgres_fts: PostgreSQL Full-Text Search with smart language detection
        3. opensearch: OpenSearch with advanced features (TODO)

        The method automatically detects if the query is in Greek or Latin
        and adjusts ranking weights accordingly.

        Automatically falls back to postgres_simple if prerequisites are not met.
        """
        if not query:
            return Organization.objects.none()

        # Get configured search method with validation and auto-fallback
        requested_method = feature_flags.get_value(
            "ENTITY_SEARCH_METHOD", SearchMethod.DEFAULT
        )
        method = self._get_validated_search_method(requested_method)

        if method == SearchMethod.OPENSEARCH:
            return self._search_organizations_opensearch(query, limit)
        elif method == SearchMethod.POSTGRES_FTS:
            return self._search_organizations_fts(query, limit)
        else:  # POSTGRES_SIMPLE (default fallback)
            return self._search_organizations_simple(query, limit)

    def _search_organizations_simple(self, query: str, limit: int = 20) -> QuerySet:
        """Simple PostgreSQL ILIKE search (Tier 1)"""
        return Organization.objects.filter(
            Q(label__icontains=query) | Q(latin_name__icontains=query)
        ).order_by("label")[:limit]

    def _search_organizations_fts(self, query: str, limit: int = 20) -> QuerySet:
        """
        PostgreSQL Full-Text Search with smart language detection (Tier 2).

        Detects if the query is Greek or Latin and adjusts ranking:
        - Greek query → prioritize 'label' field (Greek names)
        - Latin query → prioritize 'latin_name' field
        - Mixed → balanced weighting
        """
        # Detect query language for smart weighting
        query_lang = TransliterationService.detect_language(query)

        # Create search query (using Greek config for better stemming)
        search_query = SearchQuery(query, config="greek")

        # Get dynamic weights based on query language
        weights = TransliterationService.get_search_rank_weights(query)

        # Search with ranking
        qs = (
            Organization.objects.annotate(
                rank=SearchRank(F("search_vector"), search_query, weights=weights)
            )
            .filter(search_vector=search_query)
            .order_by("-rank", "label")[:limit]
        )

        logger.debug(
            f"Organization FTS: query='{query}', lang={query_lang}, found={qs.count()}"
        )
        return qs

    def _search_organizations_opensearch(self, query: str, limit: int = 20) -> QuerySet:
        """
        OpenSearch-based entity search (Tier 3) - Future implementation.

        Will support:
        - Fuzzy matching (typo tolerance)
        - Phonetic search
        - Cross-entity relevance
        - Advanced filtering
        """
        # TODO: Implement OpenSearch entity indexing
        logger.warning(
            "OpenSearch entity search not yet implemented, falling back to FTS"
        )
        return self._search_organizations_fts(query, limit)

    # ==================== UNIT SEARCH (3-TIER) ====================

    @query_debugger
    def search_units(
        self, query: str, organization_id: Optional[str] = None, limit: int = 20
    ) -> QuerySet:
        """
        Search units using the configured search method.

        Supports filtering by organization_id when provided.
        Automatically falls back to postgres_simple if prerequisites are not met.
        """
        if not query:
            return Unit.objects.none()

        requested_method = feature_flags.get_value(
            "ENTITY_SEARCH_METHOD", SearchMethod.DEFAULT
        )
        method = self._get_validated_search_method(requested_method)

        if method == SearchMethod.OPENSEARCH:
            return self._search_units_opensearch(query, organization_id, limit)
        elif method == SearchMethod.POSTGRES_FTS:
            return self._search_units_fts(query, organization_id, limit)
        else:
            return self._search_units_simple(query, organization_id, limit)

    def _search_units_simple(
        self, query: str, organization_id: Optional[str] = None, limit: int = 20
    ) -> QuerySet:
        """Simple PostgreSQL ILIKE search (Tier 1)"""
        qs = Unit.objects.filter(label__icontains=query)

        if organization_id:
            qs = qs.filter(organization__uid=organization_id)

        return qs.select_related("organization").order_by("label")[:limit]

    def _search_units_fts(
        self, query: str, organization_id: Optional[str] = None, limit: int = 20
    ) -> QuerySet:
        """PostgreSQL Full-Text Search with smart language detection (Tier 2)"""
        TransliterationService.detect_language(query)
        search_query = SearchQuery(query, config="greek")
        weights = TransliterationService.get_search_rank_weights(query)

        qs = Unit.objects.annotate(
            rank=SearchRank(F("search_vector"), search_query, weights=weights)
        ).filter(search_vector=search_query)

        if organization_id:
            qs = qs.filter(organization__uid=organization_id)

        return qs.select_related("organization").order_by("-rank", "label")[:limit]

    def _search_units_opensearch(
        self, query: str, organization_id: Optional[str] = None, limit: int = 20
    ) -> QuerySet:
        """OpenSearch-based search (Tier 3) - Future"""
        logger.warning(
            "OpenSearch unit search not yet implemented, falling back to FTS"
        )
        return self._search_units_fts(query, organization_id, limit)

    # ==================== SIGNER SEARCH (3-TIER) ====================

    @query_debugger
    def search_signers(
        self, query: str, organization_id: Optional[str] = None, limit: int = 20
    ) -> QuerySet:
        """
        Search signers using the configured search method.

        Searches across first_name and last_name fields.
        Automatically falls back to postgres_simple if prerequisites are not met.
        """
        if not query:
            return Signer.objects.none()

        requested_method = feature_flags.get_value(
            "ENTITY_SEARCH_METHOD", SearchMethod.DEFAULT
        )
        method = self._get_validated_search_method(requested_method)

        if method == SearchMethod.OPENSEARCH:
            return self._search_signers_opensearch(query, organization_id, limit)
        elif method == SearchMethod.POSTGRES_FTS:
            return self._search_signers_fts(query, organization_id, limit)
        else:
            return self._search_signers_simple(query, organization_id, limit)

    def _search_signers_simple(
        self, query: str, organization_id: Optional[str] = None, limit: int = 20
    ) -> QuerySet:
        """Simple PostgreSQL ILIKE search (Tier 1)"""
        qs = Signer.objects.filter(
            Q(first_name__icontains=query) | Q(last_name__icontains=query)
        )

        if organization_id:
            qs = qs.filter(organization__uid=organization_id)

        return qs.select_related("organization").order_by("last_name", "first_name")[
            :limit
        ]

    def _search_signers_fts(
        self, query: str, organization_id: Optional[str] = None, limit: int = 20
    ) -> QuerySet:
        """PostgreSQL Full-Text Search with smart language detection (Tier 2)"""
        TransliterationService.detect_language(query)
        search_query = SearchQuery(query, config="greek")
        weights = TransliterationService.get_search_rank_weights(query)

        qs = Signer.objects.annotate(
            rank=SearchRank(F("search_vector"), search_query, weights=weights)
        ).filter(search_vector=search_query)

        if organization_id:
            qs = qs.filter(organization__uid=organization_id)

        return qs.select_related("organization").order_by(
            "-rank", "last_name", "first_name"
        )[:limit]

    def _search_signers_opensearch(
        self, query: str, organization_id: Optional[str] = None, limit: int = 20
    ) -> QuerySet:
        """OpenSearch-based search (Tier 3) - Future"""
        logger.warning(
            "OpenSearch signer search not yet implemented, falling back to FTS"
        )
        return self._search_signers_fts(query, organization_id, limit)

    @query_debugger
    def search_documents(
        self,
        query: str,
        provider: Optional[str] = None,
        status: Optional[str] = None,
        is_scanned: Optional[bool] = None,
        organization: Optional[str] = None,
        decision_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """
        Enhanced document search using OpenSearch with fallback to PostgreSQL
        Returns dict with results and metadata
        """
        if not query:
            return {"results": [], "count": 0, "source": "none", "highlights": {}}

        # Check if PostgreSQL search is enabled
        use_postgres_search = feature_flags.is_enabled("INDEX_THE_POSTGRES")

        # Skip OpenSearch if disabled, use PostgreSQL directly
        if not feature_flags.is_enabled("INDEX_THE_OPENSEARCH"):
            if not use_postgres_search:
                # Both search methods disabled - return empty result
                logger.warning(
                    "Both OpenSearch and PostgreSQL search are disabled. "
                    "Document content search unavailable. Only entity search is available."
                )
                return {"results": [], "count": 0, "source": "none", "highlights": {}}

            logger.info("OpenSearch disabled, falling back to PostgreSQL search")
            return self._search_documents_postgresql(
                query, provider, status, is_scanned, limit
            )

        # Try OpenSearch first
        try:
            # Build filters for OpenSearch
            opensearch_filters = {}

            if organization:
                opensearch_filters["organization"] = organization
            if decision_type:
                opensearch_filters["decision_type"] = decision_type
            if date_from:
                opensearch_filters["date_from"] = date_from
            if date_to:
                opensearch_filters["date_to"] = date_to

            # Search with OpenSearch
            opensearch_results = self.opensearch_service.search_documents(
                query=query, filters=opensearch_filters, size=limit
            )

            hits = opensearch_results.get("hits", {}).get("hits", [])
            total_hits = (
                opensearch_results.get("hits", {}).get("total", {}).get("value", 0)
            )

            if hits:
                # Convert OpenSearch results to our format
                results = self._convert_opensearch_results(
                    hits, provider, status, is_scanned
                )

                logger.info(
                    f"OpenSearch returned {len(results)} results for query: {query}"
                )

                return {
                    "results": results,
                    "count": total_hits,
                    "source": "opensearch",
                    "highlights": self._extract_highlights(hits),
                }

        except Exception as e:
            logger.error(f"OpenSearch search failed: {e}")

        # Fallback to PostgreSQL search only if enabled
        if use_postgres_search:
            logger.info("Falling back to PostgreSQL search")
            return self._search_documents_postgresql(
                query, provider, status, is_scanned, limit
            )
        else:
            logger.warning(
                "PostgreSQL search is disabled - no fallback available from OpenSearch failure. "
                "Document content search unavailable."
            )
            return {"results": [], "count": 0, "source": "none", "highlights": {}}

    def _convert_opensearch_results(
        self,
        hits: List[Dict],
        provider_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
        is_scanned_filter: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """Convert OpenSearch hits to DocumentExtraction-like objects with rich metadata"""
        results = []
        decision_ids = [hit["_source"]["decision_id"] for hit in hits]

        # Fetch the actual DocumentExtraction objects for the decision IDs
        # This gives us access to all the metadata we need
        extractions = (
            DocumentExtraction.objects.filter(
                decision_id__in=decision_ids,
                extraction_status=ProcessingStatus.COMPLETED,
            )
            .select_related(
                "decision", "decision__organization", "decision__decision_type"
            )
            .prefetch_related("decision__signers")
        )

        # Create a lookup dictionary
        extraction_lookup = {ext.decision_id: ext for ext in extractions}

        for hit in hits:
            source = hit["_source"]
            decision_id = source["decision_id"]

            # Get the actual extraction object
            extraction = extraction_lookup.get(decision_id)
            if not extraction:
                continue

            # Apply additional filters that weren't handled by OpenSearch
            if provider_filter and extraction.extraction_provider != provider_filter:
                continue
            if status_filter and extraction.decision.status != status_filter:
                continue
            if (
                is_scanned_filter is not None
                and extraction.is_scanned_document != is_scanned_filter
            ):
                continue

            # Extract text excerpt from highlights or raw content
            excerpt = self._extract_text_excerpt(hit, extraction)

            # Get decision signers
            signers = (
                list(extraction.decision.signers.all()) if extraction.decision else []
            )

            # Add search score and highlights from OpenSearch
            result_data = {
                "extraction": extraction,
                "search_score": hit.get("_score", 0),
                "highlights": hit.get("highlight", {}),
                "opensearch_source": source,
                "text_excerpt": excerpt,
                "signers": signers,
            }

            results.append(result_data)

        return results

    def _extract_text_excerpt(
        self, hit: Dict, extraction: Any, max_length: int = 300
    ) -> str:
        """Extract a meaningful text excerpt from OpenSearch highlights or document content"""
        highlights = hit.get("highlight", {})

        # Log what we're getting from OpenSearch for debugging
        logger.debug(
            f"OpenSearch highlights for decision {hit.get('_source', {}).get('decision_id')}: {highlights}"
        )

        # Try to get excerpt from highlights first (best option)
        if "content" in highlights and highlights["content"]:
            # Join highlighted content and clean it up
            excerpt = " ... ".join(
                highlights["content"][:3]
            )  # Take first 3 highlight snippets
            return (
                excerpt[:max_length] + "..." if len(excerpt) > max_length else excerpt
            )

        # Try content_preview highlights
        if "content_preview" in highlights and highlights["content_preview"]:
            excerpt = " ... ".join(highlights["content_preview"][:2])
            return (
                excerpt[:max_length] + "..." if len(excerpt) > max_length else excerpt
            )

        # Try title highlights as fallback
        if "title" in highlights and highlights["title"]:
            excerpt = " ... ".join(highlights["title"][:1])
            return (
                excerpt[:max_length] + "..." if len(excerpt) > max_length else excerpt
            )

        # If no highlights, try OpenSearch source content_preview
        source = hit.get("_source", {})
        if "content_preview" in source and source["content_preview"]:
            preview = source["content_preview"]
            return (
                preview[:max_length] + "..." if len(preview) > max_length else preview
            )

        # Fallback to beginning of raw text from extraction
        if hasattr(extraction, "raw_text") and extraction.raw_text:
            raw_text = extraction.raw_text.strip()
            if len(raw_text) > max_length:
                # Try to break at word boundary
                truncated = raw_text[:max_length]
                last_space = truncated.rfind(" ")
                if last_space > max_length - 50:  # If we found a space near the end
                    truncated = truncated[:last_space]
                return truncated + "..."
            return raw_text

        return "No content preview available"

    def _extract_highlights(self, hits: List[Dict]) -> Dict[str, List[str]]:
        """Extract all highlights from OpenSearch results"""
        all_highlights = {}
        for hit in hits:
            highlights = hit.get("highlight", {})
            for field, highlight_list in highlights.items():
                if field not in all_highlights:
                    all_highlights[field] = []
                all_highlights[field].extend(highlight_list)
        return all_highlights

    def _search_documents_postgresql(
        self,
        query: str,
        provider: Optional[str] = None,
        status: Optional[str] = None,
        is_scanned: Optional[bool] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """
        Fallback PostgreSQL search (original implementation)
        Only called when INDEX_THE_POSTGRES is enabled
        """
        # Safety check: ensure PostgreSQL search is enabled
        if not feature_flags.is_enabled("INDEX_THE_POSTGRES"):
            logger.error(
                "_search_documents_postgresql called but INDEX_THE_POSTGRES is disabled. "
                "This should not happen - check search_documents() logic."
            )
            return {"results": [], "count": 0, "source": "none", "highlights": {}}

        # Build the base queryset with filters
        qs = DocumentExtraction.objects.filter(
            extraction_status=ProcessingStatus.COMPLETED
        )

        # Add prefetch_related and select_related to optimize queries
        qs = qs.select_related("decision", "decision__organization")
        qs = qs.prefetch_related("decision__signers")

        if provider:
            qs = qs.filter(extraction_provider=provider)

        if status:
            qs = qs.filter(decision__status=status)

        if is_scanned is not None:
            qs = qs.filter(is_scanned_document=is_scanned)

        # Try PostgreSQL full-text search first
        try:
            search_query = SearchQuery(query, config="greek")
            vector_results = (
                qs.filter(search_vector=search_query)
                .annotate(rank=SearchRank("search_vector", search_query))
                .order_by("-rank")
            )

            # If vector search returns results, use them
            if vector_results.exists():
                results = [
                    {
                        "extraction": ext,
                        "search_score": float(ext.rank),
                        "highlights": {},
                    }
                    for ext in vector_results[:limit]
                ]
                count = vector_results.count()
            else:
                # Fallback to direct text search
                fallback_results = qs.filter(raw_text__icontains=query)[:limit]
                results = [
                    {"extraction": ext, "search_score": 1.0, "highlights": {}}
                    for ext in fallback_results
                ]
                count = fallback_results.count()
        except Exception:
            # If any error occurs, fall back to direct text search
            fallback_results = qs.filter(raw_text__icontains=query)[:limit]
            results = [
                {"extraction": ext, "search_score": 1.0, "highlights": {}}
                for ext in fallback_results
            ]
            count = fallback_results.count()

        logger.info(
            f"PostgreSQL fallback returned {len(results)} results for query: {query}"
        )

        return {
            "results": results,
            "count": count,
            "source": "postgresql",
            "highlights": {},
        }

    @query_debugger
    def search_all_entities(
        self,
        query: str,
        include_organizations: bool = True,
        include_units: bool = True,
        include_signers: bool = True,
        include_companies: bool = True,
        include_company_persons: bool = True,
        organization_id: Optional[str] = None,
        company_id: Optional[int] = None,
        limit_per_type: int = 10,
    ) -> Dict[str, Any]:
        """
        Search across multiple entity types
        Returns organized results by type
        """
        results = {
            "organizations": [],
            "units": [],
            "signers": [],
            "companies": [],
            "company_persons": [],
            "total_count": 0,
        }

        if not query:
            return results

        # Create cache key
        cache_key = f"search_all_{hash(query)}_{organization_id}_{company_id}_{include_organizations}_{include_units}_{include_signers}_{include_companies}_{include_company_persons}"
        cached_results = cache.get(cache_key)
        if cached_results:
            return cached_results

        if include_organizations:
            orgs = self.search_organizations(query, limit_per_type)
            results["organizations"] = [
                {
                    "id": org.uid,
                    "text": org.label,
                    "type": "organization",
                    "latin_name": org.latin_name,
                }
                for org in orgs
            ]

        if include_units:
            units = self.search_units(query, organization_id, limit_per_type)
            results["units"] = [
                {
                    "id": unit.uid,
                    "text": unit.label,
                    "type": "unit",
                    "organization": (
                        unit.organization.label if unit.organization else None
                    ),
                }
                for unit in units
            ]

        if include_signers:
            signers = self.search_signers(query, organization_id, limit_per_type)
            results["signers"] = [
                {
                    "id": signer.uid,
                    "text": f"{signer.last_name}, {signer.first_name}",
                    "type": "signer",
                    "first_name": signer.first_name,
                    "last_name": signer.last_name,
                    "organization": (
                        signer.organization.label if signer.organization else None
                    ),
                    "organization_id": (
                        signer.organization.uid if signer.organization else None
                    ),
                }
                for signer in signers
            ]

        if include_companies:
            companies = self.search_companies(query, limit_per_type)
            results["companies"] = [
                {
                    "id": company.ar_gemi,
                    "text": company.co_name_el or "No name",
                    "type": "company",
                    "co_name_el": company.co_name_el,
                    "co_names_en": company.co_names_en,
                    "co_titles_el": company.co_titles_el,
                    "co_titles_en": company.co_titles_en,
                    "afm": company.afm,
                    "ar_gemi": company.ar_gemi,
                    "municipality_name": company.municipality_name,
                    "prefecture_name": company.prefecture_name,
                    "status_name": company.status_name,
                }
                for company in companies
            ]

        if include_company_persons:
            company_persons = self.search_company_persons(
                query, company_id, limit_per_type
            )
            results["company_persons"] = [
                {
                    "id": person.id,
                    "text": person.person_name or person.business_name or "No name",
                    "type": "company_person",
                    "person_name": person.person_name,
                    "business_name": person.business_name,
                    "role": person.role,
                    "company_name": (
                        person.company.co_name_el if person.company else None
                    ),
                    "company_id": person.company.ar_gemi if person.company else None,
                }
                for person in company_persons
            ]

        results["total_count"] = (
            len(results["organizations"])
            + len(results["units"])
            + len(results["signers"])
            + len(results["companies"])
            + len(results["company_persons"])
        )

        # Cache results for 5 minutes
        cache.set(cache_key, results, self.cache_timeout)
        return results

    def get_document_search_options(self) -> Dict[str, List[str]]:
        """Get available options for document search filters"""
        cache_key = "document_search_options"
        cached_options = cache.get(cache_key)
        if cached_options:
            return cached_options

        providers = list(
            DocumentExtraction.objects.values_list("extraction_provider", flat=True)
            .distinct()
            .exclude(extraction_provider__isnull=True)
        )

        from core.models.decisions import DecisionStatus

        statuses = [status.value for status in DecisionStatus]

        options = {"providers": providers, "statuses": statuses}

        # Cache for 1 hour
        cache.set(cache_key, options, 3600)
        return options

    # ==================== COMPANY SEARCH (3-TIER) ====================

    @query_debugger
    def search_companies(self, query: str, limit: int = 20) -> QuerySet:
        """
        Search companies using the configured search method.

        Searches across Greek/English names, titles, AFM, and GEMI numbers.
        Automatically falls back to postgres_simple if prerequisites are not met.
        """
        if not query:
            return Company.objects.none()

        requested_method = feature_flags.get_value(
            "ENTITY_SEARCH_METHOD", SearchMethod.DEFAULT
        )
        method = self._get_validated_search_method(requested_method)

        if method == SearchMethod.OPENSEARCH:
            return self._search_companies_opensearch(query, limit)
        elif method == SearchMethod.POSTGRES_FTS:
            return self._search_companies_fts(query, limit)
        else:
            return self._search_companies_simple(query, limit)

    def _search_companies_simple(self, query: str, limit: int = 20) -> QuerySet:
        """Simple PostgreSQL ILIKE search (Tier 1)"""
        qs = Company.objects.filter(
            Q(is_branch=False)
            & (
                Q(co_name_el__icontains=query)
                | Q(co_names_en__icontains=query)
                | Q(co_titles_el__icontains=query)
                | Q(co_titles_en__icontains=query)
                | Q(afm__icontains=query)
                | Q(ar_gemi__icontains=query)
            )
        ).order_by("co_name_el")[:limit]

        return qs

    def _search_companies_fts(self, query: str, limit: int = 20) -> QuerySet:
        """
        PostgreSQL Full-Text Search with smart language detection (Tier 2).

        Note: Companies have both Greek and English name fields,
        so language detection helps prioritize the right fields.
        """
        TransliterationService.detect_language(query)
        search_query = SearchQuery(query, config="greek")
        weights = TransliterationService.get_search_rank_weights(query)

        qs = (
            Company.objects.filter(is_branch=False)
            .annotate(
                rank=SearchRank(F("search_vector"), search_query, weights=weights)
            )
            .filter(search_vector=search_query)
            .order_by("-rank", "co_name_el")[:limit]
        )

        return qs

    def _search_companies_opensearch(self, query: str, limit: int = 20) -> QuerySet:
        """OpenSearch-based search (Tier 3) - Future"""
        logger.warning(
            "OpenSearch company search not yet implemented, falling back to FTS"
        )
        return self._search_companies_fts(query, limit)

    # ==================== COMPANY PERSON SEARCH (3-TIER) ====================

    @query_debugger
    def search_company_persons(
        self, query: str, company_id: Optional[int] = None, limit: int = 20
    ) -> QuerySet:
        """
        Search company persons using the configured search method.

        Supports filtering by company_id when provided.
        Automatically falls back to postgres_simple if prerequisites are not met.
        """
        if not query:
            return CompanyPerson.objects.none()

        requested_method = feature_flags.get_value(
            "ENTITY_SEARCH_METHOD", SearchMethod.DEFAULT
        )
        method = self._get_validated_search_method(requested_method)

        if method == SearchMethod.OPENSEARCH:
            return self._search_company_persons_opensearch(query, company_id, limit)
        elif method == SearchMethod.POSTGRES_FTS:
            return self._search_company_persons_fts(query, company_id, limit)
        else:
            return self._search_company_persons_simple(query, company_id, limit)

    def _search_company_persons_simple(
        self, query: str, company_id: Optional[int] = None, limit: int = 20
    ) -> QuerySet:
        """Simple PostgreSQL ILIKE search (Tier 1)"""
        qs = CompanyPerson.objects.filter(
            Q(person_name__icontains=query)
            | Q(business_name__icontains=query)
            | Q(role__icontains=query)
        )

        if company_id:
            qs = qs.filter(company_id=company_id)

        return qs.select_related("company").order_by("person_name")[:limit]

    def _search_company_persons_fts(
        self, query: str, company_id: Optional[int] = None, limit: int = 20
    ) -> QuerySet:
        """PostgreSQL Full-Text Search with smart language detection (Tier 2)"""
        TransliterationService.detect_language(query)
        search_query = SearchQuery(query, config="greek")
        weights = TransliterationService.get_search_rank_weights(query)

        qs = CompanyPerson.objects.annotate(
            rank=SearchRank(F("search_vector"), search_query, weights=weights)
        ).filter(search_vector=search_query)

        if company_id:
            qs = qs.filter(company_id=company_id)

        return qs.select_related("company").order_by("-rank", "person_name")[:limit]

    def _search_company_persons_opensearch(
        self, query: str, company_id: Optional[int] = None, limit: int = 20
    ) -> QuerySet:
        """OpenSearch-based search (Tier 3) - Future"""
        logger.warning(
            "OpenSearch company person search not yet implemented, falling back to FTS"
        )
        return self._search_company_persons_fts(query, company_id, limit)

    @query_debugger
    def search_all_entities_extended(
        self,
        query: str,
        include_organizations: bool = True,
        include_units: bool = True,
        include_signers: bool = True,
        include_companies: bool = True,
        include_company_people: bool = True,
        organization_id: Optional[str] = None,
        limit_per_type: int = 10,
    ) -> Dict[str, Any]:
        """
        Extended search across multiple entity types, including companies and company people
        Returns organized results by type
        """
        results = {
            "organizations": [],
            "units": [],
            "signers": [],
            "companies": [],
            "company_people": [],
            "total_count": 0,
        }

        if not query:
            return results

        # Create cache key
        cache_key = f"search_all_extended_{hash(query)}_{organization_id}_{include_organizations}_{include_units}_{include_signers}_{include_companies}_{include_company_people}"
        cached_results = cache.get(cache_key)
        if cached_results:
            return cached_results

        if include_organizations:
            orgs = self.search_organizations(query, limit_per_type)
            results["organizations"] = [
                {
                    "id": org.uid,
                    "text": org.label,
                    "type": "organization",
                    "latin_name": org.latin_name,
                }
                for org in orgs
            ]

        if include_units:
            units = self.search_units(query, organization_id, limit_per_type)
            results["units"] = [
                {
                    "id": unit.uid,
                    "text": unit.label,
                    "type": "unit",
                    "organization": (
                        unit.organization.label if unit.organization else None
                    ),
                }
                for unit in units
            ]

        if include_signers:
            signers = self.search_signers(query, organization_id, limit_per_type)
            results["signers"] = [
                {
                    "id": signer.uid,
                    "text": f"{signer.last_name}, {signer.first_name}",
                    "type": "signer",
                    "first_name": signer.first_name,
                    "last_name": signer.last_name,
                    "organization": (
                        signer.organization.label if signer.organization else None
                    ),
                    "organization_id": (
                        signer.organization.uid if signer.organization else None
                    ),
                }
                for signer in signers
            ]

        if include_companies:
            companies = self.search_companies(query, limit_per_type)
            results["companies"] = [
                {"id": company.uid, "text": company.name, "type": "company"}
                for company in companies
            ]

        if include_company_people:
            company_people = self.search_company_persons(query, None, limit_per_type)
            results["company_people"] = [
                {
                    "id": person.uid,
                    "text": f"{person.last_name}, {person.first_name}",
                    "type": "company_person",
                    "first_name": person.first_name,
                    "last_name": person.last_name,
                    "company": person.company.name if person.company else None,
                    "company_id": person.company.uid if person.company else None,
                }
                for person in company_people
            ]

        results["total_count"] = (
            len(results["organizations"])
            + len(results["units"])
            + len(results["signers"])
            + len(results["companies"])
            + len(results["company_people"])
        )

        # Cache results for 5 minutes
        cache.set(cache_key, results, self.cache_timeout)
        return results

    def debug_opensearch_response(self, query: str, limit: int = 3) -> Dict[str, Any]:
        """Debug method to see what OpenSearch is actually returning"""
        try:
            opensearch_results = self.opensearch_service.search_documents(
                query=query, size=limit
            )

            logger.info(f"Raw OpenSearch response for '{query}':")
            logger.info(json.dumps(opensearch_results, indent=2, ensure_ascii=False))

            hits = opensearch_results.get("hits", {}).get("hits", [])
            if hits:
                for i, hit in enumerate(hits):
                    logger.info(f"Hit {i+1}:")
                    logger.info(f"  Source: {hit.get('_source', {})}")
                    logger.info(f"  Highlights: {hit.get('highlight', {})}")
                    logger.info(f"  Score: {hit.get('_score', 0)}")

            return opensearch_results

        except Exception as e:
            logger.error(f"Debug search failed: {e}")
            return {}
