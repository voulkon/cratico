"""
Middleware configuration.

Contains MIDDLEWARE settings.
"""

from .base import ENABLE_SILK

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",  # Must be placed as high as possible to handle CORS on all responses
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    *(["silk.middleware.SilkyMiddleware"] if ENABLE_SILK else []),
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "api.middleware.stealth.StealthModeMiddleware",  # Must be after AuthenticationMiddleware
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "api.middleware.rate_limit.RateLimitMiddleware",
    "api.middleware.security.SecurityMonitoringMiddleware",
    "api.middleware.security_monitoring.SecurityMonitoringResponseMiddleware",  # Response-side threat detection + forensic logging
    "csp.middleware.CSPMiddleware",
]
