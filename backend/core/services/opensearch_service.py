import math
import time
from typing import Any, Dict, List

import requests
from core.services.feature_flag_service import feature_flags
from django.conf import settings
from loguru import logger


class OpenSearchService:
    # Class-level connection cache to avoid repeated testing
    _connection_tested = False
    _connection_test_time = 0
    _connection_test_ttl = 300  # Cache connection test for 5 minutes
    # Circuit breaker: once a probe fails, the service is treated as disabled
    # until the next TTL expiry re-probes and succeeds (self-healing).
    _connection_ok = False

    def __init__(self, test_connection: bool = False):
        """
        Initialize OpenSearch service.

        Args:
            test_connection: If True, force connection test. Otherwise uses cached result.
        """
        # Check if OpenSearch is enabled via feature flag
        flag_enabled = feature_flags.is_enabled("INDEX_THE_OPENSEARCH")

        self.opensearch_url = getattr(
            settings, "OPENSEARCH_URL", "http://opensearch:9200"
        )
        self.index_name = "diavgeia-documents"
        self.max_content_length = 10000
        self.preview_length = 500

        # Skip validation and connection testing if OpenSearch is disabled
        if not flag_enabled:
            self.is_enabled = False
            logger.debug(
                "OpenSearch is disabled via feature flag - skipping initialization"
            )
            return

        # Validate URL has a scheme
        if not self.opensearch_url or not self.opensearch_url.startswith(
            ("http://", "https://")
        ):
            error_msg = f"Invalid OPENSEARCH_URL: '{self.opensearch_url}'. Must start with http:// or https://"
            logger.error(f"{error_msg}")
            logger.error(
                "Check that OPENSEARCH_URL environment variable is set correctly"
            )
            # Set a safe default to prevent crashes, but service won't work
            self.opensearch_url = "http://opensearch:9200"

        # Only test connection if explicitly requested or cache expired
        current_time = time.time()
        if (
            test_connection
            or not OpenSearchService._connection_tested
            or (current_time - OpenSearchService._connection_test_time)
            > OpenSearchService._connection_test_ttl
        ):
            OpenSearchService._connection_ok = self._test_connection()
            OpenSearchService._connection_tested = True
            OpenSearchService._connection_test_time = current_time

        # Effective enablement: flag on AND the cluster is reachable. When the
        # container is absent, the probe fails once per TTL and everything
        # short-circuits at the `if not self.is_enabled` guards below.
        self.is_enabled = flag_enabled and OpenSearchService._connection_ok

    def _test_connection(self) -> bool:
        """Test OpenSearch connection and log results at DEBUG level.

        Returns True if the cluster health check succeeded, False otherwise.
        """
        try:
            response = requests.get(f"{self.opensearch_url}/_cluster/health", timeout=5)
            if response.status_code == 200:
                health = response.json()
                logger.debug(
                    f"OpenSearch connection OK - Status: {health.get('status')}"
                )

                # Test if our index exists
                index_response = requests.get(
                    f"{self.opensearch_url}/{self.index_name}", timeout=5
                )
                if index_response.status_code == 200:
                    logger.debug(f"Index '{self.index_name}' exists")

                    # Get document count
                    count_response = requests.get(
                        f"{self.opensearch_url}/{self.index_name}/_count", timeout=5
                    )
                    if count_response.status_code == 200:
                        count_data = count_response.json()
                        doc_count = count_data.get("count", 0)
                        logger.debug(f"Index contains {doc_count} documents")
                    else:
                        logger.warning(
                            f"Could not get document count: {count_response.status_code}"
                        )
                else:
                    logger.warning(
                        f"Index '{self.index_name}' does not exist: {index_response.status_code}"
                    )
                return True
            else:
                logger.error(f"OpenSearch health check failed: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"OpenSearch connection test failed: {e}")
            return False

    def _prepare_content(self, raw_text: str) -> Dict[str, str]:
        """Prepare content with smart truncation"""
        if not raw_text:
            return {"content": "", "content_preview": ""}

        # Clean the text
        cleaned = raw_text.strip()

        # Create preview (first meaningful paragraph)
        lines = cleaned.split("\n")
        preview_lines = []
        preview_chars = 0

        for line in lines:
            line = line.strip()
            if line and len(line) > 20:  # Skip very short lines
                if preview_chars + len(line) <= self.preview_length:
                    preview_lines.append(line)
                    preview_chars += len(line)
                else:
                    break

        preview = " ".join(preview_lines)

        # Create search content (smart truncation at sentence boundaries)
        if len(cleaned) <= self.max_content_length:
            content = cleaned
        else:
            # Truncate at sentence boundary near the limit
            truncated = cleaned[: self.max_content_length]
            last_sentence = max(
                truncated.rfind("."),
                truncated.rfind("!"),
                truncated.rfind("?"),
                truncated.rfind("."),  # Greek period
            )

            if (
                last_sentence > self.max_content_length * 0.8
            ):  # If we found a good break point
                content = truncated[: last_sentence + 1]
            else:
                content = truncated  # Just truncate

        return {"content": content, "content_preview": preview}

    def index_document(self, document_data: Dict[str, Any]) -> bool:
        """Index a single document with smart content handling"""
        if not self.is_enabled:
            logger.debug("OpenSearch is disabled - skipping document indexing")
            return False

        decision_id = document_data.get("decision_id", "unknown")
        ada = document_data.get("ada", "unknown")

        try:
            # Prepare content
            raw_text = document_data.get("content", "")
            content_data = self._prepare_content(raw_text)

            # Update document data
            document_data.update(content_data)

            # Add metadata
            document_data["indexed_at"] = time.time()
            document_data["content_length"] = len(content_data["content"])
            document_data["is_truncated"] = len(raw_text) > self.max_content_length

            # Log the indexing attempt
            url = f"{self.opensearch_url}/{self.index_name}/_doc/{decision_id}"
            logger.debug(
                f"Attempting to index document {ada} (ID: {decision_id}) to {url}"
            )

            response = requests.post(
                url,
                json=document_data,
                headers={"Content-Type": "application/json"},
                timeout=30,  # Add explicit timeout
            )

            # Log the raw response for debugging
            logger.debug(f"OpenSearch response status: {response.status_code}")
            logger.debug(f"OpenSearch response body: {response.text[:500]}")

            if response.status_code in [200, 201]:
                logger.info(
                    f"Indexed document {ada} (ID: {decision_id}, {len(content_data['content'])} chars)"
                )

                # Force index refresh to make document immediately searchable
                try:
                    refresh_response = requests.post(
                        f"{self.opensearch_url}/{self.index_name}/_refresh", timeout=10
                    )
                    logger.debug(
                        f"Index refresh status: {refresh_response.status_code}"
                    )
                except Exception as refresh_error:
                    logger.warning(
                        f"Index refresh failed (non-critical): {refresh_error}"
                    )

                return True
            else:
                logger.error(
                    f"Failed to index document {ada} (ID: {decision_id}): "
                    f"HTTP {response.status_code} - {response.text[:200]}"
                )
                return False

        except requests.exceptions.Timeout as e:
            logger.error(f"Timeout indexing document {ada} (ID: {decision_id}): {e}")
            return False
        except requests.exceptions.ConnectionError as e:
            logger.error(
                f"Connection error indexing document {ada} (ID: {decision_id}): {e}"
            )
            return False
        except Exception as e:
            logger.error(
                f"Error indexing document {ada} (ID: {decision_id}): {e}", exc_info=True
            )
            return False

    def search_documents(
        self, query: str, filters: Dict = None, size: int = 10
    ) -> Dict[str, Any]:
        """Enhanced search with filtering"""
        if not self.is_enabled:
            logger.debug("OpenSearch is disabled - returning empty search results")
            return {"hits": {"hits": [], "total": {"value": 0}}}

        logger.info(
            f"OpenSearch search_documents called with query: '{query}', filters: {filters}, size: {size}"
        )

        # Build the search query
        search_body = {
            "query": {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": query,
                                "fields": ["title^3", "content^2", "content_preview"],
                                "analyzer": "greek_text_analyzer",
                            }
                        }
                    ]
                }
            },
            "highlight": {
                "fields": {
                    "title": {"number_of_fragments": 1},
                    "content": {"fragment_size": 150, "number_of_fragments": 3},
                    "content_preview": {"number_of_fragments": 1},
                }
            },
            "_source": [
                "decision_id",
                "ada",
                "title",
                "content_preview",
                "organization",
                "decision_type",
                "issue_date",
                "page_count",
                "character_count",
                "is_truncated",
            ],
            "size": size,
        }

        # Add filters if provided
        if filters:
            filter_clauses = []

            if filters.get("organization"):
                filter_clauses.append(
                    {"term": {"organization.raw": filters["organization"]}}
                )

            if filters.get("decision_type"):
                filter_clauses.append(
                    {"term": {"decision_type": filters["decision_type"]}}
                )

            if filters.get("date_from") or filters.get("date_to"):
                date_range = {}
                if filters.get("date_from"):
                    date_range["gte"] = filters["date_from"]
                if filters.get("date_to"):
                    date_range["lte"] = filters["date_to"]
                filter_clauses.append({"range": {"issue_date": date_range}})

            if filter_clauses:
                search_body["query"]["bool"]["filter"] = filter_clauses

        # logger.debug(f"Search body: {json.dumps(search_body, indent=2, ensure_ascii=False)}")

        try:
            url = f"{self.opensearch_url}/{self.index_name}/_search"
            logger.debug(f"Making request to: {url}")

            response = requests.post(url, json=search_body, timeout=10)

            logger.debug(f"Response status: {response.status_code}")
            logger.debug(f"Response headers: {dict(response.headers)}")

            if response.status_code == 200:
                result = response.json()
                hits = result.get("hits", {}).get("hits", [])
                total = result.get("hits", {}).get("total", {})

                logger.info(
                    f"Search successful - Total: {total}, Hits returned: {len(hits)}"
                )

                if hits:
                    logger.debug(
                        f"First hit preview: {hits[0].get('_source', {}).get('title', 'No title')}"
                    )
                    logger.debug(
                        f"First hit highlights: {hits[0].get('highlight', {})}"
                    )
                else:
                    logger.warning("No hits returned from OpenSearch")

                return result
            else:
                error_text = response.text
                logger.error(f"Search failed: {response.status_code} - {error_text}")
                return {"hits": {"hits": []}}

        except Exception as e:
            logger.error(f"Search error: {e}")
            import traceback

            logger.error(f"Search error traceback: {traceback.format_exc()}")
            return {"hits": {"hits": []}}

    def _analyze_text(self, text: str) -> List[str]:
        """Analyze text with the Greek analyzer to see what tokens are produced"""
        analyze_request = {"analyzer": "greek_text_analyzer", "text": text}

        try:
            response = requests.post(
                f"{self.opensearch_url}/{self.index_name}/_analyze",
                json=analyze_request,
                timeout=10,
            )

            if response.status_code == 200:
                result = response.json()
                return [token["token"] for token in result.get("tokens", [])]
            else:
                logger.error(f"Analysis failed: {response.status_code}")
                return []

        except Exception as e:
            logger.error(f"Analysis error: {e}")
            return []

    def test_simple_search(self, query: str = "test") -> Dict[str, Any]:
        """Simple test search to debug connection"""
        logger.info(f"Testing simple search with query: '{query}'")

        # Simple match_all query first
        simple_body = {"query": {"match_all": {}}, "size": 3}

        try:
            url = f"{self.opensearch_url}/{self.index_name}/_search"
            logger.info(f"Testing with match_all at: {url}")

            response = requests.post(url, json=simple_body, timeout=10)
            logger.info(f"Match_all response status: {response.status_code}")

            if response.status_code == 200:
                result = response.json()
                total = result.get("hits", {}).get("total", {})
                hits = result.get("hits", {}).get("hits", [])
                logger.info(
                    f"Match_all successful - Total docs: {total}, Sample: {len(hits)}"
                )

                # Now try the actual search
                search_body = {
                    "query": {
                        "multi_match": {
                            "query": query,
                            "fields": ["title", "content", "content_preview"],
                        }
                    },
                    "size": 3,
                }

                search_response = requests.post(url, json=search_body, timeout=10)
                logger.info(f"Search response status: {search_response.status_code}")

                if search_response.status_code == 200:
                    search_result = search_response.json()
                    search_hits = search_result.get("hits", {}).get("hits", [])
                    logger.info(f"Search successful - Hits: {len(search_hits)}")
                    return search_result
                else:
                    logger.error(
                        f"Search failed: {search_response.status_code} - {search_response.text}"
                    )
                    return result  # Return match_all results

            else:
                logger.error(
                    f"Match_all failed: {response.status_code} - {response.text}"
                )
                return {"hits": {"hits": []}}

        except Exception as e:
            logger.error(f"Test search error: {e}")
            import traceback

            logger.error(f"Test search traceback: {traceback.format_exc()}")
            return {"hits": {"hits": []}}

    def _force_refresh(self):
        """Force refresh the index to make documents immediately searchable"""
        try:
            response = requests.post(
                f"{self.opensearch_url}/{self.index_name}/_refresh", timeout=10
            )
            if response.status_code == 200:
                logger.info("OpenSearch index refreshed successfully")
                return True
            else:
                logger.error(f"Failed to refresh index: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Error refreshing index: {e}")
            return False

    def _test_match_all(self, size=10000):
        """
        Execute a match_all query to get all documents or a count
        Used for sync verification and getting all indexed ADAs
        """
        try:
            search_body = {
                "query": {"match_all": {}},
                "size": size,
                "_source": ["ada", "decision_id"],  # Only fetch minimal fields
            }

            response = requests.post(
                f"{self.opensearch_url}/{self.index_name}/_search",
                json=search_body,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )

            if response.status_code == 200:
                result = response.json()
                logger.debug(
                    f"Match_all query returned {result.get('hits', {}).get('total', {}).get('value', 0)} documents"
                )
                return result
            else:
                logger.error(f"Match_all query failed: {response.status_code}")
                return {"hits": {"hits": [], "total": {"value": 0}}}

        except Exception as e:
            logger.error(f"Error in _test_match_all: {e}")
            return {"hits": {"hits": [], "total": {"value": 0}}}

    def register_s3_repository(
        self,
        repository_name="s3-backup-repo",
        bucket_name=None,
        base_path="opensearch/backups",
    ):
        """Register S3 repository for snapshots

        Note: AWS credentials should be set via environment variables in the OpenSearch container:
        - AWS_ACCESS_KEY_ID
        - AWS_SECRET_ACCESS_KEY
        - AWS_DEFAULT_REGION

        Do NOT pass credentials via the API as OpenSearch considers this insecure.
        """
        from django.conf import settings

        if not bucket_name:
            bucket_name = (
                getattr(settings, "AWS_STORAGE_BUCKET_NAME", None) or "diavgeia-backups"
            )

        # Build repository settings - OpenSearch will use container environment variables for credentials
        repo_settings = {
            "bucket": bucket_name,
            "base_path": base_path,
            "compress": True,
            "server_side_encryption": True,
            "region": settings.AWS_S3_REGION_NAME,
        }

        # DO NOT add access_key/secret_key here - OpenSearch considers this insecure
        # The OpenSearch container must have AWS credentials set via environment variables

        body = {"type": "s3", "settings": repo_settings}

        try:
            response = requests.put(
                f"{self.opensearch_url}/_snapshot/{repository_name}",
                json=body,
                timeout=10,
            )
            if response.status_code == 200:
                logger.info(
                    f"S3 repository '{repository_name}' registered successfully"
                )
                return True
            else:
                error_msg = f"Failed to register S3 repository: {response.text}"
                logger.error(f"{error_msg}")
                raise Exception(error_msg)
        except requests.exceptions.RequestException as e:
            error_msg = f"Request failed to register S3 repository: {str(e)}"
            logger.error(f"{error_msg}")
            raise Exception(error_msg)

    def create_snapshot(self, repository_name="s3-backup-repo", snapshot_name=None):
        """Create a snapshot backup"""
        from datetime import datetime

        if not snapshot_name:
            snapshot_name = f"snapshot-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        body = {
            "indices": "*",
            "ignore_unavailable": True,
            "include_global_state": False,
        }

        try:
            response = requests.put(
                f"{self.opensearch_url}/_snapshot/{repository_name}/{snapshot_name}",
                json=body,
                timeout=30,
                params={"wait_for_completion": "true"},
            )
            if response.status_code == 200:
                logger.info(f"Snapshot '{snapshot_name}' created successfully")
                return {"success": True, "snapshot": snapshot_name}
            else:
                error_msg = f"Failed to create snapshot: {response.text}"
                logger.error(f"{error_msg}")
                raise Exception(error_msg)
        except requests.exceptions.RequestException as e:
            error_msg = f"Request failed to create snapshot: {str(e)}"
            logger.error(f"{error_msg}")
            raise Exception(error_msg)

    def list_snapshots(self, repository_name="s3-backup-repo"):
        """List all snapshots in repository"""
        try:
            response = requests.get(
                f"{self.opensearch_url}/_snapshot/{repository_name}/_all", timeout=10
            )
            if response.status_code == 200:
                return response.json().get("snapshots", [])
            else:
                logger.error(f"Failed to list snapshots: {response.text}")
                return []
        except Exception as e:
            logger.error(f"Failed to list snapshots: {e}")
            return []

    def restore_snapshot(self, repository_name="s3-backup-repo", snapshot_name=None):
        """Restore from snapshot"""
        if not snapshot_name:
            logger.error("Snapshot name is required for restore")
            return False

        try:
            # Close indices before restore if necessary
            requests.post(f"{self.opensearch_url}/{self.index_name}/_close", timeout=10)

            response = requests.post(
                f"{self.opensearch_url}/_snapshot/{repository_name}/{snapshot_name}/_restore",
                json={
                    "indices": self.index_name,
                    "ignore_unavailable": True,
                    "include_global_state": False,
                },
                timeout=60,
            )

            if response.status_code == 200:
                logger.info(f"Restore from '{snapshot_name}' initiated")
                return True
            else:
                logger.error(f"Failed to restore snapshot: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Failed to restore snapshot: {e}")
            return False

    # Health Check and Verification Methods for Decision Pipeline

    def health_check(self) -> bool:
        """
        Comprehensive health check for OpenSearch connectivity and index status.
        Used by the decision health service.
        """
        if not self.is_enabled:
            logger.debug("OpenSearch is disabled - health check returning False")
            return False

        try:
            # Test basic connectivity
            response = requests.get(
                f"{self.opensearch_url}/_cluster/health", timeout=10
            )
            if response.status_code != 200:
                logger.error(
                    f"OpenSearch cluster health check failed: {response.status_code}"
                )
                return False

            cluster_health = response.json()
            cluster_status = cluster_health.get("status")

            if cluster_status == "red":
                logger.error(f"OpenSearch cluster is in RED state: {cluster_health}")
                return False
            elif cluster_status == "yellow":
                logger.warning(
                    f"OpenSearch cluster is in YELLOW state: {cluster_health}"
                )

            # Test index existence and health
            index_response = requests.get(
                f"{self.opensearch_url}/{self.index_name}/_stats", timeout=10
            )
            if index_response.status_code != 200:
                logger.error(
                    f"Index '{self.index_name}' not accessible: {index_response.status_code}"
                )
                return False

            # Test search functionality
            test_search = self.search_documents("test", size=1)
            if test_search is None:
                logger.error("Search functionality test failed")
                return False

            logger.debug("OpenSearch health check passed")
            return True

        except Exception as e:
            logger.error(f"OpenSearch health check failed with exception: {e}")
            return False

    def document_exists(self, ada: str) -> bool:
        """
        Check if a document with the given ADA exists in OpenSearch.
        Used by decision health checks to verify indexing.
        """
        if not self.is_enabled:
            logger.debug("OpenSearch is disabled - document_exists returning False")
            return False

        try:
            # Use simple term search for ADA (matching the working dev tools query)
            search_body = {
                "query": {"term": {"ada": ada}},
                "size": 1,
                "_source": ["ada"],  # Only return ADA to minimize data transfer
            }

            response = requests.post(
                f"{self.opensearch_url}/{self.index_name}/_search",
                json=search_body,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )

            if response.status_code == 200:
                result = response.json()
                hits = result.get("hits", {}).get("hits", [])
                exists = len(hits) > 0

                if exists:
                    logger.debug(f"Document {ada} exists in OpenSearch")
                else:
                    logger.debug(f"Document {ada} not found in OpenSearch")

                return exists
            else:
                logger.error(
                    f"Failed to check document existence for {ada}: {response.status_code}"
                )
                return False

        except Exception as e:
            logger.error(f"Error checking document existence for {ada}: {e}")
            return False

    def verify_document_searchability(
        self, ada: str, test_queries: List[str] = None
    ) -> Dict[str, Any]:
        """
        Verify that a document is properly indexed and searchable.
        Tests both exact ADA search and content-based searches.

        Args:
            ada: Decision ADA to test
            test_queries: List of queries to test against the document content

        Returns:
            Dictionary with verification results
        """
        if not self.is_enabled:
            logger.debug(
                "OpenSearch is disabled - verify_document_searchability returning negative result"
            )
            return {
                "ada": ada,
                "exists": False,
                "ada_searchable": False,
                "content_searchable": False,
                "test_results": [],
                "issues": ["OpenSearch is disabled via feature flag"],
            }

        verification_result = {
            "ada": ada,
            "exists": False,
            "ada_searchable": False,
            "content_searchable": False,
            "test_results": [],
            "issues": [],
        }

        try:
            # First check if document exists at all
            verification_result["exists"] = self.document_exists(ada)

            if not verification_result["exists"]:
                verification_result["issues"].append("Document not found in index")
                return verification_result

            # Test ADA-based search
            ada_search_results = self.search_documents(ada, size=5)
            if ada_search_results and ada_search_results.get("hits"):
                # Check if our document appears in ADA search results
                ada_found = any(
                    hit.get("ada") == ada for hit in ada_search_results["hits"]
                )
                verification_result["ada_searchable"] = ada_found

                if not ada_found:
                    verification_result["issues"].append(
                        "Document exists but not found in ADA search"
                    )
            else:
                verification_result["issues"].append("ADA search returned no results")

            # Test content-based searches if test queries provided
            if test_queries:
                successful_content_searches = 0

                for query in test_queries:
                    if not query or not query.strip():
                        continue

                    content_results = self.search_documents(query, size=10)
                    if content_results and content_results.get("hits"):
                        query_found = any(
                            hit.get("ada") == ada for hit in content_results["hits"]
                        )

                        test_result = {
                            "query": query,
                            "found": query_found,
                            "total_results": len(content_results["hits"]),
                        }
                        verification_result["test_results"].append(test_result)

                        if query_found:
                            successful_content_searches += 1
                    else:
                        verification_result["test_results"].append(
                            {
                                "query": query,
                                "found": False,
                                "error": "No search results returned",
                            }
                        )

                # Document is content searchable if it appears in at least some queries
                verification_result["content_searchable"] = (
                    successful_content_searches > 0
                )

                if successful_content_searches == 0 and test_queries:
                    verification_result["issues"].append(
                        "Document not found in any content searches"
                    )

            # Overall assessment
            if not verification_result["issues"]:
                logger.info(f"Document {ada} passes all searchability tests")
            else:
                logger.warning(
                    f"Document {ada} has searchability issues: {verification_result['issues']}"
                )

        except Exception as e:
            logger.error(f"Error verifying searchability for {ada}: {e}")
            verification_result["issues"].append(f"Verification failed: {str(e)}")

        return verification_result

    def get_document_by_ada(self, ada: str) -> Dict[str, Any]:
        """
        Retrieve a specific document by ADA for inspection.
        Used for detailed investigation of indexing issues.
        """
        try:
            search_body = {"query": {"term": {"ada.keyword": ada}}, "size": 1}

            response = requests.post(
                f"{self.opensearch_url}/{self.index_name}/_search",
                json=search_body,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )

            if response.status_code == 200:
                result = response.json()
                hits = result.get("hits", {}).get("hits", [])

                if hits:
                    document = hits[0]["_source"]
                    logger.debug(f"Retrieved document {ada} from OpenSearch")
                    return document
                else:
                    logger.warning(f"Document {ada} not found in OpenSearch")
                    return {}
            else:
                logger.error(
                    f"Failed to retrieve document {ada}: {response.status_code}"
                )
                return {}

        except Exception as e:
            logger.error(f"Error retrieving document {ada}: {e}")
            return {}

    def analyze_index_health(self) -> Dict[str, Any]:
        """
        Analyze overall index health and statistics.
        Useful for understanding system-wide indexing issues.
        """
        health_analysis = {
            "index_exists": False,
            "index_name": self.index_name,
            "document_count": 0,
            "index_size": 0,
            "index_size_pretty": "0 B",
            "fields": [],
            "mapping_issues": [],
            "performance_metrics": {},
            "recommendations": [],
        }

        if not self.is_enabled:
            logger.debug(
                "OpenSearch is disabled - analyze_index_health returning empty analysis"
            )
            health_analysis["recommendations"].append(
                "OpenSearch is disabled or unreachable"
            )
            return health_analysis

        try:
            # Check index existence and basic stats
            stats_response = requests.get(
                f"{self.opensearch_url}/{self.index_name}/_stats", timeout=10
            )

            if stats_response.status_code == 200:
                health_analysis["index_exists"] = True
                stats = stats_response.json()

                index_stats = stats.get("indices", {}).get(self.index_name, {})
                primaries = index_stats.get("primaries", {})

                # Document count
                docs = primaries.get("docs", {})
                health_analysis["document_count"] = docs.get("count", 0)

                # Index size
                store = primaries.get("store", {})
                size_bytes = store.get("size_in_bytes", 0)
                health_analysis["index_size"] = size_bytes

                # Format size
                if size_bytes > 0:
                    i = int(math.floor(math.log(size_bytes, 1024)))
                    p = math.pow(1024, i)
                    s = round(size_bytes / p, 2)
                    size_name = ("B", "KB", "MB", "GB", "TB")
                    health_analysis["index_size_pretty"] = f"{s} {size_name[i]}"

                # Performance metrics
                search_stats = primaries.get("search", {})
                health_analysis["performance_metrics"] = {
                    "total_searches": search_stats.get("query_total", 0),
                    "search_time_ms": search_stats.get("query_time_in_millis", 0),
                    "avg_search_time": round(
                        search_stats.get("query_time_in_millis", 0)
                        / max(search_stats.get("query_total", 1), 1),
                        2,
                    ),
                }
            else:
                health_analysis["recommendations"].append(
                    f"Index '{self.index_name}' does not exist or is not accessible"
                )
                return health_analysis

            # Check mapping
            mapping_response = requests.get(
                f"{self.opensearch_url}/{self.index_name}/_mapping", timeout=10
            )

            if mapping_response.status_code == 200:
                mapping = mapping_response.json()
                index_mapping = mapping.get(self.index_name, {}).get("mappings", {})
                properties = index_mapping.get("properties", {})
                health_analysis["fields"] = list(properties.keys())

                # Check for expected fields
                expected_fields = [
                    "ada",
                    "title",
                    "content",
                    "organization",
                    "issue_date",
                ]
                missing_fields = [
                    field for field in expected_fields if field not in properties
                ]

                if missing_fields:
                    health_analysis["mapping_issues"].extend(
                        [f"Missing field mapping: {field}" for field in missing_fields]
                    )

            # Generate recommendations
            if health_analysis["document_count"] == 0:
                health_analysis["recommendations"].append(
                    "Index is empty - check document indexing process"
                )

            if health_analysis["index_size"] > 10 * 1024 * 1024 * 1024:  # 10GB
                health_analysis["recommendations"].append(
                    "Index is very large - consider optimization"
                )

            avg_search_time = health_analysis["performance_metrics"].get(
                "avg_search_time", 0
            )
            if avg_search_time > 1000:  # More than 1 second average
                health_analysis["recommendations"].append(
                    "Search performance is slow - consider optimization"
                )

            logger.info(f"Index health analysis completed for '{self.index_name}'")

        except Exception as e:
            logger.error(f"Error analyzing index health: {e}")
            health_analysis["recommendations"].append(
                f"Health analysis failed: {str(e)}"
            )

        return health_analysis
