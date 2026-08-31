.PHONY: lint lint-install sample-data reset-db quality quality-report quality-check quality-ai quality-css quality-ai-report quality-css-report help stack-up stack-down stack-logs wait-for-api e2e e2e-headed

# ───────────────────────── Help ─────────────────────────

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ───────────────────────── Stack (docker compose) ─────────────────────────

COMPOSE_FILE ?= docker/docker-compose.yml
ENV_FILE ?= .env_files/.env.local.secrets
API_URL ?= http://localhost/api/system/config/auth/

stack-up: ## Boot the compose stack (override with COMPOSE_FILE=... ENV_FILE=...)
	docker compose -f $(COMPOSE_FILE) --env-file=$(ENV_FILE) up -d
	$(MAKE) wait-for-api

stack-down: ## Tear down the compose stack
	docker compose -f $(COMPOSE_FILE) --env-file=$(ENV_FILE) down

stack-logs: ## Tail backend logs
	docker compose -f $(COMPOSE_FILE) --env-file=$(ENV_FILE) logs -f backend

wait-for-api: ## Block until the auth-config endpoint answers
	scripts/ci/wait_for_url.sh $(API_URL) $(COMPOSE_FILE) $(ENV_FILE) backend

# ───────────────────────── E2E (Playwright) ─────────────────────────

e2e: ## Run Playwright E2E against the running stack
	cd frontend && npx playwright test

e2e-headed: ## Run Playwright E2E with a visible browser
	cd frontend && npx playwright test --headed

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
