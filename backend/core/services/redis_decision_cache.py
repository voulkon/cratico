"""
Redis-based Decision Caching Service

Replaces the filesystem-based pickle approach with Redis for temporary storage
of decision data between fetch and processing tasks.

Benefits:
- No risk of lost files due to container restarts
- Atomic operations prevent race conditions
- Automatic expiration prevents storage bloat
- Shared access across all workers

Redis DB Usage:
- DB 0: Celery results (CELERY_RESULT_BACKEND)
- DB 1: Django cache (CACHES['default'])
- DB 2: Import decision chunks (this service) [OK]
"""

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

# Import centralized Redis key functions
from api.redis_keys import (
    IMPORT_CHUNK_PREFIX,
    IMPORT_CHUNKS_EXPIRE,
    get_import_chunk_key,
    get_import_chunk_scan_pattern,
    get_import_chunk_state_key,
    get_import_job_metadata_key,
)
from diavgeia_project.settings.constants import IMPORT_CHUNKS_REDIS_DB_NAME
from django_redis import get_redis_connection
from loguru import logger


class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles datetime, date, and Decimal objects"""

    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def parse_chunk_index(chunk_id: str) -> Optional[int]:
    """Extract ``N`` from a chunk ID formatted as ``<job_id>_chunk_<N>``."""
    _, separator, index = chunk_id.rpartition("_chunk_")
    if not separator:
        return None
    try:
        return int(index)
    except ValueError:
        return None


def _chunk_index_sort_key(chunk_id: str):
    index = parse_chunk_index(chunk_id)
    return (index is None, index if index is not None else 0, chunk_id)


class RedisDecisionCache:
    """
    Manages temporary storage of decision data in Redis during the import pipeline.

    Data flow:
    1. fetch_daily_decisions_to_redis creates chunks and stores in Redis
    2. store_decisions_from_redis reads from Redis, processes, and deletes
    """

    # Use dedicated DB to avoid conflicts with Celery (DB 0) and Django cache (DB 1)
    REDIS_DB = 2

    def __init__(self):
        """Initialize Redis connection using Django's connection pool"""
        # Reuse Django's connection pool for DB 2 (import_chunks)
        # This prevents connection exhaustion and resource leaks
        self.redis_client = get_redis_connection(IMPORT_CHUNKS_REDIS_DB_NAME)

        logger.debug(
            f"Redis decision cache connected via connection pool "
            f"DB {self.REDIS_DB} (dedicated for import chunks)"
        )

    def store_chunk(
        self,
        chunk_id: str,
        decisions: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
        ttl_seconds: int = IMPORT_CHUNKS_EXPIRE,
    ) -> str:
        """
        Store a chunk of decisions in Redis using centralized key format.

        Args:
            chunk_id: Unique identifier for this chunk (e.g., "123_chunk_5")
            decisions: List of decision DTOs (as dicts)
            metadata: Optional metadata about the chunk
            ttl_seconds: Time to live in seconds (default: 24 hours)

        Returns:
            Redis key where data was stored
        """
        key = get_import_chunk_key(chunk_id)  # [SECURE] Centralized key generation

        # Convert Decision DTOs to dictionaries for JSON serialization
        decision_dicts = [
            d.model_dump() if hasattr(d, "model_dump") else d for d in decisions
        ]

        data = {
            "decisions": decision_dicts,
            "metadata": metadata or {},
            "chunk_id": chunk_id,
            "decision_count": len(decisions),
        }

        try:
            # Serialize to JSON with datetime handling
            serialized = json.dumps(data, cls=DateTimeEncoder)
            self.redis_client.setex(key, ttl_seconds, serialized)

            logger.debug(f"[PKG] Stored {len(decisions)} decisions in Redis: {key}")
            return key

        except Exception as e:
            logger.error(f"[ERROR] Failed to store chunk {chunk_id} in Redis: {e}")
            raise

    def get_chunk(
        self, chunk_id: str, delete_after_read: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve a chunk of decisions from Redis using centralized key format.

        Args:
            chunk_id: Unique identifier for the chunk
            delete_after_read: If True, delete the key after reading.  The
                import task must NOT do this before the work succeeds: the
                chunk payload is the only copy of the fetched decisions.

        Returns:
            Dict with 'decisions' and 'metadata', or None if not found
        """
        key = get_import_chunk_key(chunk_id)  # [SECURE] Centralized key generation

        try:
            # Get data
            data = self.redis_client.get(key)

            if not data:
                logger.warning(f"[WARN]️ Chunk not found in Redis: {key}")
                return None

            # Deserialize
            chunk_data = json.loads(data)

            # Note: Dates come back as ISO strings - convert if needed
            # For now, leave them as strings since Pydantic will handle conversion
            # when you create Decision objects from the dicts

            logger.debug(
                f"[IMPORT] Retrieved {chunk_data['decision_count']} decisions from Redis: {key}"
            )

            # Optionally delete (consume pattern)
            if delete_after_read:
                self.redis_client.delete(key)
                logger.debug(f"[PURGE]️ Deleted chunk from Redis: {key}")

            return chunk_data

        except Exception as e:
            logger.error(f"[ERROR] Failed to retrieve chunk {chunk_id} from Redis: {e}")
            raise

    def chunk_exists(self, chunk_id: str) -> bool:
        """Check if a chunk exists in Redis"""
        key = get_import_chunk_key(chunk_id)
        return bool(self.redis_client.exists(key))

    def delete_chunk(self, chunk_id: str) -> bool:
        """Manually delete a chunk"""
        key = get_import_chunk_key(chunk_id)
        deleted = self.redis_client.delete(key)
        return bool(deleted)

    # ── Per-chunk accounting ─────────────────────────────────────────
    # Completion is recorded independently of the two DB counters.  This
    # makes redelivery idempotent and lets the watchdog know which chunks are
    # genuinely missing rather than merely unreported.
    def mark_chunk_state(
        self, job_id: int, chunk_index: Optional[int], outcome: str = "completed"
    ) -> bool:
        """Record a chunk's terminal outcome.

        Returns True the first time this ``(job_id, chunk_index)`` pair is
        recorded, False when the chunk was already accounted for (i.e. this is
        a duplicate delivery and the caller must not increment a counter).
        """
        if chunk_index is None:
            # Legacy payload without a chunk_index: cannot de-duplicate.
            return True

        key = get_import_chunk_state_key(job_id)
        try:
            added = self.redis_client.hsetnx(key, str(chunk_index), outcome)
            self.redis_client.expire(key, IMPORT_CHUNKS_EXPIRE)
            return bool(added)
        except Exception as e:
            logger.error(f"[ERROR] Failed to record chunk state {job_id}/{chunk_index}: {e}")
            # Fail open: better to risk a duplicate counter than lose a chunk.
            return True

    def get_chunk_state(self, job_id: int, chunk_index: Optional[int]) -> Optional[str]:
        """Return ``completed``/``failed`` for a chunk, or None if unknown."""
        if chunk_index is None:
            return None
        key = get_import_chunk_state_key(job_id)
        value = self.redis_client.hget(key, str(chunk_index))
        if value is None:
            return None
        return value.decode("utf-8") if isinstance(value, bytes) else value

    def get_job_chunk_states(self, job_id: int) -> Dict[int, str]:
        """Return ``{chunk_index: outcome}`` for every accounted chunk."""
        key = get_import_chunk_state_key(job_id)
        raw = self.redis_client.hgetall(key) or {}
        states: Dict[int, str] = {}
        for field, value in raw.items():
            try:
                index = int(field.decode("utf-8") if isinstance(field, bytes) else field)
            except (TypeError, ValueError):
                continue
            states[index] = value.decode("utf-8") if isinstance(value, bytes) else value
        return states

    def clear_chunk_state(self, job_id: int, chunk_index: Optional[int]) -> None:
        """Forget a chunk's outcome so a manual retry can record it again."""
        if chunk_index is None:
            return
        self.redis_client.hdel(get_import_chunk_state_key(job_id), str(chunk_index))

    def list_job_chunk_ids(self, job_id: int) -> List[str]:
        """List the chunk IDs (without the Redis prefix) still stored for a job.

        The pattern always comes from :func:`api.redis_keys.get_import_chunk_key`
        via :func:`get_import_chunk_scan_pattern`, so diagnostics can never
        drift onto a stale namespace.
        """
        pattern = get_import_chunk_scan_pattern(job_id)
        cursor = 0
        chunk_ids: List[str] = []

        while True:
            cursor, keys = self.redis_client.scan(
                cursor=cursor, match=pattern, count=100
            )
            for key in keys:
                key_str = key.decode("utf-8") if isinstance(key, bytes) else key
                chunk_ids.append(key_str[len(IMPORT_CHUNK_PREFIX) :])
            if cursor == 0:
                break

        return sorted(chunk_ids, key=_chunk_index_sort_key)

    def store_job_metadata(
        self,
        job_id: int,
        metadata: Dict[str, Any],
        ttl_seconds: int = IMPORT_CHUNKS_EXPIRE,
    ):
        """
        Store metadata about an import job using centralized key format.

        This is separate from the Django model and provides quick Redis-based lookup.
        Useful for checking "is this job already running?" before creating tasks.
        """
        key = get_import_job_metadata_key(job_id)  # [SECURE] Centralized key generation

        try:
            serialized = json.dumps(metadata, cls=DateTimeEncoder)
            self.redis_client.setex(key, ttl_seconds, serialized)
            logger.debug(f"[COPY] Stored job metadata: {key}")
        except Exception as e:
            logger.error(f"[ERROR] Failed to store job metadata {job_id}: {e}")
            raise

    def get_job_metadata(self, job_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve job metadata using centralized key format"""
        key = get_import_job_metadata_key(job_id)

        try:
            data = self.redis_client.get(key)
            if not data:
                return None
            return json.loads(data)
        except Exception as e:
            logger.error(f"[ERROR] Failed to retrieve job metadata {job_id}: {e}")
            return None

    def cleanup_job(self, job_id: int):
        """
        Clean up all Redis keys associated with an import job.

        Call this after all chunks have been processed (or if job fails).
        """
        # Delete job metadata
        job_key = get_import_job_metadata_key(job_id)
        self.redis_client.delete(job_key)

        # Delete per-chunk accounting state
        self.redis_client.delete(get_import_chunk_state_key(job_id))

        # Find and delete all chunk keys for this job
        # Pattern: import:chunk:{job_id}_chunk_*
        pattern = get_import_chunk_scan_pattern(job_id)
        cursor = 0
        deleted_count = 0

        while True:
            cursor, keys = self.redis_client.scan(
                cursor=cursor, match=pattern, count=100
            )

            if keys:
                deleted_count += self.redis_client.delete(*keys)

            if cursor == 0:
                break

        logger.info(f"[CLEAN] Cleaned up {deleted_count} chunk keys for job {job_id}")
        return deleted_count

    def get_job_stats(self, job_id: int) -> Dict[str, Any]:
        """
        Get statistics about a job's chunks in Redis.

        Returns:
            Dict with counts of stored chunks
        """
        pattern = get_import_chunk_scan_pattern(job_id)
        cursor = 0
        chunk_count = 0

        while True:
            cursor, keys = self.redis_client.scan(
                cursor=cursor, match=pattern, count=100
            )
            chunk_count += len(keys)

            if cursor == 0:
                break

        return {
            "job_id": job_id,
            "chunks_in_redis": chunk_count,
        }

    def get_chunk_ttl(self, chunk_id: str) -> Optional[int]:
        """
        Get remaining TTL (time to live) for a chunk in seconds.

        Returns:
            Seconds until expiration, or None if chunk doesn't exist
            -1 if chunk has no expiration set (shouldn't happen)
        """
        key = get_import_chunk_key(chunk_id)
        ttl = self.redis_client.ttl(key)

        if ttl == -2:  # Key doesn't exist
            return None
        return ttl

    def get_job_ttl_stats(self, job_id: int, sample_size: int = 10) -> Dict[str, Any]:
        """
        Get TTL statistics for a job's chunks (samples first N chunks).

        This helps diagnose if chunks are at risk of expiring before processing.

        Args:
            job_id: Import job ID
            sample_size: Number of chunks to sample (default: 10)

        Returns:
            Dict with min/max/avg TTL remaining in seconds
        """
        pattern = get_import_chunk_scan_pattern(job_id)

        # Scan for chunk keys
        cursor, keys = self.redis_client.scan(
            cursor=0, match=pattern, count=sample_size
        )

        if not keys:
            return {"job_id": job_id, "error": "No chunks found in Redis"}

        # Get TTL for each sampled chunk
        ttls = []
        for key in keys[:sample_size]:
            ttl = self.redis_client.ttl(key)
            if ttl > 0:  # -1 = no expiration, -2 = doesn't exist
                ttls.append(ttl)

        if not ttls:
            return {
                "job_id": job_id,
                "chunks_sampled": len(keys),
                "error": "No valid TTLs found",
            }

        return {
            "job_id": job_id,
            "chunks_sampled": len(ttls),
            "ttl_min_seconds": min(ttls),
            "ttl_max_seconds": max(ttls),
            "ttl_avg_seconds": sum(ttls) / len(ttls),
            "ttl_min_hours": min(ttls) / 3600,
            "ttl_max_hours": max(ttls) / 3600,
            "ttl_avg_hours": (sum(ttls) / len(ttls)) / 3600,
        }
