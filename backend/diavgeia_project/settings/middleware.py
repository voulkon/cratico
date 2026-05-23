"""
Middleware configuration.

Contains MIDDLEWARE settings.
"""

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",  # Must be placed as high as possible to handle CORS on all responses
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "api.middleware.stealth.StealthModeMiddleware",  # Must be after AuthenticationMiddleware
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "api.middleware.rate_limit.RateLimitMiddleware",
    "api.middleware.security.SecurityMonitoringMiddleware",
    "csp.middleware.CSPMiddleware",
]
