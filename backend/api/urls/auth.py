"""
Authentication-related URL patterns.

All endpoints here are automatically exempt from stealth mode middleware
because they're under the /api/auth/ prefix.
"""

from django.urls import path

# URL prefix for this module - used by stealth middleware for automatic exemption
PREFIX = "auth/"
from api.views.django_auth import login as django_login
from api.views.django_auth import logout as django_logout
from api.views.django_auth import me as current_user
from api.views.django_auth import (
    register,
    request_password_reset,
    reset_password,
    verify_email,
    verify_reset_token,
)

urlpatterns = [
    # Django authentication endpoints (for when Clerk is not configured)
    path("login/", django_login, name="django_login"),
    path("register/", register, name="django_register"),
    path("logout/", django_logout, name="django_logout"),
    path("verify-email/", verify_email, name="django_verify_email"),
    path("me/", current_user, name="current_user"),
    # Password reset endpoints
    path(
        "request-password-reset/", request_password_reset, name="request_password_reset"
    ),
    path("reset-password/", reset_password, name="reset_password"),
    path("verify-reset-token/", verify_reset_token, name="verify_reset_token"),
]
