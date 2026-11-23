"""
Tests for the cached DRF token authentication (organization-page perf step 2).

``CachedTokenAuthentication`` must turn the per-request ``authtoken_token``
join into at most one query per TTL window, while keeping invalidation and the
inactive-user guard intact.

Run explicitly:
    cd backend && pytest api/tests/test_cached_token_authentication.py -v
"""

import uuid
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIRequestFactory

from api.authentication import (
    CachedTokenAuthentication,
    invalidate_token_cache,
    invalidate_user_token_cache,
)
from api.redis_keys import get_token_auth_cache_key

pytestmark = [pytest.mark.django_db, pytest.mark.fast]

ME_URL = "/api/auth/me/"
LOGOUT_URL = "/api/auth/logout/"
RESET_PASSWORD_URL = "/api/auth/reset-password/"


@pytest.fixture(autouse=True)
def clear_token_cache():
    """Isolate the auth-token cache namespace (shared Redis cache)."""
    cache.delete_pattern("auth:token:*")
    yield
    cache.delete_pattern("auth:token:*")


class BrokenCache:
    """Cache backend stub whose every operation fails."""

    def get(self, *args, **kwargs):
        raise RuntimeError("cache unavailable")

    def set(self, *args, **kwargs):
        raise RuntimeError("cache unavailable")

    def delete(self, *args, **kwargs):
        raise RuntimeError("cache unavailable")


def _request(token_key: str):
    return APIRequestFactory().get(
        "/api/decisions/", HTTP_AUTHORIZATION=f"Token {token_key}"
    )


def _authenticate(token_key: str):
    return CachedTokenAuthentication().authenticate(_request(token_key))


def _token_queries(captured_queries):
    return [q for q in captured_queries if "authtoken_token" in q["sql"]]


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------


def test_cache_hit_avoids_the_token_table(user):
    token = Token.objects.create(user=user)

    with CaptureQueriesContext(connection) as first:
        _authenticate(token.key)
    assert len(_token_queries(first.captured_queries)) == 1

    with CaptureQueriesContext(connection) as second:
        result = _authenticate(token.key)

    assert result is not None
    assert _token_queries(second.captured_queries) == []


def test_cached_value_is_the_resolved_user_and_token(user):
    token = Token.objects.create(user=user)
    _authenticate(token.key)

    cached_user, cached_token = cache.get(get_token_auth_cache_key(token.key))

    assert cached_user.pk == user.pk
    assert cached_token.key == token.key


def test_cache_key_hashes_the_raw_token(user):
    token = Token.objects.create(user=user)

    key = get_token_auth_cache_key(token.key)

    assert key.startswith("auth:token:")
    assert token.key not in key


def test_invalid_token_raises_and_is_not_cached():
    missing = "not-a-real-token"

    with pytest.raises(AuthenticationFailed):
        _authenticate(missing)

    assert cache.get(get_token_auth_cache_key(missing)) is None


def test_inactive_cached_user_is_rejected(user):
    user.is_active = False
    user.save(update_fields=["is_active"])
    token = Token.objects.create(user=user)
    cache.set(get_token_auth_cache_key(token.key), (user, token), 60)

    with pytest.raises(AuthenticationFailed):
        _authenticate(token.key)


def test_cache_failure_falls_back_to_the_database(user, monkeypatch):
    token = Token.objects.create(user=user)
    monkeypatch.setattr("api.authentication.cache", BrokenCache())

    result_user, result_token = _authenticate(token.key)

    assert result_user.pk == user.pk
    assert result_token.key == token.key


# ---------------------------------------------------------------------------
# Invalidation
# ---------------------------------------------------------------------------


def test_invalidate_token_cache_drops_the_entry(user):
    token = Token.objects.create(user=user)
    _authenticate(token.key)
    assert cache.get(get_token_auth_cache_key(token.key)) is not None

    invalidate_token_cache(token.key)

    assert cache.get(get_token_auth_cache_key(token.key)) is None


def test_invalidate_user_token_cache_drops_the_users_entry(user):
    token = Token.objects.create(user=user)
    _authenticate(token.key)
    assert cache.get(get_token_auth_cache_key(token.key)) is not None

    invalidate_user_token_cache(user)

    assert cache.get(get_token_auth_cache_key(token.key)) is None


def test_two_authenticated_requests_hit_the_token_table_once(api_client, user):
    token = Token.objects.create(user=user)
    api_client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    with CaptureQueriesContext(connection) as ctx:
        first = api_client.get(ME_URL)
        second = api_client.get(ME_URL)

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(_token_queries(ctx.captured_queries)) == 1


def test_logout_invalidates_the_cached_token(api_client, user):
    token = Token.objects.create(user=user)
    api_client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    assert api_client.get(ME_URL).status_code == 200
    assert cache.get(get_token_auth_cache_key(token.key)) is not None

    response = api_client.post(LOGOUT_URL, {}, format="json")

    assert response.status_code == 200
    assert cache.get(get_token_auth_cache_key(token.key)) is None


def test_password_reset_invalidates_the_old_cached_token(api_client, user):
    old_token = Token.objects.create(user=user)
    old_key = old_token.key
    api_client.credentials(HTTP_AUTHORIZATION=f"Token {old_key}")
    assert api_client.get(ME_URL).status_code == 200
    assert cache.get(get_token_auth_cache_key(old_key)) is not None

    user.password_reset_token = uuid.uuid4()
    user.password_reset_token_expires = timezone.now() + timedelta(hours=1)
    user.save(update_fields=["password_reset_token", "password_reset_token_expires"])

    response = api_client.post(
        RESET_PASSWORD_URL,
        {
            "token": str(user.password_reset_token),
            "new_password": "Str0ng-Passw0rd-123",
        },
        format="json",
    )

    assert response.status_code == 200
    assert cache.get(get_token_auth_cache_key(old_key)) is None

    new_key = response.json()["token"]
    assert new_key != old_key

    api_client.credentials(HTTP_AUTHORIZATION=f"Token {new_key}")
    assert api_client.get(ME_URL).status_code == 200
