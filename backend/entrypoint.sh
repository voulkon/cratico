#!/bin/sh

# Wait for database
echo "Waiting for database..."
python manage.py wait_for_db

# Wait for Redis
echo "Waiting for Redis..."
python manage.py wait_for_redis

if [ "${INDEX_THE_OPENSEARCH:-true}" = "true" ]; then
    # Wait for OpenSearch only if it is part of the stack (the "search"
    # compose profile can leave it out, in which case the hostname won't
    # resolve). The OpenSearchService circuit breaker degrades gracefully.
    OPENSEARCH_HOST=$(echo "${OPENSEARCH_URL:-http://opensearch:9200}" | sed -E 's#^[a-z]+://##; s#[:/].*##')
    if getent hosts "$OPENSEARCH_HOST" >/dev/null 2>&1; then
        echo "Waiting for OpenSearch..."
        python manage.py wait_for_opensearch
    else
        echo "OpenSearch not in stack (search profile off) — skipping wait."
    fi
fi

# Wait for Loki (only if it is part of the stack — the "observability"
# compose profile can leave it out, in which case the hostname won't resolve)
if getent hosts "${LOKI_HOST:-loki}" >/dev/null 2>&1; then
    echo "Waiting for Loki..."
    python manage.py wait_for_loki
else
    echo "Loki not in stack (observability profile off) — skipping wait."
fi

if [ "${INDEX_THE_OPENSEARCH:-true}" = "true" ]; then
    echo "Setting up OpenSearch Greek language support..."
    python manage.py setup_opensearch_greek
fi

# Test services integration
echo "Testing services integration..."
python manage.py test_services_integration

# From inside the docker container
# python manage.py makemigrations
# echo "Migrations created."

# Run migrations
echo "Running migrations..."
python manage.py migrate

# Create superuser if needed
echo "Creating superuser if it doesn't exist..."
python manage.py create_superuser

# Initialize feature flags
echo "Initializing feature flags..."
python manage.py initialize_feature_flags

# Collect static files (needed for admin CSS/JS in production when DEBUG=False)
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Run the server
if [ "$DEBUG" = "True" ]; then
    echo "Starting in debug mode on port ${DJANGO_DEBUG_PORT:-8002}..."
    python -Xfrozen_modules=off -m debugpy --listen 0.0.0.0:${DJANGO_DEBUG_PORT:-8002} manage.py runserver 0.0.0.0:8000
else
    echo "Starting in production mode..."
    gunicorn diavgeia_project.wsgi:application --bind 0.0.0.0:8000 --timeout 300 --workers 2
fi
