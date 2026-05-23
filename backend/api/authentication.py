import jwt
from diavgeia_project.security_tracing import get_client_ip, security_tracer
from django.conf import settings
from loguru import logger
from rest_framework import authentication, exceptions
from users.models import CustomUser


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
            logger.warning("No Bearer token found, skipping Clerk auth")
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

            # Get or create user based on Clerk ID
            try:
                user = CustomUser.objects.get(clerk_id=clerk_id)
                # Log successful authentication
                security_tracer.log_security_event(
                    "authentication.clerk.success",
                    {"email": payload.get("email", "")},
                    user=user,
                    ip=get_client_ip(request),
                )
            except CustomUser.DoesNotExist:
                # Auto-provision user from Clerk data
                email = payload.get("email", "")
                username = email or f"user_{clerk_id}"

                user = CustomUser.objects.create(
                    username=username,
                    email=email,
                    clerk_id=clerk_id,
                )

                # Log user provisioning
                security_tracer.log_security_event(
                    "user.provisioned",
                    {"email": email, "source": "clerk"},
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
