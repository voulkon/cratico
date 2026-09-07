#!/bin/sh
# Celery beat with DatabaseScheduler queries django_celery_beat_* tables at
# startup. On a fresh stack, migrations run in the backend entrypoint, so beat
# must retry instead of crashing on ProgrammingError (relation does not exist).

echo "Waiting for database..."
python manage.py wait_for_db

# Backend runs migrations in its entrypoint; poll until the beat tables exist.
echo "Waiting for django_celery_beat tables (migrations)..."
for i in $(seq 1 60); do
    if python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'diavgeia_project.settings')
django.setup()
from django.db import connection
with connection.cursor() as c:
    c.execute(\"SELECT 1 FROM django_celery_beat_crontabschedule LIMIT 1\")
" 2>/dev/null; then
        echo "Beat tables ready."
        break
    fi
    echo "Beat tables not ready yet ($i/60), waiting 2s..."
    sleep 2
done

echo "Starting Celery beat..."
exec celery -A diavgeia_project beat -l INFO
