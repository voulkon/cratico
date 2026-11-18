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

# Guard against a structurally overcommitted worker configuration.  The
# per-child memory limit is a soft limit for recycling, not a hard cap: every
# child may reach it simultaneously, so concurrency x limit must fit the
# *container* limit (falling back to host memory when no cgroup limit is set).
MAX_MEM_KB=${CELERY_WORKER_MAX_MEMORY_PER_CHILD:-2500000}
MEM_TOTAL_KB=$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)

CGROUP_LIMIT=$(cat /sys/fs/cgroup/memory.max 2>/dev/null || \
               cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || \
               echo "")
LIMIT_KB=0
case "$CGROUP_LIMIT" in
    ""|max) LIMIT_KB=0 ;;
    *)
        # cgroup files report bytes; ignore the "unlimited" sentinel.
        if [ "$CGROUP_LIMIT" -gt 0 ] 2>/dev/null; then
            LIMIT_KB=$((CGROUP_LIMIT / 1024))
        fi
        if [ "$LIMIT_KB" -gt 100000000 ] 2>/dev/null; then
            LIMIT_KB=0
        fi
        ;;
esac
if [ "$LIMIT_KB" -le 0 ]; then
    LIMIT_KB=$MEM_TOTAL_KB
fi

BUDGET_KB=$((CELERY_CONCURRENCY * MAX_MEM_KB))
if [ "$LIMIT_KB" -gt 0 ] && [ "$BUDGET_KB" -gt "$LIMIT_KB" ]; then
    echo "WARNING: Celery memory budget ${BUDGET_KB}KB (${CELERY_CONCURRENCY} x ${MAX_MEM_KB}KB) exceeds the memory limit ${LIMIT_KB}KB."
    echo "WARNING: Reduce CELERY_CONCURRENCY or CELERY_WORKER_MAX_MEMORY_PER_CHILD; overcommit causes abrupt child recycling (SIGKILL) and in-flight task loss."
fi

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
