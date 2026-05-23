"""
Application settings.

Contains INSTALLED_APPS configuration.
"""

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",  # For intcomma and other filters
    "core.apps.CoreConfig",
    "rest_framework",
    "rest_framework.authtoken",
    "admin_custom",
    "users",
    "api",
    "notifications",  # Notification system
    "experiments",  # Experimental decomposition strategies
    "drf_yasg",
    "corsheaders",
    "django_celery_results",
    "django_celery_beat",
]
