"""
Django native authentication endpoints.

Provides traditional email/password registration and login alongside Clerk.
Useful for:
- Development and testing
- Admin/internal users
- Fallback authentication
- Testing without Clerk credentials

These endpoints coexist with Clerk - users can authenticate via either method.
"""

import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from loguru import logger
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

User = get_user_model()


@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def register(request):
    """
    Register a new user with email and password.

    Request:
    {
        "email": "user@example.com",
        "password": "secure_password",
        "username": "optional_username"  // Optional, defaults to email
    }

    Response:
    {
        "user": {
            "id": 1,
            "email": "user@example.com",
            "username": "user@example.com"
        },
        "token": "drf_token_here"
    }
    """
    email = request.data.get("email")
    password = request.data.get("password")
    username = request.data.get("username", email)  # Default username to email

    # Validate
    if not email or not password:
        return Response(
            {"error": "Email and password are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Check if user exists
    if User.objects.filter(email=email).exists():
        return Response(
            {"error": "User with this email already exists"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        # Create user - inactive until email is verified
        user = User.objects.create_user(
            email=email,
            username=username,
            password=password,
            is_active=False,  # User cannot login until email is verified
        )

        # Generate verification token
        verification_token = uuid.uuid4()
        user.email_verification_token = verification_token
        user.email_verification_token_expires = timezone.now() + timedelta(hours=24)
        user.save()

        # Send verification email
        email_sent = False
        if (
            getattr(settings, "DEFAULT_FROM_EMAIL", None)
            and settings.DEFAULT_FROM_EMAIL != "YOUR-ACCESS-KEY-ID"
        ):
            try:
                from core.email_service import RegistrationEmailService

                email_sent = RegistrationEmailService.send_verification_email(
                    user_email=user.email,
                    username=user.username,
                    verification_token=str(verification_token),
                )
                if email_sent:
                    logger.debug(f"Verification email sent to: {user.email}")
                else:
                    logger.warning(
                        f"Failed to send verification email to: {user.email}"
                    )
            except Exception as e:
                logger.error(f"Error sending verification email: {e}", exc_info=True)
        else:
            logger.warning(
                "Email not configured - user created but no verification email sent"
            )

        logger.debug(f"Created Django user (pending verification): {user.email}")

        return Response(
            {
                "message": "Registration successful! Please check your email to verify your account.",
                "email": user.email,
                "verification_required": True,
                "email_sent": email_sent,
            },
            status=status.HTTP_201_CREATED,
        )

    except Exception as e:
        logger.error(f"Error creating user: {e}", exc_info=True)
        return Response(
            {"error": "Failed to create user"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def login(request):
    """
    Login with email and password.

    Request:
    {
        "email": "user@example.com",
        "password": "password"
    }

    Response:
    {
        "user": {
            "id": 1,
            "email": "user@example.com",
            "username": "user@example.com"
        },
        "token": "drf_token_here"
    }
    """
    email = request.data.get("email")
    password = request.data.get("password")

    if not email or not password:
        return Response(
            {"error": "Email and password are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Authenticate using Django's auth backends
    user = authenticate(request, username=email, password=password)

    if user is None:
        return Response(
            {"error": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED
        )

    # Check if user is active (for Django-registered users, this means email is verified)
    if not user.is_active:
        # Check if it's specifically because email is not verified
        if not user.email_verified and user.email_verification_token:
            return Response(
                {
                    "error": "Email not verified. Please check your email for the verification link.",
                    "verification_required": True,
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(
            {"error": "User account is disabled"}, status=status.HTTP_403_FORBIDDEN
        )

    # Get or create DRF token
    token, _ = Token.objects.get_or_create(user=user)

    logger.debug(f"Django login: {user.email}")

    return Response(
        {
            "user": {
                "id": user.id,
                "email": user.email,
                "username": user.username,
            },
            "token": token.key,
        }
    )


@csrf_exempt
@api_view(["POST"])
def logout(request):
    """
    Logout - delete the user's auth token.

    Requires authentication.
    """
    if not request.user or not request.user.is_authenticated:
        return Response(
            {"error": "Not authenticated"}, status=status.HTTP_401_UNAUTHORIZED
        )

    # Delete the user's token (if using token auth)
    try:
        Token.objects.filter(user=request.user).delete()
        logger.debug(f"Logged out user: {request.user.email}")
    except Exception:
        pass  # No token to delete

    return Response({"message": "Logged out successfully"})


@csrf_exempt
@api_view(["POST", "GET"])
@permission_classes([AllowAny])
def verify_email(request):
    """
    Verify user's email address using the token sent via email.

    Supports both GET (from email link) and POST (from frontend form).

    GET: /auth/verify-email/?token=uuid-token-from-email
    POST: {"token": "uuid-token-from-email"}

    Response:
    {
        "message": "Email verified successfully",
        "user": {...},
        "token": "drf_token_here"
    }
    """
    # Support both GET and POST
    if request.method == "GET":
        verification_token = request.query_params.get("token")
    else:
        verification_token = request.data.get("token")

    if not verification_token:
        return Response(
            {"error": "Verification token is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        # Find user with this verification token
        user = User.objects.get(email_verification_token=verification_token)

        # Check if token has expired
        if (
            user.email_verification_token_expires
            and user.email_verification_token_expires < timezone.now()
        ):
            return Response(
                {"error": "Verification token has expired. Please request a new one."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if already verified
        if user.email_verified and user.is_active:
            return Response(
                {"message": "Email already verified. You can log in now."},
                status=status.HTTP_200_OK,
            )

        # Verify the user
        user.email_verified = True
        user.is_active = True  # Allow login
        user.email_verification_token = None  # Clear the token
        user.email_verification_token_expires = None
        user.save()

        # Create DRF token for automatic login
        token, _ = Token.objects.get_or_create(user=user)

        # Optionally send welcome email
        if (
            getattr(settings, "DEFAULT_FROM_EMAIL", None)
            and settings.DEFAULT_FROM_EMAIL != "YOUR-ACCESS-KEY-ID"
        ):
            try:
                from core.email_service import RegistrationEmailService

                RegistrationEmailService.send_welcome_email(
                    user_email=user.email, username=user.username
                )
            except Exception as e:
                logger.warning(f"Failed to send welcome email: {e}")

        logger.debug(f"Email verified for user: {user.email}")

        return Response(
            {
                "message": "Email verified successfully! You are now logged in.",
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username,
                },
                "token": token.key,
            },
            status=status.HTTP_200_OK,
        )

    except User.DoesNotExist:
        return Response(
            {"error": "Invalid verification token"}, status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        logger.error(f"Error verifying email: {e}", exc_info=True)
        return Response(
            {"error": "Failed to verify email"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def request_password_reset(request):
    """
    Request a password reset email.

    Request:
    {
        "email": "user@example.com"
    }

    Response:
    {
        "message": "If an account with that email exists, a password reset link has been sent."
    }

    Note: Returns the same message whether the user exists or not (for security).
    """
    email = request.data.get("email")

    if not email:
        return Response(
            {"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST
        )

    try:
        # Try to find the user (don't reveal if user exists or not)
        user = User.objects.get(email=email, is_active=True)

        # Only allow password reset for Django users (not Clerk users)
        if user.clerk_id:
            # For Clerk users, they should use Clerk's password reset
            logger.debug(f"Password reset attempted for Clerk user: {email}")
            # Still return success message (don't reveal it's a Clerk user)
            return Response(
                {
                    "message": "If an account with that email exists, a password reset link has been sent.",
                    "note": "For Clerk users, please use the Clerk password reset flow.",
                }
            )

        # Generate password reset token
        reset_token = uuid.uuid4()
        user.password_reset_token = reset_token
        user.password_reset_token_expires = timezone.now() + timedelta(
            hours=1
        )  # 1 hour expiry
        user.save()

        # Send password reset email
        email_sent = False
        if (
            getattr(settings, "DEFAULT_FROM_EMAIL", None)
            and settings.DEFAULT_FROM_EMAIL != "YOUR-ACCESS-KEY-ID"
        ):
            try:
                from core.email_service import PasswordResetEmailService

                email_sent = PasswordResetEmailService.send_password_reset_email(
                    user_email=user.email,
                    username=user.username,
                    reset_token=str(reset_token),
                )
                if email_sent:
                    logger.debug(f"Password reset email sent to: {user.email}")
                else:
                    logger.warning(
                        f"Failed to send password reset email to: {user.email}"
                    )
            except Exception as e:
                logger.error(f"Error sending password reset email: {e}", exc_info=True)
        else:
            logger.warning(
                "Email not configured - password reset requested but no email sent"
            )

        # Always return success message (don't reveal if user exists)
        return Response(
            {
                "message": "If an account with that email exists, a password reset link has been sent.",
                "email_sent": email_sent,
            }
        )

    except User.DoesNotExist:
        # Don't reveal that user doesn't exist - return same message
        logger.debug(f"Password reset requested for non-existent email: {email}")
        return Response(
            {
                "message": "If an account with that email exists, a password reset link has been sent."
            }
        )
    except Exception as e:
        logger.error(f"Error processing password reset request: {e}", exc_info=True)
        return Response(
            {"error": "Failed to process password reset request"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def reset_password(request):
    """
    Reset password using the token from email.

    Request:
    {
        "token": "uuid-token-from-email",
        "new_password": "new_secure_password"
    }

    Response:
    {
        "message": "Password reset successfully",
        "user": {...},
        "token": "drf_token_here"
    }
    """
    reset_token = request.data.get("token")
    new_password = request.data.get("new_password")

    if not reset_token or not new_password:
        return Response(
            {"error": "Token and new password are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Validate password strength
    min_length = getattr(settings, "MIN_PASSWORD_LENGTH", 8)
    if len(new_password) < min_length:
        return Response(
            {"error": f"Password must be at least {min_length} characters long"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        # Find user with this reset token
        user = User.objects.get(password_reset_token=reset_token)

        # Check if token has expired
        if (
            user.password_reset_token_expires
            and user.password_reset_token_expires < timezone.now()
        ):
            return Response(
                {
                    "error": "Password reset token has expired. Please request a new one."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Reset the password
        user.set_password(new_password)
        user.password_reset_token = None  # Clear the token
        user.password_reset_token_expires = None
        user.save()

        # Send confirmation email
        if (
            getattr(settings, "DEFAULT_FROM_EMAIL", None)
            and settings.DEFAULT_FROM_EMAIL != "YOUR-ACCESS-KEY-ID"
        ):
            try:
                from core.email_service import PasswordResetEmailService

                PasswordResetEmailService.send_password_changed_notification(
                    user_email=user.email, username=user.username
                )
            except Exception as e:
                logger.warning(f"Failed to send password changed notification: {e}")

        # Create new DRF token for automatic login
        Token.objects.filter(user=user).delete()  # Delete old token
        token = Token.objects.create(user=user)

        logger.debug(f"Password reset successfully for: {user.email}")

        return Response(
            {
                "message": "Password reset successfully! You are now logged in.",
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username,
                },
                "token": token.key,
            },
            status=status.HTTP_200_OK,
        )

    except User.DoesNotExist:
        return Response(
            {"error": "Invalid or expired reset token"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as e:
        logger.error(f"Error resetting password: {e}", exc_info=True)
        return Response(
            {"error": "Failed to reset password"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def verify_reset_token(request):
    """
    Verify if a password reset token is valid (without resetting the password).

    Useful for the frontend to check if the token in the URL is valid
    before showing the password reset form.

    Request:
    {
        "token": "uuid-token-from-email"
    }

    Response:
    {
        "valid": true,
        "email": "us***@example.com"  // Masked email
    }
    """
    reset_token = request.data.get("token")

    if not reset_token:
        return Response(
            {"error": "Token is required"}, status=status.HTTP_400_BAD_REQUEST
        )

    try:
        # Find user with this reset token
        user = User.objects.get(password_reset_token=reset_token)

        # Check if token has expired
        if (
            user.password_reset_token_expires
            and user.password_reset_token_expires < timezone.now()
        ):
            return Response({"valid": False, "error": "Token has expired"})

        # Mask the email address for security
        email_parts = user.email.split("@")
        if len(email_parts) == 2:
            masked_email = f"{email_parts[0][:2]}***@{email_parts[1]}"
        else:
            masked_email = "***"

        return Response({"valid": True, "email": masked_email})

    except User.DoesNotExist:
        return Response({"valid": False, "error": "Invalid token"})
    except Exception as e:
        logger.error(f"Error verifying reset token: {e}", exc_info=True)
        return Response(
            {"error": "Failed to verify token"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
def me(request):
    """
    Get current authenticated user info.

    Works for both Django-authenticated and Clerk-authenticated users.
    """
    if not request.user or not request.user.is_authenticated:
        return Response(
            {"error": "Not authenticated"}, status=status.HTTP_401_UNAUTHORIZED
        )

    return Response(
        {
            "user": {
                "id": request.user.id,
                "email": request.user.email,
                "username": request.user.username,
                "auth_method": (
                    "clerk" if hasattr(request.user, "clerk_id") else "django"
                ),
            }
        }
    )
