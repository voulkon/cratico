"""
Central registry of Redis keys used throughout the application.
"""

# Key namespaces
STATS_NS = "stats"
RATELIMIT_NS = "ratelimit"
IMPORT_CHUNKS_NS = "import"  # Import decision chunks namespace
IMPORT_JOB_QUEUE_NS = "import_job_queue"  # Import job queue namespace

# Stats keys
TOTAL_REQUESTS = f"{STATS_NS}:total_requests"
UNIQUE_IPS = f"{STATS_NS}:unique_ips"
HOURLY_STATS = f"{STATS_NS}:hourly"
DAILY_STATS = f"{STATS_NS}:daily"
ENDPOINT_PREFIX = f"{STATS_NS}:endpoint:"
METHOD_PREFIX = f"{STATS_NS}:method:"
USER_AGENTS = f"{STATS_NS}:user_agents"

# IP tracking keys (for user journey analysis)
IP_ENDPOINTS_PREFIX = f"{STATS_NS}:ip:"  # stats:ip:<ip>:endpoints
ENDPOINT_IPS_PREFIX = f"{STATS_NS}:endpoint_ips:"  # stats:endpoint_ips:<endpoint>

# Rate limit keys
USER_RATELIMIT_PREFIX = f"{RATELIMIT_NS}:user:"
IP_RATELIMIT_PREFIX = f"{RATELIMIT_NS}:ip:"

# Import decision chunks keys
IMPORT_CHUNK_PREFIX = f"{IMPORT_CHUNKS_NS}:chunk:"  # import:chunk:<job_id>_chunk_<n>
IMPORT_JOB_METADATA_PREFIX = f"{IMPORT_CHUNKS_NS}:job:"  # import:job:<job_id>

#  Import job queue keys
IMPORT_JOB_QUEUE_PENDING = f"{IMPORT_JOB_QUEUE_NS}:pending"
IMPORT_JOB_QUEUE_ACTIVE = f"{IMPORT_JOB_QUEUE_NS}:active"
IMPORT_JOB_QUEUE_LOCK = f"{IMPORT_JOB_QUEUE_NS}:lock"

# Default expiration times (in seconds)
STATS_EXPIRE = 60 * 60 * 24 * 30  # 30 days
RATELIMIT_EXPIRE = 60 * 60 * 24  # 24 hours
IMPORT_CHUNKS_EXPIRE = (
    60 * 60 * 24 * 3
)  # 72 hours (3 days) - allows for queued jobs and slow processing

# AFM Fetch Locking (distributed lock for company data fetching)
AFM_FETCH_LOCK_PREFIX = "afm_fetch_lock:"
AFM_FETCH_LOCK_TIMEOUT = 60 * 45  # 45 minutes lock timeout

# AFM Fetch Queue (priority-based queue for company data fetching)
AFM_FETCH_QUEUE_NS = "afm_fetch_queue"
AFM_FETCH_QUEUE_PENDING = (
    f"{AFM_FETCH_QUEUE_NS}:pending"  # Sorted set (score = priority)
)
AFM_FETCH_QUEUE_ACTIVE = f"{AFM_FETCH_QUEUE_NS}:active"  # Set of AFMs being processed
AFM_FETCH_QUEUE_FETCHED = (
    f"{AFM_FETCH_QUEUE_NS}:fetched"  # Set of successfully fetched AFMs
)
AFM_FETCH_QUEUE_FAILED = f"{AFM_FETCH_QUEUE_NS}:failed"  # Set of failed AFMs
AFM_FETCH_QUEUE_IGNORED = f"{AFM_FETCH_QUEUE_NS}:ignored"  # Set of AFMs below threshold
AFM_FETCH_QUEUE_LOCK = f"{AFM_FETCH_QUEUE_NS}:lock"  # Global queue processing lock
AFM_FETCH_QUEUE_STATS = f"{AFM_FETCH_QUEUE_NS}:stats"  # Hash of queue statistics

# Search History (personal search tracking)
SEARCH_HISTORY_NS = "search_history"
SEARCH_HISTORY_USER_PREFIX = (
    f"{SEARCH_HISTORY_NS}:user:"  # search_history:user:<user_id>
)
SEARCH_HISTORY_IP_PREFIX = f"{SEARCH_HISTORY_NS}:ip:"  # search_history:ip:<ip_address>
SEARCH_HISTORY_EXPIRE = 60 * 60 * 24 * 90  # 90 days (recent searches)

PREREQUISITE_CHECK_CACHE_PREFIX = "prerequisite:postgres_fts"
PREREQUISITE_CHECK_CACHE_MIGRATION = f"{PREREQUISITE_CHECK_CACHE_PREFIX}:migration"
PREREQUISITE_CHECK_CACHE_BACKFILL_STATUS = f"{PREREQUISITE_CHECK_CACHE_PREFIX}:backfill_status"
PREREQUISITE_CHECK_CACHE_FULL_CHECK = f"{PREREQUISITE_CHECK_CACHE_PREFIX}:full_check"

# API Response Cache (cached view responses for expensive queries)
API_CACHE_NS = "api_cache"
API_CACHE_DA_PREFIX = f"{API_CACHE_NS}:da:"  # api_cache:da:<view>:<params>
API_CACHE_EXPIRE_HISTORICAL = 60 * 60 * 24  # 24 hours (past data won't change)
API_CACHE_EXPIRE_CURRENT = 60 * 5  # 5 minutes (current data may update)
API_CACHE_EXPIRE_STATS = 60 * 10  # 10 minutes (stats change slowly)

# Warmup status tracking (defer_on_miss)
WARMUP_STATUS_PREFIX = "warmup:"
WARMUP_STATUS_TTL = 120  # 2 min — if warmup takes longer, something is wrong

FEATURE_FLAG_PREFIX = "feature_flag"

# Browse API (alphabetical entity browsing)
BROWSE_NS = "browse"
BROWSE_AVAILABLE_LETTERS_PREFIX = f"{BROWSE_NS}:available_letters:"  # browse:available_letters:<entity_type>
BROWSE_CACHE_TIMEOUT = 300  # 5 minutes

def get_endpoint_key(endpoint):
    """Get the Redis key for endpoint stats"""
    return f"{ENDPOINT_PREFIX}{endpoint}"


def get_method_key(method):
    """Get the Redis key for HTTP method stats"""
    return f"{METHOD_PREFIX}{method}"


def get_user_ratelimit_key(user_id):
    """Get the Redis key for user rate limiting"""
    return f"{USER_RATELIMIT_PREFIX}{user_id}"


def get_ip_ratelimit_key(ip):
    """Get the Redis key for IP rate limiting"""
    return f"{IP_RATELIMIT_PREFIX}{ip}"


def get_ip_endpoints_key(ip: str) -> str:
    """Generate Redis key for tracking endpoints visited by an IP"""
    return f"{IP_ENDPOINTS_PREFIX}{ip}:endpoints"


def get_endpoint_ips_key(endpoint: str) -> str:
    """Generate Redis key for tracking IPs that visited an endpoint"""
    return f"{ENDPOINT_IPS_PREFIX}{endpoint}"


# 🆕 Import chunk key helpers
def get_import_chunk_key(chunk_id: str) -> str:
    """Generate Redis key for storing decision chunk data"""
    return f"{IMPORT_CHUNK_PREFIX}{chunk_id}"


def get_import_job_metadata_key(job_id: int) -> str:
    """Generate Redis key for storing import job metadata"""
    return f"{IMPORT_JOB_METADATA_PREFIX}{job_id}"


# [SCAN] Search history key helpers
def get_user_search_history_key(user_id: int) -> str:
    """Generate Redis key for storing user's search history"""
    return f"{SEARCH_HISTORY_USER_PREFIX}{user_id}"


def get_ip_search_history_key(ip_address: str) -> str:
    """Generate Redis key for storing IP's search history"""
    return f"{SEARCH_HISTORY_IP_PREFIX}{ip_address}"


# [DB]️ API Response Cache key helpers
def get_api_cache_key(view_name: str, **params) -> str:
    """
    Generate a deterministic Redis key for a cached API response.

    Args:
        view_name: Short identifier for the view (e.g., "da:top_pairs")
        **params: Query parameters that affect the response (sorted for determinism)

    Returns:
        Redis key string, e.g., "api_cache:da:top_pairs:end=2025-12-31:limit=6:start=2025-01-01"
    """
    parts = [API_CACHE_DA_PREFIX, view_name]
    for key, value in sorted(params.items()):
        parts.append(f"{key}={value}")
    return ":".join(parts)


def get_warmup_status_key(cache_key: str) -> str:
    """
    Convert a standard API cache key to its warmup-status tracking key.

    Args:
        cache_key: A key from get_api_cache_key(), e.g.
                   "api_cache:da:explore_orgs:end_date=2025-12-31:..."

    Returns:
        Warmup status key, e.g. "warmup:api_cache:da:explore_orgs:end_date=2025-12-31:..."
    """
    return f"{WARMUP_STATUS_PREFIX}{cache_key}"
