import os

from .settings import *

# Start with the existing database configuration
test_db_config = DATABASES["default"].copy()

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
DATABASE_URL = os.environ.get("DATABASE_URL")

if TEST_DATABASE_URL:
    from urllib.parse import urlparse

    parsed = urlparse(TEST_DATABASE_URL)

    test_db_config = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": parsed.username,
        "PASSWORD": parsed.password,
        "HOST": parsed.hostname,
        "PORT": parsed.port or 5432,
    }
    print(
        f"Using TEST_DATABASE_URL: {parsed.hostname}:{parsed.port}/{parsed.path.lstrip('/')}"
    )
elif DATABASE_URL:
    # Use the main DATABASE_URL but override HOST to localhost for local testing
    from urllib.parse import urlparse

    parsed = urlparse(DATABASE_URL)

    test_db_config = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": parsed.username,
        "PASSWORD": parsed.password,
        "HOST": parsed.hostname,  # Override to localhost for local testing
        "PORT": parsed.port or 5432,
    }
    print(
        f"Using DATABASE_URL: {parsed.hostname}:{parsed.port}/{parsed.path.lstrip('/')}"
    )
else:
    # Fallback to individual environment variables with test-specific overrides
    test_db_config = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get(
            "TEST_DB_NAME", os.environ.get("POSTGRES_DB", "test_local_diavgia")
        ),
        "USER": os.environ.get(
            "TEST_DB_USER", os.environ.get("POSTGRES_USER", "postgres")
        ),
        "PASSWORD": os.environ.get(
            "TEST_DB_PASSWORD", os.environ.get("POSTGRES_PASSWORD", "postgres")
        ),
        "HOST": os.environ.get(
            "TEST_DB_HOST", "localhost"
        ),  # Always localhost for tests
        "PORT": os.environ.get("TEST_DB_PORT", os.environ.get("DB_PORT", "5432")),
    }
    print(
        f"Using individual env vars: localhost:{test_db_config['PORT']}/{test_db_config['NAME']}"
    )


# Use the test database configuration
DATABASES = {"default": test_db_config}

print(
    f"PostgreSQL connection details: HOST={test_db_config['HOST']} DB={test_db_config['NAME']}"
)

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

# Add a setting to indicate we're using PostgreSQL for tests
USING_POSTGRESQL_FOR_TESTS = True
