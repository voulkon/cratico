#!/usr/bin/env bash
# Wait until a URL answers, then fail with container logs if it never does.
#
# Usage: wait_for_url.sh <url> <compose-file> <env-file> <service> [timeout_secs] [project_name]
set -euo pipefail

URL="${1:?usage: wait_for_url.sh <url> <compose-file> <env-file> <service> [timeout] [project]}"
COMPOSE_FILE="${2:?missing compose file}"
ENV_FILE="${3:?missing env file}"
SERVICE="${4:?missing service}"
TIMEOUT="${5:-120}"
PROJECT="${6:-}"

# Compose args: isolate by project name when one is given (CI stack).
COMPOSE_ARGS=(-f "$COMPOSE_FILE" --env-file "$ENV_FILE")
[ -n "$PROJECT" ] && COMPOSE_ARGS+=(-p "$PROJECT")

deadline=$(( $(date +%s) + TIMEOUT ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  if curl -sf "$URL" > /dev/null 2>&1; then
    echo "✓ $URL is up"
    exit 0
  fi
  sleep 2
done

echo "✗ $URL did not come up within ${TIMEOUT}s — dumping $SERVICE logs:" >&2
docker compose "${COMPOSE_ARGS[@]}" logs "$SERVICE" >&2
exit 1
