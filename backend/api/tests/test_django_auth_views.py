"""
Tests for api/views/django_auth.py — Django-native registration, login,
email verification and password-reset flows.

These endpoints are the "django" leg advertised by /api/system/config/auth/
(see api/utils/auth_methods.py), so they must stay fully covered: any
deployment without Clerk relies on them exclusively.

Run explicitly (api/tests is not in pytest.ini testpaths):
    cd backend && pytest api/tests/test_django_auth_views.py -v
"""

import uuid

import pytest
from django.test import override_settings
from rest_framework.authtoken.models import Token
from unittest.mock import patch

from django.contrib.auth import get_user_model

User = get_user_model()

REGISTER_URL = "/api/auth/register/"
LOGIN_URL = "/api/auth/login/"
LOGOUT_URL = "/api/auth/logout/"
VERIFY_EMAIL_URL = "/api/auth/verify-email/"
ME_URL = "/api/auth/me/"
REQUEST_RESET_URL = "/api/auth/request-password-reset/"
RESET_PASSWORD_URL = "/api/auth/reset-password/"
VERIFY_RESET_TOKEN_URL = "/api/auth/verify-reset-token/"

# Hermetic: pin the feature-flag singleton used by stealth/security middleware.
FF_PATH = "core.services.feature_flag_service.feature_flags.is_enabled"


def _post(api_client, url, payload):
    with patch(FF_PATH, side_effect=lambda _name: False):
        return api_client.post(url, payload, format="json")


def _get(api_client, url):
    with patch(FF_PATH, side_effect=lambda _name: False):
        return api_client.get(url)


def _get_with_query(api_client, url, query):
    with patch(FF_PATH, side_effect=lambda _name: False):
        return api_client.get(f"{url}?{query}")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRegister:
    def test_register_without_verification_returns_token(self, api_client):
        response = _post(
            api_client,
            REGISTER_URL,
            {"email": "newuser@example.com", "password": "Str0ngPassw0rd!"},
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["verification_required"] is False
        assert payload["token"]
        assert payload["user"]["email"] == "newuser@example.com"
        assert Token.objects.filter(
            user__email="newuser@example.com"
        ).exists()

    def test_register_with_optional_username(self, api_client):
        response = _post(
            api_client,
            REGISTER_URL,
            {
                "email": "named@example.com",
                "password": "Str0ngPassw0rd!",
                "username": "named",
            },
        )
        assert response.status_code == 201
        assert response.json()["user"]["username"] == "named"

    @override_settings(DJANGO_EMAIL_VERIFICATION_REQUIRED=True)
    def test_register_with_verification_creates_inactive_user(self, api_client):
        response = _post(
            api_client,
            REGISTER_URL,
            {"email": "verifyme@example.com", "password": "Str0ngPassw0rd!"},
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["verification_required"] is True
        # No mocked mailer: the real email service runs (console backend in
        # tests) and reports success — assert on the outcome, not on "no send".
        assert payload["email_sent"] is True
        assert "token" not in payload
        user = User.objects.get(email="verifyme@example.com")
        assert user.is_active is False
        assert user.email_verification_token is not None

    def test_register_missing_fields_400(self, api_client):
        assert _post(api_client, REGISTER_URL, {"email": "x@example.com"}).status_code == 400
        assert _post(api_client, REGISTER_URL, {"password": "pw"}).status_code == 400

    def test_register_duplicate_email_400(self, api_client):
        _post(
            api_client,
            REGISTER_URL,
            {"email": "dup@example.com", "password": "Str0ngPassw0rd!"},
        )
        response = _post(
            api_client,
            REGISTER_URL,
            {"email": "dup@example.com", "password": "Str0ngPassw0rd!"},
        )
        assert response.status_code == 400
        assert "already exists" in response.json()["error"]

    @override_settings(DJANGO_EMAIL_VERIFICATION_REQUIRED=True)
    def test_register_sends_verification_email_when_configured(self, api_client):
        with patch(
            "core.email_service.RegistrationEmailService.send_verification_email",
            return_value=True,
        ) as mock_send:
            response = _post(
                api_client,
                REGISTER_URL,
                {"email": "mailer@example.com", "password": "Str0ngPassw0rd!"},
            )
        assert response.status_code == 201
        assert response.json()["email_sent"] is True
        mock_send.assert_called_once()

    @override_settings(DJANGO_EMAIL_VERIFICATION_REQUIRED=True)
    def test_register_verification_email_failure_is_non_fatal(self, api_client):
        with patch(
            "core.email_service.RegistrationEmailService.send_verification_email",
            side_effect=Exception("SES down"),
        ):
            response = _post(
                api_client,
                REGISTER_URL,
                {"email": "mailerfail@example.com", "password": "Str0ngPassw0rd!"},
            )
        assert response.status_code == 201
        assert response.json()["email_sent"] is False


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLogin:
    def _register(self, api_client, email, password="Str0ngPassw0rd!"):
        return _post(api_client, REGISTER_URL, {"email": email, "password": password})

    def test_login_success_returns_token(self, api_client):
        self._register(api_client, "login@example.com")
        response = _post(
            api_client, LOGIN_URL, {"email": "login@example.com", "password": "Str0ngPassw0rd!"}
        )
        assert response.status_code == 200
        assert response.json()["token"]
        assert response.json()["user"]["email"] == "login@example.com"

    def test_login_invalid_credentials_401(self, api_client):
        response = _post(
            api_client,
            LOGIN_URL,
            {"email": "nobody@example.com", "password": "wrong"},
        )
        assert response.status_code == 401

    def test_login_missing_fields_400(self, api_client):
        assert _post(api_client, LOGIN_URL, {}).status_code == 400

    @override_settings(DJANGO_EMAIL_VERIFICATION_REQUIRED=True)
    def test_login_unverified_email_403(self, api_client):
        # The auth backend rejects inactive users (user_can_authenticate),
        # so authenticate() returns None and we can't reach the view's 403
        # branch through the normal flow. Stub authenticate to return the
        # inactive user, exactly as a backend that doesn't filter on
        # is_active would — the view then applies its own inactive-user logic.
        user = User.objects.create(
            username="unverified",
            email="unverified@example.com",
            password="Str0ngPassw0rd!",
            is_active=False,
            email_verified=False,
            email_verification_token=uuid.uuid4(),
        )
        with patch(
            "api.views.django_auth.authenticate", return_value=user
        ):
            response = _post(
                api_client,
                LOGIN_URL,
                {"email": "unverified@example.com", "password": "Str0ngPassw0rd!"},
            )
        assert response.status_code == 403
        assert response.json()["verification_required"] is True

    @override_settings(DJANGO_EMAIL_VERIFICATION_REQUIRED=True)
    def test_login_inactive_user_without_pending_verification_403(self, api_client):
        # Same stubbing rationale as test_login_unverified_email_403: the
        # backend filters inactive users out before the view can respond.
        user = User.objects.create(
            username="disabled",
            email="disabled@example.com",
            password="Str0ngPassw0rd!",
            is_active=False,
            email_verified=False,
            email_verification_token=None,
        )

        with patch(
            "api.views.django_auth.authenticate", return_value=user
        ):
            response = _post(
                api_client,
                LOGIN_URL,
                {"email": "disabled@example.com", "password": "Str0ngPassw0rd!"},
            )
        assert response.status_code == 403
        assert "disabled" in response.json()["error"]


# ---------------------------------------------------------------------------
# Logout / me
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLogoutAndMe:
    def test_logout_deletes_token(self, api_client, user):
        token = Token.objects.create(user=user)
        api_client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        response = _post(api_client, LOGOUT_URL, {})
        assert response.status_code == 200
        assert not Token.objects.filter(user=user).exists()

    def test_logout_unauthenticated_401(self, api_client):
        assert _post(api_client, LOGOUT_URL, {}).status_code == 401

    def test_me_returns_current_user(self, api_client, user):
        token = Token.objects.create(user=user)
        api_client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        response = _get(api_client, ME_URL)
        assert response.status_code == 200
        assert response.json()["user"]["id"] == user.id
        assert response.json()["user"]["auth_method"] == "django"

    def test_me_unauthenticated_401(self, api_client):
        assert _get(api_client, ME_URL).status_code == 401


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestVerifyEmail:
    def test_verify_email_via_get_activates_user(self, api_client):
        token_uuid = uuid.uuid4()
        User.objects.create(
            username="verifyget",
            email="verifyget@example.com",
            password="x",
            is_active=False,
            email_verified=False,
            email_verification_token=token_uuid,
        )
        response = _get_with_query(api_client, VERIFY_EMAIL_URL, f"token={token_uuid}")
        assert response.status_code == 200
        user = User.objects.get(email="verifyget@example.com")
        assert user.is_active is True
        assert user.email_verified is True
        assert user.email_verification_token is None

    def test_verify_email_via_post_returns_token(self, api_client):
        token_uuid = uuid.uuid4()
        User.objects.create(
            username="verifypost",
            email="verifypost@example.com",
            password="x",
            is_active=False,
            email_verified=False,
            email_verification_token=token_uuid,
        )
        response = _post(api_client, VERIFY_EMAIL_URL, {"token": str(token_uuid)})
        assert response.status_code == 200
        assert response.json()["token"]

    def test_verify_email_missing_token_400(self, api_client):
        assert _post(api_client, VERIFY_EMAIL_URL, {}).status_code == 400

    def test_verify_email_invalid_token_400(self, api_client):
        response = _post(api_client, VERIFY_EMAIL_URL, {"token": str(uuid.uuid4())})
        assert response.status_code == 400

    def test_verify_email_expired_token_400(self, api_client):
        from django.utils import timezone

        token_uuid = uuid.uuid4()
        User.objects.create(
            username="expired",
            email="expired@example.com",
            password="x",
            is_active=False,
            email_verified=False,
            email_verification_token=token_uuid,
            email_verification_token_expires=timezone.now() - timezone.timedelta(hours=1),
        )
        response = _post(api_client, VERIFY_EMAIL_URL, {"token": str(token_uuid)})
        assert response.status_code == 400
        assert "expired" in response.json()["error"]

    def test_verify_email_already_verified_200(self, api_client):
        token_uuid = uuid.uuid4()
        User.objects.create(
            username="already",
            email="already@example.com",
            password="x",
            is_active=True,
            email_verified=True,
            email_verification_token=token_uuid,
        )
        response = _post(api_client, VERIFY_EMAIL_URL, {"token": str(token_uuid)})
        assert response.status_code == 200
        assert "already verified" in response.json()["message"]


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPasswordReset:
    def test_request_password_reset_sends_email(self, api_client, user):
        user.email_verified = True
        user.save()
        with patch(
            "core.email_service.PasswordResetEmailService.send_password_reset_email",
            return_value=True,
        ) as mock_send:
            response = _post(api_client, REQUEST_RESET_URL, {"email": user.email})
        assert response.status_code == 200
        assert mock_send.called
        user.refresh_from_db()
        assert user.password_reset_token is not None

    def test_request_password_reset_never_reveals_unknown_email(self, api_client):
        response = _post(
            api_client, REQUEST_RESET_URL, {"email": "ghost@example.com"}
        )
        assert response.status_code == 200
        assert "reset link has been sent" in response.json()["message"]

    def test_request_password_reset_missing_email_400(self, api_client):
        assert _post(api_client, REQUEST_RESET_URL, {}).status_code == 400

    def test_request_password_reset_for_clerk_user_notes_flow(self, api_client, user):
        user.clerk_id = "user_clerk_123"
        user.email_verified = True
        user.save()
        response = _post(api_client, REQUEST_RESET_URL, {"email": user.email})
        assert response.status_code == 200
        assert "Clerk" in response.json().get("note", "")

    def test_reset_password_success(self, api_client, user):
        from django.utils import timezone

        user.password_reset_token = uuid.uuid4()
        user.password_reset_token_expires = timezone.now() + timezone.timedelta(hours=1)
        user.save()

        response = _post(
            api_client,
            RESET_PASSWORD_URL,
            {"token": str(user.password_reset_token), "new_password": "NewStr0ngPass!"},
        )
        assert response.status_code == 200
        user.refresh_from_db()
        assert user.check_password("NewStr0ngPass!")
        assert user.password_reset_token is None

    def test_reset_password_missing_fields_400(self, api_client):
        assert _post(api_client, RESET_PASSWORD_URL, {"token": "t"}).status_code == 400

    def test_reset_password_too_short_400(self, api_client):
        # MIN_PASSWORD_LENGTH defaults low in some deployments, so use a
        # deliberately longer-than-default weak password plus a valid UUID
        # token (the view parses it before the length check).
        response = _post(
            api_client,
            RESET_PASSWORD_URL,
            {"token": str(uuid.uuid4()), "new_password": "short-password"},
        )
        assert response.status_code == 400

    def test_reset_password_invalid_token_400(self, api_client):
        response = _post(
            api_client,
            RESET_PASSWORD_URL,
            {"token": str(uuid.uuid4()), "new_password": "NewStr0ngPass!"},
        )
        assert response.status_code == 400

    def test_reset_password_expired_token_400(self, api_client, user):
        from django.utils import timezone

        user.password_reset_token = uuid.uuid4()
        user.password_reset_token_expires = timezone.now() - timezone.timedelta(hours=1)
        user.save()
        response = _post(
            api_client,
            RESET_PASSWORD_URL,
            {"token": str(user.password_reset_token), "new_password": "NewStr0ngPass!"},
        )
        assert response.status_code == 400
        assert "expired" in response.json()["error"]

    def test_verify_reset_token_valid_returns_masked_email(self, api_client, user):
        from django.utils import timezone

        user.password_reset_token = uuid.uuid4()
        user.password_reset_token_expires = timezone.now() + timezone.timedelta(hours=1)
        user.save()
        response = _post(
            api_client, VERIFY_RESET_TOKEN_URL, {"token": str(user.password_reset_token)}
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["valid"] is True
        assert payload["email"].startswith(user.email[:2])
        assert "***" in payload["email"]

    def test_verify_reset_token_missing_token_400(self, api_client):
        assert _post(api_client, VERIFY_RESET_TOKEN_URL, {}).status_code == 400

    def test_verify_reset_token_invalid_token(self, api_client):
        response = _post(
            api_client, VERIFY_RESET_TOKEN_URL, {"token": str(uuid.uuid4())}
        )
        assert response.status_code == 200
        assert response.json()["valid"] is False

    def test_verify_reset_token_expired_token(self, api_client, user):
        from django.utils import timezone

        user.password_reset_token = uuid.uuid4()
        user.password_reset_token_expires = timezone.now() - timezone.timedelta(hours=1)
        user.save()
        response = _post(
            api_client, VERIFY_RESET_TOKEN_URL, {"token": str(user.password_reset_token)}
        )
        assert response.json()["valid"] is False
