#!/bin/sh
#
# Dead-man's switch for the Celery consumer.
#
# Run every 5 minutes from host cron/systemd:
#   */5 * * * * ALERT_WEBHOOK_URL=https://... /path/to/check_celery_health.sh
#
# Alerts when the `celery` queue has messages but no consumers — the exact
# 2026-11-10 failure mode.  Deliberately independent of Prometheus/Grafana so
# it keeps working when the observability stack is down.
#
# Exit codes:
#   0 healthy (or no webhook configured)
#   1 alert triggered / webhook failed
#   2 inspection failed (docker/rabbitmqctl unavailable)

set -eu

RABBITMQ_CONTAINER="${RABBITMQ_CONTAINER:-diavgeia_rabbitmq}"
QUEUE="${CELERY_QUEUE:-celery}"
WEBHOOK_URL="${ALERT_WEBHOOK_URL:-}"

row="$(
  docker exec "$RABBITMQ_CONTAINER" \
    rabbitmqctl list_queues name messages consumers --quiet 2>/dev/null \
  | awk -v q="$QUEUE" '$1 == q { print $2 " " $3; exit }'
)" || {
  echo "check_celery_health: cannot inspect RabbitMQ in $RABBITMQ_CONTAINER" >&2
  exit 2
}

if [ -z "$row" ]; then
  echo "check_celery_health: queue '$QUEUE' not found" >&2
  exit 2
fi

messages="$(echo "$row" | cut -d' ' -f1)"
consumers="$(echo "$row" | cut -d' ' -f2)"

if [ "$consumers" -eq 0 ] && [ "$messages" -gt 0 ]; then
  message="Celery queue '$QUEUE' has $messages messages and 0 consumers"
  echo "ALERT: $message" >&2
  if [ -n "$WEBHOOK_URL" ]; then
    payload="$(printf '{"text":"%s"}' "$message")"
    curl --fail --silent --show-error --max-time 10 \
      -H 'Content-Type: application/json' \
      -d "$payload" "$WEBHOOK_URL" >/dev/null || exit 1
  fi
  exit 1
fi

echo "check_celery_health: OK (queue=$QUEUE messages=$messages consumers=$consumers)"
exit 0
