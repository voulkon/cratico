.PHONY: lint lint-install sample-data reset-db quality quality-report quality-check quality-ai quality-css quality-ai-report quality-css-report

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
