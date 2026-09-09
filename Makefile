.PHONY: lint lint-install sample-data reset-db quality quality-report quality-check quality-ai quality-css quality-ai-report quality-css-report help stack-up stack-down stack-logs wait-for-api e2e e2e-headed e2e-phase e2e-phases e2e-sweep

# ───────────────────────── Help ─────────────────────────

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ───────────────────────── Stack (docker compose) ─────────────────────────

COMPOSE_FILE ?= docker/docker-compose.yml
ENV_FILE ?= .env_files/.env.local.secrets
API_URL ?= http://localhost/api/system/config/auth/

# docker/docker-compose.yml interpolates ${ENV_FILE:-...} inside its own
# `env_file:` directives, so it must be visible in the environment, not just
# as a make variable. Without this, every service silently falls back to
# .env.local.secrets (which doesn't exist in CI).
export ENV_FILE

stack-up: ## Boot the compose stack (override with COMPOSE_FILE=... ENV_FILE=...)
	docker compose -f $(COMPOSE_FILE) --env-file=$(ENV_FILE) up -d
	$(MAKE) wait-for-api

stack-down: ## Tear down the compose stack
	docker compose -f $(COMPOSE_FILE) --env-file=$(ENV_FILE) down

# CI/e2e stack: isolated project name => isolated volumes. Prevents the
# "FATAL: password authentication failed" trap: the postgres image only
# applies POSTGRES_USER/PASSWORD on first volume init, so a generated
# .env.ci with different credentials can't reuse the local volume.
stack-up-ci: ## Boot an isolated CI-style stack (own project name + volumes)
	COMPOSE_PROJECT_NAME=diavgeia-ci docker compose -f $(COMPOSE_FILE) --env-file=$(ENV_FILE) up -d
	COMPOSE_PROJECT_NAME=diavgeia-ci $(MAKE) wait-for-api

stack-down-ci: ## Tear down the isolated CI stack (including its volumes)
	COMPOSE_PROJECT_NAME=diavgeia-ci docker compose -f $(COMPOSE_FILE) --env-file=$(ENV_FILE) down -v

stack-logs: ## Tail backend logs
	docker compose -f $(COMPOSE_FILE) --env-file=$(ENV_FILE) logs -f backend

wait-for-api: ## Block until the auth-config endpoint answers
	scripts/ci/wait_for_url.sh $(API_URL) $(COMPOSE_FILE) $(ENV_FILE) backend

.PHONY: stack-up-ci stack-down-ci

# ───────────────────────── E2E (Playwright) ─────────────────────────

# SPEC scopes to specific files, e.g. make e2e SPEC="e2e/auth.spec.js e2e/clerk.spec.js"
e2e: ## Run Playwright E2E against the running stack (override with SPEC=...)
	cd frontend && npx playwright test $(SPEC)

e2e-headed: ## Run Playwright E2E with a visible browser
	cd frontend && npx playwright test --headed $(SPEC)

# Per-spec data lifecycle (called by frontend/e2e/lifecycle.js).
# e2e-phase SPEC=auth PHASE=setup|teardown RUN_ID=abc123
# Backend no-ops undeclared phases — parity lives in
# backend/api/e2e_fixtures/__init__.py (REGISTRY).
e2e-phase: ## Run backend e2e data phase: make e2e-phase SPEC=auth PHASE=setup RUN_ID=xyz
	docker compose -f $(COMPOSE_FILE) --env-file=$(ENV_FILE) exec -T backend \
	  python manage.py e2e_data --spec=$(SPEC) --phase=$(PHASE) --run-id=$(RUN_ID)

e2e-phases: ## List the spec → phases registry
	docker compose -f $(COMPOSE_FILE) --env-file=$(ENV_FILE) exec -T backend \
	  python manage.py e2e_data --list

e2e-sweep: ## GC abandoned e2e data (crashed runs older than HOURS=6)
	docker compose -f $(COMPOSE_FILE) --env-file=$(ENV_FILE) exec -T backend \
	  python manage.py e2e_data --sweep-stale --max-age-hours=$(HOURS)

# ───────────────────────── Linting (pre-commit) ─────────────────────────

lint:
	pre-commit run --all-files

lint-install:
	pip install pre-commit && pre-commit install

# ───────────────────────── Data Management (TODO) ─────────────────────────

sample-data:
	@echo "TODO: implement sample data generation"
	@exit 1

reset-db:
	@echo "TODO: implement DB reset with sample data"
	@exit 1

# ───────────────────────── Code Quality ─────────────────────────

quality: quality-report
	@echo ""
	@echo "[OK] Quality checks complete! Review the report at: reports/quality-report.md"

quality-report:
	@echo "Generating comprehensive quality report..."
	@mkdir -p reports
	@python3 scripts/generate_quality_report.py --format markdown --output reports/quality-report.md
	@python3 scripts/generate_quality_report.py --format json --output reports/quality-report.json
	@echo "[OK] Reports generated:"
	@echo "   - reports/quality-report.md"
	@echo "   - reports/quality-report.json"

quality-check:
	@echo "Running quick quality checks (CI mode)..."
	@python3 scripts/detect_ai_slop.py backend --ci --quiet
	@python3 scripts/detect_hardcoded_colors.py frontend --ci --quiet
	@echo "[OK] Quality checks passed!"

quality-ai:
	@echo "Checking for AI-generated patterns..."
	@python3 scripts/detect_ai_slop.py backend frontend scripts

quality-css:
	@echo "Checking for hard-coded colors..."
	@python3 scripts/detect_hardcoded_colors.py frontend

quality-ai-report:
	@echo "Generating AI slop report..."
	@mkdir -p reports
	@python3 scripts/detect_ai_slop.py backend frontend scripts --report markdown --output reports/ai-slop-report.md
	@echo "[OK] Report saved to: reports/ai-slop-report.md"

quality-css-report:
	@echo "Generating hard-coded colors report..."
	@mkdir -p reports
	@python3 scripts/detect_hardcoded_colors.py frontend --report markdown --output reports/css-colors-report.md
	@echo "[OK] Report saved to: reports/css-colors-report.md"
