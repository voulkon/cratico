DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Speed up password hashing in tests
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# Disable SSL redirects in tests (prevents 301 redirects)
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Make sure DEBUG is True for tests
DEBUG = True

# Add a setting to indicate we're using SQLite for tests
USING_POSTGRESQL_FOR_TESTS = False
