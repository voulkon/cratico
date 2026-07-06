"""
Security monitoring service.

Centralizes all threat-detection logic so it can be called from middleware
and tested in isolation. All state lives in Redis (fast, ephemeral) — the
FlaggedIP DB table is the persistent record, written only when an IP is
banned or manually flagged.

Detection signals (all per-IP, all in Redis):
    - velocity:   requests per rolling 60s window
    - scan:       distinct endpoints hit in rolling 5min window
    - errors:     4xx/5xx responses in rolling 5min window
    - strikes:    security-pattern matches (from security.py) in rolling 1h window

Enforcement:
    - When SECURITY_AUTO_BAN_ENABLED, IPs crossing any threshold are added
      to the Redis banned set (sorted by expiry timestamp) and a FlaggedIP
      record is created in the DB.
    - The middleware checks the banned set on every request (O(log n) ZRANGEBYSCORE).
"""

from __future__ import annotations

import time
from typing import Optional
from datetime import timedelta
from django.utils import timezone
from django_redis import get_redis_connection
from loguru import logger

from api.redis_keys import (
    SECURITY_BANNED_SET,
    SECURITY_ERRORS_WINDOW,
    SECURITY_FLAGGED_SET,
    SECURITY_FLAGGED_WINDOW,
    SECURITY_SCAN_WINDOW,
    SECURITY_STRIKES_PREFIX,
    SECURITY_STRIKES_WINDOW,
    SECURITY_VELOCITY_PREFIX,
    SECURITY_VELOCITY_WINDOW,
    get_errors_key,
    get_scan_key,
    get_strikes_key,
    get_velocity_key,
)


class SecurityService:
    """Stateless service — all state lives in Redis."""

    def __init__(self):
        self._redis = None

    @property
    def redis(self):
        """Lazy Redis connection — avoids connection at import time."""
        if self._redis is None:
            self._redis = get_redis_connection("default")
        return self._redis

    # ── Public API ──────────────────────────────────────────────────

    def is_banned(self, ip: str) -> bool:
        """Check if an IP is currently banned (Redis fast path)."""
        if not ip:
            return False
        # Remove expired bans lazily
        now = time.time()
        self.redis.zremrangebyscore(SECURITY_BANNED_SET, 0, now)
        return bool(self.redis.zscore(SECURITY_BANNED_SET, ip))

    def ban_ip(
        self,
        ip: str,
        reason: str,
        strike_count: int = 0,
        duration_hours: Optional[int] = None,
    ) -> None:
        """
        Ban an IP: add to Redis banned set + create/update FlaggedIP record.

        Args:
            ip: The IP address to ban.
            reason: One of FlaggedIP.FlagReason values.
            strike_count: Number of strikes that triggered the ban.
            duration_hours: Ban duration. None = use flag default. 0 = permanent.
        """
        if not ip:
            return

        from api.models import FlaggedIP

        # Resolve duration from feature flag if not specified
        if duration_hours is None:
            from core.services.feature_flag_service import feature_flags

            duration_hours = feature_flags.get_value("SECURITY_BAN_DURATION_HOURS", 24)

        # Add to Redis banned set (score = expiry timestamp; 0 = never expires)
        if duration_hours and duration_hours > 0:
            expiry_ts = time.time() + (duration_hours * 3600)
        else:
            expiry_ts = float("inf")  # permanent ban
        self.redis.zadd(SECURITY_BANNED_SET, {ip: expiry_ts})

        # Also add to flagged set so forensic logging kicks in
        self._flag_for_forensics(ip)

        # Persist to DB
        existing = FlaggedIP.objects.filter(ip_address=ip).first()
        is_recurring = existing is not None
        flag_reason = reason  # Preserve the real reason; is_recurring is tracked separately.

        # Preserve admin notes — prepend recurring notice if needed.
        existing_notes = existing.notes if existing else ""
        if is_recurring and "Recurring" not in existing_notes:
            notes_final = f"Recurring offender (repeat ban). {existing_notes}".strip()
        else:
            notes_final = existing_notes

        obj, created = FlaggedIP.objects.update_or_create(
            ip_address=ip,
            defaults={
                "reason": flag_reason,
                "is_active": True,
                "strike_count": strike_count,
                "notes": notes_final,
                "ban_expires_at": (
                    timezone.now() + timedelta(hours=duration_hours)
                    if duration_hours and duration_hours > 0
                    else None
                ),
            },
        )
        logger.warning(
            f"IP {ip} banned (reason={flag_reason}, strikes={strike_count}, "
            f"duration={'permanent' if not duration_hours else f'{duration_hours}h'}, "
            f"{'new' if created else 'updated'})"
        )

    def unban_ip(self, ip: str) -> bool:
        """Remove an IP from the ban set and deactivate the FlaggedIP record."""
        removed = self.redis.zrem(SECURITY_BANNED_SET, ip)
        self.redis.zrem(SECURITY_FLAGGED_SET, ip)

        from api.models import FlaggedIP

        updated = FlaggedIP.objects.filter(ip_address=ip, is_active=True).update(
            is_active=False,
            ban_expires_at=None,  # Clear expiry so admin UI doesn't show stale date.
        )
        logger.info(f"IP {ip} unbanned (redis_removed={removed}, db_updated={updated})")
        return bool(removed or updated)

    def is_flagged_for_forensics(self, ip: str) -> bool:
        """Check if an IP should have all its requests logged to DB."""
        if not ip:
            return False
        # Lazy cleanup: evict members whose forensic window has expired.
        self.redis.zremrangebyscore(SECURITY_FLAGGED_SET, 0, time.time())
        return bool(self.redis.zscore(SECURITY_FLAGGED_SET, ip))

    def _flag_for_forensics(self, ip: str) -> None:
        """Add IP to forensic capture set with per-member TTL.

        Score = expiry timestamp (now + SECURITY_FLAGGED_WINDOW).
        Re-flagging an already-flagged IP overwrites the score,
        naturally extending the observation window.
        """
        expiry = time.time() + SECURITY_FLAGGED_WINDOW
        self.redis.zadd(SECURITY_FLAGGED_SET, {ip: expiry})

    # ── Signal recording (called by middleware) ────────────────────

    def record_signals(self, ip: str, endpoint: str, is_error: bool = False) -> None:
        """Record velocity + scan (+ optionally error) in a single pipeline round-trip.

        Uses EXPIRE … NX to seed the TTL only on key creation, producing a
        true rolling window: the key expires WINDOW seconds after the *first*
        request in the window, not after the *last* request (which would let
        a low-rate attacker keep the counter alive indefinitely by sending
        one request just before the previous TTL elapses).
        """
        if not ip:
            return
        pipe = self.redis.pipeline()
        # Velocity: only set TTL when the key is first created (NX)
        vel_key = get_velocity_key(ip)
        pipe.incr(vel_key)
        pipe.expire(vel_key, SECURITY_VELOCITY_WINDOW, nx=True)
        # Scan detection
        scan_key = get_scan_key(ip)
        pipe.sadd(scan_key, endpoint)
        pipe.expire(scan_key, SECURITY_SCAN_WINDOW, nx=True)
        # Error rate (optional)
        if is_error:
            err_key = get_errors_key(ip)
            pipe.incr(err_key)
            pipe.expire(err_key, SECURITY_ERRORS_WINDOW, nx=True)
        pipe.execute()

    def record_strike(self, ip: str, event_type: str = "security") -> int:
        """
        Record a security-pattern strike (SQLi/XSS/etc from security.py).

        Returns the new strike count for this IP.
        """
        if not ip:
            return 0
        strikes_key = get_strikes_key(ip)
        pipe = self.redis.pipeline()
        pipe.incr(strikes_key)
        pipe.expire(strikes_key, SECURITY_STRIKES_WINDOW, nx=True)
        pipe.execute()
        count = int(self.redis.get(strikes_key) or 0)
        logger.warning(
            f"Security strike recorded for {ip}: {event_type} (count={count})"
        )
        return count

    # ── Threshold evaluation ────────────────────────────────────────

    def evaluate_threats(self, ip: str) -> Optional[str]:
        """
        Check all threat signals for an IP. Returns the first triggered
        reason (FlaggedIP.FlagReason value) or None if clean.

        Called after record_request() / record_error() / record_strike()
        so the counters are fresh.
        """
        if not ip:
            return None

        from core.services.feature_flag_service import feature_flags

        # 1. Velocity check
        vel_key = get_velocity_key(ip)
        velocity = int(self.redis.get(vel_key) or 0)
        vel_threshold = feature_flags.get_value("SECURITY_VELOCITY_THRESHOLD", 120)
        if velocity >= vel_threshold:
            return "velocity"

        # 2. Strike check
        strikes_key = get_strikes_key(ip)
        strikes = int(self.redis.get(strikes_key) or 0)
        strike_threshold = feature_flags.get_value("SECURITY_STRIKE_THRESHOLD", 5)
        if strikes >= strike_threshold:
            return "strikes"

        # 3. Scan detection: distinct-endpoint count exceeds threshold
        scan_key = get_scan_key(ip)
        distinct_endpoints = self.redis.scard(scan_key)
        scan_threshold = feature_flags.get_value("SECURITY_SCAN_THRESHOLD", 50)
        if distinct_endpoints >= scan_threshold:
            return "scan"

        # 4. Error rate: 4xx/5xx count exceeds threshold
        err_key = get_errors_key(ip)
        errors = int(self.redis.get(err_key) or 0)
        error_threshold = feature_flags.get_value("SECURITY_ERROR_THRESHOLD", 40)
        if errors >= error_threshold:
            return "errors"

        return None

    # ── Dashboard helpers (used by admin views) ────────────────────

    def get_top_velocity_ips(self, limit: int = 20):
        """Get IPs with highest current velocity (uses SCAN, not KEYS)."""
        results = []
        for key in self.redis.scan_iter(match=f"{SECURITY_VELOCITY_PREFIX}*"):
            # Strip the known prefix to get the IP — safe for IPv6 (avoids split on ':').
            ip = key.decode("utf-8")[len(SECURITY_VELOCITY_PREFIX):]
            count = int(self.redis.get(key) or 0)
            if count > 0:
                results.append((ip, count))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    def get_top_strike_ips(self, limit: int = 20):
        """Get IPs with most security strikes (uses SCAN, not KEYS)."""
        results = []
        for key in self.redis.scan_iter(match=f"{SECURITY_STRIKES_PREFIX}*"):
            # Strip the known prefix to get the IP — safe for IPv6 (avoids split on ':').
            ip = key.decode("utf-8")[len(SECURITY_STRIKES_PREFIX):]
            count = int(self.redis.get(key) or 0)
            if count > 0:
                results.append((ip, count))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    def get_banned_ips(self):
        """Get all currently-banned IPs with expiry."""
        now = time.time()
        # Clean expired
        self.redis.zremrangebyscore(SECURITY_BANNED_SET, 0, now)
        banned = self.redis.zrange(SECURITY_BANNED_SET, 0, -1, withscores=True)
        results = []
        for ip_bytes, expiry_ts in banned:
            ip = ip_bytes.decode("utf-8")
            if expiry_ts == float("inf"):
                expiry = "permanent"
            else:
                from datetime import datetime

                expiry = datetime.fromtimestamp(expiry_ts).strftime("%Y-%m-%d %H:%M")
            results.append((ip, expiry))
        return results


# Singleton
security_service = SecurityService()
