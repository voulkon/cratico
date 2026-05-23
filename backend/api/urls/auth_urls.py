"""
URL patterns for Django native authentication.

These endpoints provide traditional email/password authentication
alongside Clerk authentication.

Usage:
    Include in main urls.py:
    path('auth/django/', include('api.urls.auth_urls')),
"""

from api.views import django_auth
from django.urls import path

urlpatterns = [
    path("register/", django_auth.register, name="django-register"),
    path("login/", django_auth.login, name="django-login"),
    path("logout/", django_auth.logout, name="django-logout"),
    path("verify-email/", django_auth.verify_email, name="django-verify-email"),
    path("me/", django_auth.me, name="django-me"),
]
