#!/bin/sh

# Wait for database
echo "Waiting for database..."
python manage.py wait_for_db

# Wait for Loki (only if it is part of the stack — the "observability"
# compose profile can leave it out, in which case the hostname won't resolve)
if getent hosts "${LOKI_HOST:-loki}" >/dev/null 2>&1; then
    echo "Waiting for Loki..."
    python manage.py wait_for_loki
else
    echo "Loki not in stack (observability profile off) — skipping wait."
fi

# Wait for Redis/RabbitMQ
echo "Waiting for broker..."
sleep 5

# Run celery worker with or without debugging
# Default concurrency to 2 to avoid OOM with heavy ML models
CELERY_CONCURRENCY=${CELERY_CONCURRENCY:-2}

# Log the worker configuration
echo "=========================================="
echo "Celery Worker Configuration"
echo "=========================================="
echo "Concurrency: ${CELERY_CONCURRENCY} workers"
echo "Max Tasks Per Child: ${CELERY_WORKER_MAX_TASKS_PER_CHILD:-100}"
echo "Max Memory Per Child: ${CELERY_WORKER_MAX_MEMORY_PER_CHILD:-2500000} KB (~$((${CELERY_WORKER_MAX_MEMORY_PER_CHILD:-2500000}/1024/1024))GB)"
echo "Debug Mode: ${DEBUG:-False}"
if [ "$DEBUG" = "True" ]; then
    echo "Debug Port: ${CELERY_DEBUG_PORT:-8004}"
fi
echo "=========================================="

if [ "$DEBUG" = "True" ]; then
    echo "Starting Celery worker in debug mode on port ${CELERY_DEBUG_PORT:-8004} with concurrency ${CELERY_CONCURRENCY}..."
    python -Xfrozen_modules=off -m debugpy --listen 0.0.0.0:${CELERY_DEBUG_PORT:-8004} -m celery -A diavgeia_project worker -l INFO --concurrency=${CELERY_CONCURRENCY}
else
    echo "Starting Celery worker in production mode with concurrency ${CELERY_CONCURRENCY}..."
    celery -A diavgeia_project worker -l INFO --concurrency=${CELERY_CONCURRENCY}
fi
