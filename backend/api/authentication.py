import jwt
from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from loguru import logger
from rest_framework import authentication, exceptions
from rest_framework.authtoken.models import Token

from api.redis_keys import TOKEN_AUTH_CACHE_TTL, get_token_auth_cache_key
from diavgeia_project.security_tracing import get_client_ip, security_tracer
from users.models import CustomUser


def _resolve_clerk_user(clerk_id: str, payload: dict) -> CustomUser:
    """
    Resolve (link or provision) the CustomUser for a verified Clerk identity.

    Identity-linking rules (unified-auth step 06):
    1. Match on clerk_id first — the fast path for returning Clerk users.
    2. Otherwise LINK to an existing Django-registered account with the same
       email (case-insensitive). Clerk only issues sessions for verified
       emails, so "same verified email = same person" — the industry-standard
       behavior (Auth0/Firebase/Supabase). Prefer verified rows, tie-break
       oldest-first for determinism when legacy duplicates exist.
    3. Otherwise provision a new user with a collision-safe username.

    Race-safe: provisioning runs in a transaction with an IntegrityError
    retry, so two concurrent first-logins with the same new email produce
    exactly one row (the loser re-resolves via clerk_id/email lookup).
    """
    email = (payload.get("email") or "").strip().lower()
    # Clerk's session token template emits a top-level `email_verified` user
    # property (see docs/implementation-tasks/04. unified-auth/06-...md).
    # Fallback: a Clerk session can only exist for a verified primary email,
    # so a present email is treated as verified when the claim is absent.
    email_verified = bool(payload.get("email_verified", bool(email)))

    # 1. Fast path: existing Clerk-linked user.
    user = CustomUser.objects.filter(clerk_id=clerk_id).first()
    if user:
        # Keep email_verified in sync with Clerk's claim (e.g. the user
        # verified their Django email via Clerk in the meantime).
        if email and email_verified and not user.email_verified:
            user.email_verified = True
            user.save(update_fields=["email_verified"])
        return user

    # 2. Link to an existing same-email Django account before creating a new
    #    row — this is what keeps bookmarks/subscription/AI spend unified.
    if email:
        existing = (
            CustomUser.objects.filter(email__iexact=email)
            .order_by("-email_verified", "date_joined")
            .first()
        )
        if existing:
            if existing.clerk_id and existing.clerk_id != clerk_id:
                # Different Clerk identity already bound to this email — do
                # not silently steal the link; provision a separate user.
                logger.warning(
                    f"Email {email} already linked to clerk_id {existing.clerk_id}; "
                    f"provisioning separate user for {clerk_id}"
                )
            else:
                existing.clerk_id = clerk_id
                if email_verified:
                    existing.email_verified = True
                existing.save(update_fields=["clerk_id", "email_verified"])
                logger.info(f"Linked Clerk identity {clerk_id} to user {existing.pk}")
                return existing

    # 3. Provision a new user (collision-safe username, race-safe).
    username = email or f"user_{clerk_id}"
    for attempt in range(3):
        try:
            with transaction.atomic():
                if CustomUser.objects.filter(username=username).exists():
                    username = (
                        f"{username}_{clerk_id[-8:]}"
                        if attempt == 0
                        else f"{username}_{attempt}"
                    )
                user = CustomUser.objects.create(
                    username=username,
                    email=email,
                    clerk_id=clerk_id,
                    email_verified=email_verified,
                )
                logger.info(
                    f"Provisioned new user {user.pk} from Clerk identity {clerk_id}"
                )
                return user
        except IntegrityError:
            # Concurrent login created the row first — re-resolve and return.
            user = (
                CustomUser.objects.filter(clerk_id=clerk_id).first()
                or CustomUser.objects.filter(email__iexact=email).first()
            )
            if user:
                return user
    raise exceptions.AuthenticationFailed("Could not resolve Clerk identity")


class CsrfExemptSessionAuthentication(authentication.SessionAuthentication):
    """
    SessionAuthentication that doesn't enforce CSRF checks.

    Use this for API endpoints that:
    - Use token-based authentication as the primary method
    - Support session auth as a fallback (e.g., for browsable API)
    - Don't need CSRF protection because they use Authorization headers

    This is safe because:
    - CSRF attacks rely on browser automatically sending cookies
    - Token auth requires explicit JavaScript code to add headers
    - Malicious sites can't read tokens from your origin due to CORS
    """

    def enforce_csrf(self, request):
        # Skip CSRF check
        return


def _token_cache_ttl() -> int:
    return int(getattr(settings, "TOKEN_AUTH_CACHE_TTL", TOKEN_AUTH_CACHE_TTL))


def _cache_get(key: str):
    """Read from cache, treating an unavailable cache as a miss."""
    try:
        return cache.get(key)
    except Exception as exc:
        # Auth must keep working when Redis is down; the DB remains the source
        # of truth. Never log the token (only this generic error is logged).
        logger.debug(f"Token auth cache read failed, falling back to DB: {exc}")
        return None


def _cache_set(key: str, value, ttl: int) -> None:
    try:
        cache.set(key, value, ttl)
    except Exception as exc:
        logger.debug(f"Token auth cache write failed: {exc}")


def _cache_delete(key: str) -> None:
    try:
        cache.delete(key)
    except Exception as exc:
        logger.debug(f"Token auth cache delete failed: {exc}")


def invalidate_token_cache(token_key: str | None) -> None:
    """Drop the cached auth pair for a raw DRF token key."""
    if not token_key:
        return
    _cache_delete(get_token_auth_cache_key(token_key))


def invalidate_user_token_cache(user) -> None:
    """Drop the cached auth pair for every token belonging to ``user``."""
    try:
        token_keys = list(Token.objects.filter(user=user).values_list("key", flat=True))
    except Exception as exc:
        logger.debug(f"Token auth cache user lookup failed: {exc}")
        return

    for token_key in token_keys:
        invalidate_token_cache(token_key)


class CachedTokenAuthentication(authentication.TokenAuthentication):
    """
    TokenAuthentication with a short-lived token -> (user, token) cache.

    DRF's TokenAuthentication joins ``authtoken_token`` to ``users_customuser``
    on every request. A page visit fires dozens of requests with the same
    token, so that repeated lookup dominates auth DB time. Cache the resolved
    pair (already ``select_related("user")`` via the parent implementation)
    under the token's SHA-256 for ``TOKEN_AUTH_CACHE_TTL`` seconds.

    Staleness is bounded by the TTL, and ``is_active`` is still checked on the
    cached user before it is returned. Logout, token rotation and password
    reset invalidate eagerly.
    """

    def authenticate_credentials(self, key):
        cache_key = get_token_auth_cache_key(key)
        cached = _cache_get(cache_key)
        if isinstance(cached, tuple) and len(cached) == 2:
            user, token = cached
            if not user.is_active:
                raise exceptions.AuthenticationFailed("User inactive or deleted.")
            return (user, token)

        user, token = super().authenticate_credentials(key)
        _cache_set(cache_key, (user, token), _token_cache_ttl())
        return (user, token)


class ClerkAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        # Skip Clerk authentication if feature flag is disabled
        use_clerk = getattr(settings, "USE_CLERK_AUTH", False)
        if not use_clerk:
            logger.debug("Clerk authentication disabled by feature flag, skipping")
            return None

        # Skip Clerk authentication if not configured
        if not getattr(settings, "CLERK_JWT_PUBLIC_KEY", None):
            logger.warning(
                "Clerk authentication enabled but not configured (missing public key), skipping"
            )
            return None

        logger.debug(f"ClerkAuthentication.authenticate called for {request.path}")
        auth_header = request.META.get("HTTP_AUTHORIZATION")
        logger.debug(f"Auth header present: {bool(auth_header)}")
        if not auth_header or not auth_header.startswith("Bearer "):
            # Anonymous requests are a supported flow (free read-only access),
            # so this is expected on most calls — keep it out of WARNING.
            logger.debug("No Bearer token found, skipping Clerk auth")
            return None  # No token provided, let other auth methods try

        token = auth_header.split(" ")[1]
        logger.debug(f"Token extracted: {token[:20]}...")

        try:
            logger.debug("Attempting JWT decode...")
            # Verify JWT token with Clerk's public key
            # Note: Clerk doesn't always include 'aud' claim, so we skip audience verification
            payload = jwt.decode(
                token,
                settings.CLERK_JWT_PUBLIC_KEY,
                algorithms=["RS256"],
                options={"verify_exp": True, "verify_aud": False},
            )
            logger.debug(f"JWT decoded successfully, sub: {payload.get('sub')}")

            clerk_id = payload.get("sub")
            if not clerk_id:
                security_tracer.log_security_event(
                    "authentication.clerk.invalid",
                    {"reason": "missing_sub_claim"},
                    ip=get_client_ip(request),
                    severity="WARNING",
                )
                raise exceptions.AuthenticationFailed("Invalid token")

            # Resolve (link or provision) the user for this Clerk identity.
            user = _resolve_clerk_user(clerk_id, payload)

            # Log successful authentication
            security_tracer.log_security_event(
                "authentication.clerk.success",
                {"email": payload.get("email", "")},
                user=user,
                ip=get_client_ip(request),
            )

            return (user, token)

        except jwt.ExpiredSignatureError:
            security_tracer.log_security_event(
                "authentication.clerk.expired",
                {"token_preview": token[:10] + "..."},
                clerk_id=payload.get("sub") if "payload" in locals() else None,
                ip=get_client_ip(request),
                severity="WARNING",
            )
            raise exceptions.AuthenticationFailed("Token expired")
        except jwt.InvalidTokenError as e:

            logger.error(f"JWT validation failed: {str(e)}")
            security_tracer.log_security_event(
                "authentication.clerk.invalid",
                {"token_preview": token[:10] + "...", "error": str(e)},
                ip=get_client_ip(request),
                severity="WARNING",
            )
            raise exceptions.AuthenticationFailed("Invalid token")
        except Exception as e:

            logger.error(f"Unexpected auth error: {str(e)}")
            security_tracer.log_security_event(
                "authentication.clerk.error",
                {"error": str(e)},
                ip=get_client_ip(request),
                severity="ERROR",
            )
            raise exceptions.AuthenticationFailed(f"Authentication failed: {str(e)}")


class ApiKeyAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        api_key = request.META.get("HTTP_X_API_KEY") or request.query_params.get(
            "api_key"
        )
        if not api_key:
            return None

        try:
            user = CustomUser.objects.get(api_key=api_key)

            # Check if subscription is still valid
            if not user.has_active_subscription:
                security_tracer.log_security_event(
                    "authentication.api_key.expired_subscription",
                    {"api_key_preview": api_key[:5] + "..."},
                    user=user,
                    ip=get_client_ip(request),
                    severity="WARNING",
                )
                raise exceptions.AuthenticationFailed("Subscription expired")

            # Log successful API key authentication
            security_tracer.log_security_event(
                "authentication.api_key.success",
                {},
                user=user,
                ip=get_client_ip(request),
            )

            return (user, api_key)
        except CustomUser.DoesNotExist:
            security_tracer.log_security_event(
                "authentication.api_key.invalid",
                {"api_key_preview": api_key[:5] + "..."},
                ip=get_client_ip(request),
                severity="WARNING",
            )
            return None
