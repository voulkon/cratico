"""
Security settings.

Contains CORS, CSP, and cookie security configurations.
"""

# Import from base module for FRONTEND_DOMAINS_clean and DEBUG
from .base import DEBUG, FRONTEND_DOMAINS_clean

#####CORS Settings#####

CORS_ALLOW_CREDENTIALS = True
if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True  # Only in development
else:
    CORS_ALLOWED_ORIGINS = FRONTEND_DOMAINS_clean

# CSRF
CSRF_TRUSTED_ORIGINS = FRONTEND_DOMAINS_clean

# Important: Allow CORS headers for rate limiting responses
CORS_EXPOSE_HEADERS = [
    "X-RateLimit-Limit",
    "X-RateLimit-Remaining",
    "X-RateLimit-Reset",
]

#####CORS Settings#####

# Create a common base list for Clerk CSP settings
CLERK_CSP_SOURCES = ["'self'", "https://api.clerk.com", *FRONTEND_DOMAINS_clean]

#####Content Security Policy#####
CSP_DEFAULT_SRC = ["'self'"]
CSP_SCRIPT_SRC = CLERK_CSP_SOURCES
CSP_STYLE_SRC = ["'self'", "'unsafe-inline'"]  # Often needed for styling
CSP_CONNECT_SRC = CLERK_CSP_SOURCES
CSP_IMG_SRC = ["'self'", "https://img.clerk.com"]  # For Clerk avatars/images
CSP_FRAME_SRC = ["'self'", "https://accounts.clerk.dev"]  # For embedded iframes
#####Content Security Policy#####


#####Cookies#####
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = not DEBUG
    SESSION_COOKIE_SECURE = not DEBUG
    CSRF_COOKIE_SECURE = not DEBUG
#####Cookies#####
