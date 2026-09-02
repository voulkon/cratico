#!/usr/bin/env bash
# Generate a compose env file on the spot, resolving every variable with
# per-variable logic. Three resolution styles, mixed freely:
#
#   secret_or VAR FALLBACK  — CI secret (env var) wins; otherwise a safe dummy
#   fixed     VAR VALUE     — always this value in generated stacks
#   branch-dependent        — value chosen from the target branch (see below)
#
# Secrets arrive as ordinary env vars (GitHub Actions: `env:` + `secrets.*`).
# The summary printed at the end lists PROVENANCE ONLY — values are never
# echoed.
#
# Usage:
#   scripts/ci/create_env_file.sh [output_path]   # default: .env_files/.env.ci
#
# Then: make stack-up ENV_FILE=.env_files/.env.ci
set -euo pipefail

OUT="${1:-.env_files/.env.ci}"
mkdir -p "$(dirname "$OUT")"
: > "$OUT"
chmod 600 "$OUT"

PROVENANCE=()

put() { # put VAR VALUE SOURCE
  printf '%s=%s\n' "$1" "$2" >> "$OUT"
  PROVENANCE+=("$(printf '%-28s %s' "$1" "$3")")
}

secret_or() { # secret_or VAR FALLBACK
  local var="$1" fallback="$2"
  if [ -n "${!var:-}" ]; then
    put "$var" "${!var}" "secret"
  else
    put "$var" "$fallback" "dummy"
  fi
}

fixed() { put "$1" "$2" "fixed"; }

BRANCH="${GITHUB_BASE_REF:-${GITHUB_REF_NAME:-$(git branch --show-current 2>/dev/null || echo local)}}"

# ── Django core ───────────────────────────────────────────────────────────
secret_or DJANGO_SECRET_KEY 'ci-django-secret-not-real'
fixed     DEBUG             'False'
fixed     ALLOWED_HOSTS     '*'
fixed     ENABLE_SILK       'False'

# ── Database (in-stack postgres service) ──────────────────────────────────
fixed     POSTGRES_USER     'ci_user'
fixed     POSTGRES_PASSWORD 'ci_password'
fixed     POSTGRES_DB       'ci_diavgeia'
fixed     DB_HOST           'db'
fixed     DB_PORT           '5432'

# ── Redis / RabbitMQ (in-stack services) ──────────────────────────────────
fixed     REDIS_HOST        'redis'
fixed     REDIS_PORT        '6379'
fixed     REDIS_DB          '0'
fixed     RABBITMQ_USER     'guest'
fixed     RABBITMQ_PASSWORD 'guest'

# ── Auth matrix ───────────────────────────────────────────────────────────
# Row B (Django-only) is the default: no Clerk keys → backend advertises
# only "django". Provide all three CLERK_* secrets (+ USE_CLERK_AUTH=true)
# to flip a generated stack to row A (dual auth).
secret_or USE_CLERK_AUTH        'false'
secret_or CLERK_PUBLISHABLE_KEY ''
secret_or CLERK_SECRET_KEY      ''
secret_or CLERK_JWT_PUBLIC_KEY  ''

# ── Stealth mode: must stay OFF for E2E (register/login must be reachable) ─
fixed     STEALTH_MODE            'false'
fixed     STEALTH_ALLOWLIST       'false'
fixed     REACT_APP_STEALTH_MODE        'false'
fixed     REACT_APP_STEALTH_ALLOWLIST   'false'

# ── Third-party keys (never exercised by the E2E specs) ───────────────────
secret_or GEMI_API_KEY        'ci-dummy-gemi-key'
secret_or AWS_ACCESS_KEY_ID   'ci-dummy'
secret_or AWS_SECRET_ACCESS_KEY 'ci-dummy'

# ── Stack tuning ──────────────────────────────────────────────────────────
# LIGHT_WORKER=true skips the Docling layer: ~500MB / 2-3min build instead of
# ~13GB / 15+min. Auth E2E never runs a worker job, so light is plenty.
fixed     LIGHT_WORKER        'true'
fixed     FLOWER_BASIC_AUTH   'ci:ci'
fixed     DJANGO_SUPERUSER_USERNAME 'ci-admin'
fixed     DJANGO_SUPERUSER_EMAIL    'ci-admin@example.com'
fixed     DJANGO_SUPERUSER_PASSWORD 'ci-admin-password'
fixed     DJANGO_SUPERUSER_AUTO_UPDATE 'false'

# ── Branch-dependent example ──────────────────────────────────────────────
# Pattern: pick the value from the branch under test. Here: quieter logs on
# main, verbose everywhere else. Add your own cases as needed.
case "$BRANCH" in
  main) fixed BACKEND_LOG_LEVEL 'INFO'  ;;
  *)    fixed BACKEND_LOG_LEVEL 'DEBUG' ;;
esac

echo "Generated $OUT (branch: $BRANCH):"
printf '  %s\n' "${PROVENANCE[@]}"
