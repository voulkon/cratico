"""
Custom authentication backends for Django.
Provides email-based authentication instead of username.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from loguru import logger

User = get_user_model()


class EmailAuthBackend(ModelBackend):
    """
    Authenticate using email address instead of username.
    This allows users to log in with their email and password.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        """
        Authenticate a user by email and password.

        Args:
            request: The HTTP request object
            username: Actually contains the email address (parameter name kept for compatibility)
            password: The user's password
            **kwargs: Additional keyword arguments

        Returns:
            User object if authentication successful, None otherwise
        """
        if username is None or password is None:
            return None

        try:
            # Try to fetch the user by email
            user = User.objects.get(email=username)
        except User.DoesNotExist:
            logger.debug(f"No user found with email: {username}")
            # Run the default password hasher once to reduce timing attacks
            User().set_password(password)
            return None
        except User.MultipleObjectsReturned:
            # This shouldn't happen if email is unique, but handle it gracefully
            logger.warning(f"Multiple users found with email: {username}")
            return None

        # Check the password
        if user.check_password(password) and self.user_can_authenticate(user):
            logger.debug(f"Successfully authenticated user with email: {username}")
            return user

        logger.error(f"Password check failed for email: {username}")
        return None
