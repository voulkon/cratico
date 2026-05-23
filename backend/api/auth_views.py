"""
Django authentication views for when Clerk is not configured.
Provides username/password login and token-based authentication.
"""

from django.contrib.auth import authenticate, login, logout
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from loguru import logger
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@swagger_auto_schema(
    method="post",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=["email", "password"],
        properties={
            "email": openapi.Schema(
                type=openapi.TYPE_STRING, description="User email address"
            ),
            "password": openapi.Schema(
                type=openapi.TYPE_STRING, description="User password"
            ),
            "language": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="Preferred language (en or el)",
                enum=["en", "el"],
            ),
        },
    ),
    responses={
        200: openapi.Response(
            description="Login successful",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "success": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "user": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "id": openapi.Schema(type=openapi.TYPE_INTEGER),
                            "username": openapi.Schema(type=openapi.TYPE_STRING),
                            "email": openapi.Schema(type=openapi.TYPE_STRING),
                            "first_name": openapi.Schema(type=openapi.TYPE_STRING),
                            "last_name": openapi.Schema(type=openapi.TYPE_STRING),
                            "preferred_language": openapi.Schema(
                                type=openapi.TYPE_STRING
                            ),
                        },
                    ),
                    "token": openapi.Schema(
                        type=openapi.TYPE_STRING, description="Authentication token"
                    ),
                },
            ),
        ),
        400: "Bad Request - Missing email or password",
        401: "Unauthorized - Invalid credentials",
    },
)
@api_view(["POST"])
@permission_classes([AllowAny])
def django_login(request):
    """
    Login with Django email/password.
    Creates a session and returns user info + auth token.
    Optionally updates user's preferred language.
    """
    email = request.data.get("email")
    password = request.data.get("password")
    language = request.data.get("language")  # Optional

    if not email or not password:
        return Response(
            {"error": "Email and password are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user = authenticate(request, username=email, password=password)

    if user is not None:
        login(request, user)

        # Update preferred language if provided
        if language and language in ["en", "el"]:
            user.preferred_language = language
            user.save(update_fields=["preferred_language"])
            logger.debug(f"Updated language preference for {email} to {language}")

        # Get or create auth token
        token, created = Token.objects.get_or_create(user=user)

        logger.debug(f"User {email} logged in successfully")

        return Response(
            {
                "success": True,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "preferred_language": getattr(user, "preferred_language", "en"),
                },
                "token": token.key,
            }
        )
    else:
        logger.warning(f"Failed login attempt for email: {email}")
        return Response(
            {"error": "Invalid email or password"}, status=status.HTTP_401_UNAUTHORIZED
        )


@swagger_auto_schema(
    method="post",
    responses={
        200: openapi.Response(
            description="Logout successful",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "success": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "message": openapi.Schema(type=openapi.TYPE_STRING),
                },
            ),
        ),
        400: "Bad Request - Not authenticated",
    },
)
@api_view(["POST"])
@permission_classes([AllowAny])
def django_logout(request):
    """
    Logout current user.
    """
    if request.user.is_authenticated:
        # Delete auth token if it exists
        try:
            request.user.auth_token.delete()
        except:
            pass

        logout(request)
        return Response({"success": True, "message": "Logged out successfully"})
    else:
        return Response(
            {"error": "Not authenticated"}, status=status.HTTP_400_BAD_REQUEST
        )


@swagger_auto_schema(
    method="get",
    responses={
        200: openapi.Response(
            description="Current user info",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "authenticated": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "user": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "id": openapi.Schema(type=openapi.TYPE_INTEGER),
                            "username": openapi.Schema(type=openapi.TYPE_STRING),
                            "email": openapi.Schema(type=openapi.TYPE_STRING),
                            "first_name": openapi.Schema(type=openapi.TYPE_STRING),
                            "last_name": openapi.Schema(type=openapi.TYPE_STRING),
                            "preferred_language": openapi.Schema(
                                type=openapi.TYPE_STRING
                            ),
                        },
                    ),
                },
            ),
        ),
        401: "Not authenticated",
    },
)
@api_view(["GET"])
def current_user(request):
    """
    Get current authenticated user info.
    Requires authentication via Session, Token, or Basic Auth.
    """
    if request.user.is_authenticated:
        return Response(
            {
                "authenticated": True,
                "user": {
                    "id": request.user.id,
                    "username": request.user.username,
                    "email": request.user.email,
                    "first_name": request.user.first_name,
                    "last_name": request.user.last_name,
                    "preferred_language": getattr(
                        request.user, "preferred_language", "en"
                    ),
                },
            }
        )
    else:
        return Response({"authenticated": False}, status=status.HTTP_401_UNAUTHORIZED)


@swagger_auto_schema(
    method="post",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=["email", "password", "first_name", "last_name"],
        properties={
            "email": openapi.Schema(
                type=openapi.TYPE_STRING, description="User email address"
            ),
            "password": openapi.Schema(
                type=openapi.TYPE_STRING, description="User password (min 8 characters)"
            ),
            "first_name": openapi.Schema(
                type=openapi.TYPE_STRING, description="User first name"
            ),
            "last_name": openapi.Schema(
                type=openapi.TYPE_STRING, description="User last name"
            ),
            "language": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="Preferred language (en or el)",
                enum=["en", "el"],
            ),
        },
    ),
    responses={
        201: openapi.Response(
            description="Registration successful",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "success": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "user": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "id": openapi.Schema(type=openapi.TYPE_INTEGER),
                            "username": openapi.Schema(type=openapi.TYPE_STRING),
                            "email": openapi.Schema(type=openapi.TYPE_STRING),
                            "first_name": openapi.Schema(type=openapi.TYPE_STRING),
                            "last_name": openapi.Schema(type=openapi.TYPE_STRING),
                            "preferred_language": openapi.Schema(
                                type=openapi.TYPE_STRING
                            ),
                        },
                    ),
                    "token": openapi.Schema(
                        type=openapi.TYPE_STRING, description="Authentication token"
                    ),
                },
            ),
        ),
        400: "Bad Request - Missing fields or email already exists",
    },
)
@api_view(["POST"])
@permission_classes([AllowAny])
def django_register(request):
    """
    Register a new user with Django email/password.
    Automatically logs in the user and returns auth token.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()

    email = request.data.get("email")
    password = request.data.get("password")
    first_name = request.data.get("first_name")
    last_name = request.data.get("last_name")
    language = request.data.get("language", "en")  # Default to English

    # Validate required fields
    if not all([email, password, first_name, last_name]):
        return Response(
            {"error": "Email, password, first name, and last name are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Validate password length
    from django.conf import settings

    min_length = getattr(settings, "MIN_PASSWORD_LENGTH", 8)
    if len(password) < min_length:
        return Response(
            {"error": f"Password must be at least {min_length} characters long"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Check if user already exists
    if User.objects.filter(email=email).exists():
        return Response(
            {"error": "A user with this email already exists"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Validate language
    if language not in ["en", "el"]:
        language = "en"

    try:
        # Create user
        user = User.objects.create_user(
            username=email,  # Use email as username
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )

        # Set preferred language
        user.preferred_language = language
        user.save(update_fields=["preferred_language"])

        # Auto-login the user
        login(request, user)

        # Create auth token
        token, created = Token.objects.get_or_create(user=user)

        logger.info(f"New user registered: {email}")

        return Response(
            {
                "success": True,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "preferred_language": user.preferred_language,
                },
                "token": token.key,
            },
            status=status.HTTP_201_CREATED,
        )

    except Exception as e:
        logger.error(f"Error creating user {email}: {str(e)}")
        return Response(
            {"error": f"Failed to create user: {str(e)}"},
            status=status.HTTP_400_BAD_REQUEST,
        )
