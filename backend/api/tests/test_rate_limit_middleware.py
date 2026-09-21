"""
Tests for RateLimitMiddleware (backend/api/middleware/rate_limit.py).

The limiter must actually RUN behind the compose/Cloudflare gateway (the
"local/private" exemption is decided from the RESOLVED client IP only, not from
nginx's REMOTE_ADDR), and the anonymous daily limit must resolve through the
ANON_API_DAILY_LIMIT FeatureFlag whose default is the ANON_API_DAILY_LIMIT
setting (so deployments keep the env knob while an admin can override live).

Cases:

  1. DEBUG=True -> never 429, no X-RateLimit-* headers (existing dev behavior).
  2. REMOTE_ADDR=172.20.0.5 with no forwarded header -> exempt (infra gateway):
     HTTP 200 with no X-RateLimit-* headers.
  3. Public synthetic client behind a private gateway (X-Forwarded-For) ->
     enforcement ACTIVE: N requests return 200 with decreasing
     X-RateLimit-Remaining; request N+1 returns 429 JSON with Remaining: 0 and
     X-RateLimit-Limit == the ANON_API_DAILY_LIMIT setting.
  4. Exempt paths (/api/auth/*, /system/rate-limit/*) never 429 once throttled.
  5. A second client IP is independent (its own bucket).
  6. The anonymous cap is registered as an integer FeatureFlag, and a flag
     override (admin) takes precedence over the settings default.
  7. Token-authenticated traffic is billed to the per-USER bucket.  The SPA
     sends `Authorization: Token <key>` (see frontend/src/api/client.js), which
     Django's session-only AuthenticationMiddleware cannot see — before the fix
     every logged-in SPA request looked anonymous and burned the per-IP cap.
     Staff tokens are exempt like staff sessions.
  8. Safe reads of the SPA's boot/widget endpoints do NOT consume quota, while
     writes on those same paths still do.  The not-counted set is exactly
     security_service.is_noisy_endpoint (the list the threat layer already
     ignores so browsing cannot self-ban).

Strategy mirrors test_security_monitoring_middleware.py: run through the real
Django middleware stack with django.test.Client (the redis-backed cache is the
rate-limit store, and the conftest autouse clear_rate_limit_cache fixture gives
each test a clean slate). Feature flags are pinned off so stealth/security
middleware never interfere; the anonymous-cap FeatureFlag resolves to the
settings default because the test DB has no FeatureFlag row and the env var is
unset.

"""

from contextlib import contextmanager
from unittest.mock import patch

import core.services.feature_flag_service as ffs
import pytest
from django.core.cache import cache
from django.test import Client, override_settings

from api.redis_keys import get_ip_ratelimit_key, get_user_ratelimit_key

# Counted endpoint for enforcement tests: a trivial, always-200, non-DRF view
# that is neither an exempt path nor "noisy" boot chatter.  (/api/system/config/
# auth/ was used here before the boot-chatter carve-out, and is now not
# counted — same for /api/auth/me/.)
API_PATH = "/api/version/"

# Boot/widget paths the SPA calls on every page: not counted when read.
NOISY_READ_PATH = "/api/system/config/auth/"
# ...but a mutating method on a noisy path still consumes quota.
NOISY_WRITE_PATH = "/api/user-data/bookmarks/"

# docker-compose nginx -> backend gateway (private, was the old false trigger).
GATEWAY_REMOTE_ADDR = "172.20.0.5"
# Truly public synthetic clients (documentation ranges like 198.51.100.0/24 are
# is_private=True in ipaddress, so they would count as "infrastructure").
PUBLIC_CLIENT_A = "8.8.8.8"
PUBLIC_CLIENT_B = "1.1.1.1"

# Turn DEBUG off so the limiter actually runs and wildcard ALLOWED_HOSTS so the
# test client's "testserver" Host header is accepted.
ENFORCED = dict(DEBUG=False, ALLOWED_HOSTS=["*"])
# Same, with a small tunable anonymous limit so a burst reaches 429 quickly.
from api.constants import DEFAULT_ANON_API_DAILY_LIMIT
ENFORCED_LIMIT_3 = dict(ENFORCED, ANON_API_DAILY_LIMIT=DEFAULT_ANON_API_DAILY_LIMIT)

FF_PATH = "core.services.feature_flag_service.feature_flags.is_enabled"


@pytest.fixture(autouse=True)
def _flags_off():
    """Keep stealth/security feature flags off so these tests are hermetic."""
    with patch(FF_PATH, side_effect=lambda _name: False):
        yield


def _gateway_client():
    """A client whose REMOTE_ADDR is the private compose gateway."""
    return Client(REMOTE_ADDR=GATEWAY_REMOTE_ADDR)


def _as(ip):
    """Return request-kwargs tagging the request with a public client IP."""
    return {"HTTP_X_FORWARDED_FOR": ip}


def _no_ratelimit_headers(response):
    return all(
        h not in response
        for h in ("X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset")
    )


@contextmanager
def _anon_limit(value):
    """Pin the anonymous daily cap without touching settings or the DB flag.

    feature_flags.get_value() is cached in Redis for 5 minutes, so an
    override_settings(ANON_API_DAILY_LIMIT=...) would be order-dependent here.
    """
    real_get_value = ffs.feature_flags.get_value

    def fake_get_value(key, default=None):
        if key == "ANON_API_DAILY_LIMIT":
            return value
        return real_get_value(key, default=default)

    with patch.object(ffs.feature_flags, "get_value", side_effect=fake_get_value):
        yield


def _token_client(user):
    """Gateway client authenticated the way the SPA does: DRF token header."""
    from rest_framework.authtoken.models import Token

    token = Token.objects.create(user=user)
    client = _gateway_client()
    # Django's test Client has no DRF-style credentials() helper, so the header
    # goes into the client defaults and rides along with every request.
    client.defaults["HTTP_AUTHORIZATION"] = f"Token {token.key}"
    return client


# ---------------------------------------------------------------------------
# 1. DEBUG stays a hard bypass (existing localhost-dev behavior)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDebugBypass:
    @override_settings(DEBUG=True, ALLOWED_HOSTS=["*"])
    def test_debug_never_enforces_and_adds_no_headers(self):
        """DEBUG=True short-circuits before the IP gate: no 429, no headers."""
        client = _gateway_client()
        for _ in range(ENFORCED_LIMIT_3["ANON_API_DAILY_LIMIT"] + 2):
            response = client.get(API_PATH, **_as(PUBLIC_CLIENT_A))
            assert response.status_code == 200
            assert _no_ratelimit_headers(response), "DEBUG must not emit X-RateLimit-*"


# ---------------------------------------------------------------------------
# 2. Private gateway REMOTE_ADDR with no forwarded header stays exempt
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestInfraGatewayExempt:
    @override_settings(**ENFORCED_LIMIT_3)
    def test_no_forwarded_header_is_exempt(self):
        """A bare 172.x REMOTE_ADDR (no spoofed header) resolves to the gateway
        -> infrastructure -> exempt, exactly as before."""
        client = _gateway_client()
        for _ in range(ENFORCED_LIMIT_3["ANON_API_DAILY_LIMIT"] + 2):
            response = client.get(API_PATH)
            assert response.status_code == 200
            assert _no_ratelimit_headers(response)


# ---------------------------------------------------------------------------
# 3. Public client behind the gateway IS enforced
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPublicClientEnforced:
    @override_settings(**ENFORCED_LIMIT_3)
    def test_decreasing_remaining_then_429(self):
        """Public client behind the private gateway is throttled per-IP: N 200s
        with decreasing Remaining, then request N+1 is a JSON 429."""
        client = _gateway_client()
        limit = ENFORCED_LIMIT_3["ANON_API_DAILY_LIMIT"]

        for i in range(1, limit + 1):
            response = client.get(API_PATH, **_as(PUBLIC_CLIENT_A))
            assert response.status_code == 200, f"request {i} should be allowed"
            assert int(response["X-RateLimit-Limit"]) == limit
            assert int(response["X-RateLimit-Remaining"]) == limit - i
            assert "X-RateLimit-Reset" in response

        # Over the limit -> 429, Remaining 0, Limit == setting.
        response = client.get(API_PATH, **_as(PUBLIC_CLIENT_A))
        assert response.status_code == 429
        payload = response.json()
        assert "error" in payload
        assert int(response["X-RateLimit-Limit"]) == limit
        assert int(response["X-RateLimit-Remaining"]) == 0


# ---------------------------------------------------------------------------
# 4. Exempt paths are never 429 once throttled
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestExemptPaths:
    @override_settings(**ENFORCED_LIMIT_3)
    def test_auth_path_never_429_after_throttle(self):
        """Once this IP is throttled on a normal API endpoint, /api/auth/* must
        still pass through untouched (never 429)."""
        client = _gateway_client()
        limit = ENFORCED_LIMIT_3["ANON_API_DAILY_LIMIT"]

        for _ in range(limit):
            client.get(API_PATH, **_as(PUBLIC_CLIENT_A))
        # Confirm the bucket is now exhausted.
        assert client.get(API_PATH, **_as(PUBLIC_CLIENT_A)).status_code == 429

        response = client.get("/api/auth/login/", **_as(PUBLIC_CLIENT_A))
        assert response.status_code != 429, "exempt auth path was throttled"

    @override_settings(**ENFORCED_LIMIT_3)
    def test_rate_limit_management_path_never_429_after_throttle(self):
        """/system/rate-limit/* must stay reachable after throttling."""
        client = _gateway_client()
        limit = ENFORCED_LIMIT_3["ANON_API_DAILY_LIMIT"]

        for _ in range(limit):
            client.get(API_PATH, **_as(PUBLIC_CLIENT_A))
        assert client.get(API_PATH, **_as(PUBLIC_CLIENT_A)).status_code == 429

        response = client.get(
            "/api/system/rate-limit/status/1/", **_as(PUBLIC_CLIENT_A)
        )
        assert response.status_code != 429


# ---------------------------------------------------------------------------
# 5. A second IP is independent (its own bucket)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestIndependentBuckets:
    @override_settings(**ENFORCED_LIMIT_3)
    def test_second_ip_not_affected_by_first(self):
        """Throttling client A must not leak into client B's bucket."""
        client = _gateway_client()
        limit = ENFORCED_LIMIT_3["ANON_API_DAILY_LIMIT"]

        for i in range(1, limit + 1):
            response = client.get(API_PATH, **_as(PUBLIC_CLIENT_A))
            assert int(response["X-RateLimit-Remaining"]) == limit - i

        # A is now exhausted...
        assert client.get(API_PATH, **_as(PUBLIC_CLIENT_A)).status_code == 429

        # ...but B still has a full bucket.
        response = client.get(API_PATH, **_as(PUBLIC_CLIENT_B))
        assert response.status_code == 200
        assert int(response["X-RateLimit-Remaining"]) == limit - 1


# ---------------------------------------------------------------------------
# 6. Hybrid: registered integer flag, settings default, admin override wins
# ---------------------------------------------------------------------------


class TestHybridFlagRegistration:
    def test_anon_limit_is_registered_integer_flag(self):
        """The hybrid contract requires the cap to be an admin-visible,
        env-backed integer flag whose KNOWN default matches the settings one."""
        known = ffs.feature_flags.KNOWN_FLAGS["ANON_API_DAILY_LIMIT"]
        assert known["value_type"] == "integer"
        assert known["env_var"] == "ANON_API_DAILY_LIMIT"
        assert known["default"] == DEFAULT_ANON_API_DAILY_LIMIT
        assert known["requires_restart"] is False


@pytest.mark.django_db
class TestHybridFlagOverride:
    @override_settings(**ENFORCED)
    def test_flag_override_takes_precedence_over_settings_default(self):
        """When no DB row exists the cap is the settings default; a
        FeatureFlag override must win over that default and drive the 429."""
        client = _gateway_client()
        real_get_value = ffs.feature_flags.get_value

        def fake_get_value(key, default=None):
            if key == "ANON_API_DAILY_LIMIT":
                return 3
            return real_get_value(key, default=default)

        with patch.object(
            ffs.feature_flags, "get_value", side_effect=fake_get_value
        ):
            for _ in range(3):
                response = client.get(API_PATH, **_as(PUBLIC_CLIENT_A))
                assert response.status_code == 200
                # 3 (the flag override), not the settings default.
                assert int(response["X-RateLimit-Limit"]) == 3

            response = client.get(API_PATH, **_as(PUBLIC_CLIENT_A))
            assert response.status_code == 429
            assert int(response["X-RateLimit-Limit"]) == 3
            assert int(response["X-RateLimit-Remaining"]) == 0


# ---------------------------------------------------------------------------
# 7. Token-authenticated SPA traffic is billed per USER, not per IP
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTokenAuthenticatedIdentity:
    """The SPA authenticates with `Authorization: Token <key>`, which Django's
    session-only AuthenticationMiddleware cannot see.  Such requests must be
    counted against the user's own daily limit, never the anonymous IP bucket
    (that bug billed every logged-in page load to the 300/day anon cap)."""

    @override_settings(**ENFORCED)
    def test_token_user_is_billed_to_user_bucket_not_ip(self, user):
        user.daily_request_limit_override = 3
        user.save(update_fields=["daily_request_limit_override"])
        client = _token_client(user)

        for i in range(1, 4):
            response = client.get(API_PATH, **_as(PUBLIC_CLIENT_A))
            assert response.status_code == 200, f"request {i} should be allowed"
            assert int(response["X-RateLimit-Limit"]) == 3
            assert int(response["X-RateLimit-Remaining"]) == 3 - i

        response = client.get(API_PATH, **_as(PUBLIC_CLIENT_A))
        assert response.status_code == 429
        assert int(response["X-RateLimit-Remaining"]) == 0

        # Billed to the user bucket...
        assert cache.get(get_user_ratelimit_key(user.id))["count"] == 3
        # ...and the anonymous per-IP bucket was never touched.
        assert cache.get(get_ip_ratelimit_key(PUBLIC_CLIENT_A)) is None

    @override_settings(**ENFORCED)
    def test_session_and_token_auth_share_the_user_bucket(self, user):
        """Session auth (what /api/admin/ uses) keeps working and lands on the
        same per-user counter as token auth."""
        user.daily_request_limit_override = 2
        user.save(update_fields=["daily_request_limit_override"])
        client = _gateway_client()
        client.force_login(user)

        for i in (1, 2):
            response = client.get(API_PATH, **_as(PUBLIC_CLIENT_A))
            assert response.status_code == 200
            assert int(response["X-RateLimit-Remaining"]) == 2 - i

        assert client.get(API_PATH, **_as(PUBLIC_CLIENT_A)).status_code == 429
        assert cache.get(get_user_ratelimit_key(user.id))["count"] == 2
        assert cache.get(get_ip_ratelimit_key(PUBLIC_CLIENT_A)) is None

    @override_settings(**ENFORCED)
    def test_staff_token_is_exempt(self, admin_user):
        """Staff are exempt whichever way they authenticate (session or token)."""
        client = _token_client(admin_user)
        for _ in range(5):
            response = client.get(API_PATH, **_as(PUBLIC_CLIENT_A))
            assert response.status_code == 200
            assert _no_ratelimit_headers(response)
        assert cache.get(get_ip_ratelimit_key(PUBLIC_CLIENT_A)) is None
        assert cache.get(get_user_ratelimit_key(admin_user.id)) is None

    @override_settings(**ENFORCED)
    def test_invalid_token_falls_back_to_anonymous_counting(self):
        """A bogus credential must neither raise from middleware nor grant a
        free pass: the request is treated as anonymous."""
        client = _gateway_client()
        client.defaults["HTTP_AUTHORIZATION"] = "Token not-a-real-token"
        with _anon_limit(1):
            assert client.get(API_PATH, **_as(PUBLIC_CLIENT_A)).status_code == 200
            assert client.get(API_PATH, **_as(PUBLIC_CLIENT_A)).status_code == 429


# ---------------------------------------------------------------------------
# 8. Boot/widget chatter (safe reads) is not billed
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestNoisyBootChatterExempt:
    @override_settings(**ENFORCED)
    def test_noisy_safe_reads_are_never_counted(self):
        client = _gateway_client()
        for _ in range(10):
            client.get(NOISY_READ_PATH, **_as(PUBLIC_CLIENT_A))
        assert cache.get(get_ip_ratelimit_key(PUBLIC_CLIENT_A)) is None

    @override_settings(**ENFORCED)
    def test_noisy_reads_do_not_consume_the_daily_cap(self):
        """A page load's worth of boot calls is free, so a small cap still
        covers that many real data requests."""
        client = _gateway_client()
        with _anon_limit(2):
            for _ in range(10):
                client.get(NOISY_READ_PATH, **_as(PUBLIC_CLIENT_A))

            for i in (1, 2):
                response = client.get(API_PATH, **_as(PUBLIC_CLIENT_A))
                assert response.status_code == 200
                assert int(response["X-RateLimit-Remaining"]) == 2 - i

            assert client.get(API_PATH, **_as(PUBLIC_CLIENT_A)).status_code == 429

    @override_settings(**ENFORCED)
    def test_writes_on_noisy_paths_are_still_counted(self):
        """Only safe methods are carved out, so the exemption cannot be used to
        hammer a mutating endpoint for free."""
        client = _gateway_client()
        client.post(
            NOISY_WRITE_PATH,
            data={},
            content_type="application/json",
            **_as(PUBLIC_CLIENT_A),
        )
        usage = cache.get(get_ip_ratelimit_key(PUBLIC_CLIENT_A))
        assert usage is not None, "write on a noisy path must still be counted"
        assert usage["count"] == 1
