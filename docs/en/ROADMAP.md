# Roadmap

Where the project is headed — and where contributions are most welcome right now.

**Contributing to the roadmap itself:** if you'd like to propose a new direction or pick up an item, open a GitHub issue referencing the relevant item (e.g. "Roadmap: <area> — <item>") or comment on an existing one. Completed items get moved to the changelog / lessons-learnt docs (`docs/lessons_learnt/`); this list tracks what's open.

## Areas

- **Testing & quality** — see [CONTRIBUTING.md → Running Tests](../../../CONTRIBUTING.md#running-tests). Every PR runs backend pytest + diff coverage, frontend Jest, and a (currently non-blocking) Playwright E2E auth matrix. Contributions here: more unit coverage, more E2E specs, flipping the E2E job to blocking once stable.
- **Observability** — the stack ships Grafana, Loki, OpenTelemetry collectors (`docker/`, observability compose profiles). Ongoing work: better dashboards, alerting rules, trace coverage of the ingestion pipeline.
- **Ingestion pipeline hardening** — the Diavgeia ingestion/orchestrator flow is the core of the app (background: `docs_deprecated/decision-ingestion-pipeline.md`, `docs/en/ARCHITECTURE.md`). Reliability, retries, and idempotency improvements are high-value.
- **Search** — OpenSearch migration with circuit-breaker protections; search-quality improvements and better filtering UX.
- **Extraction & AI services** — text extraction from PDFs/decision documents, AFM/amount extraction, and AI provider integrations (`backend/gemi/`, `backend/core/ai_services/` — see its README for planned providers).
- **Notifications** — batch notification pipeline (`backend/notifications/`, docs in `docs/notification-batch-impl/`).
- **Performance** — query optimization (N+1 fixes), caching strategy (Redis usage: `docs_deprecated/architecture-redis-usage-and-monitoring.md`), DB performance (notes in `notes/db_performance/`).
- **i18n & accessibility** — Greek/English content parity and frontend accessibility passes.
- **Deployment & ops** — Coolify/Caddy production setup, backups (`docs_deprecated/backup_opensearch.md`), and a smoother no-DB dev setup.
