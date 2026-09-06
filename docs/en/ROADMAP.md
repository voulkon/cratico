# Roadmap

Where the project is headed — and where contributions are most welcome right now.

**Contributing to the roadmap itself:** if you'd like to propose a new direction or pick up an item, open a GitHub issue referencing the relevant item (e.g. "Roadmap: <area> — <item>") or comment on an existing one. Completed items get moved to the changelog / lessons-learnt docs (`docs/lessons_learnt/`); this list tracks what's open.

## Areas

- **Testing & quality** — see [CONTRIBUTING.md → Running Tests](../../../CONTRIBUTING.md#running-tests). Every PR runs backend pytest + diff coverage, frontend Jest, and a (currently non-blocking) Playwright E2E auth matrix. Contributions here: more unit coverage, more E2E specs, flipping the E2E job to blocking once stable.
- **Observability** — the stack ships Grafana, Loki, OpenTelemetry collectors (`docker/`, observability compose profiles). Ongoing work: better dashboards, alerting rules, trace coverage of the ingestion pipeline.
- **Ingestion pipeline hardening** — the Diavgeia ingestion/orchestrator flow is the core of the app (background: `docs_deprecated/decision-ingestion-pipeline.md`, `docs/en/ARCHITECTURE.md`). Reliability, retries, and idempotency improvements are high-value.
- **Fresher data (near real-time ingestion)** — today we ingest once after midnight, covering the previous day. Goal: move to hourly ingestion so new decisions appear within the hour instead of the next day. This needs incremental fetching from the Diavgeia API (query by publication timestamp since the last successful run), idempotent re-ingestion of overlapping windows, and coordination with the downstream pipeline (extraction, notifications) so hourly batches stay cheap and don't spam users.
- **Search** — OpenSearch migration with circuit-breaker protections; search-quality improvements and better filtering UX.
- **Sharing & collaboration** — bookmark folders already support sharing and public shareable pages (gather decisions relevant to a story, publish one link). Next steps: richer share views, making notification batches shareable the same way, and broader user-to-user interactions (discussions, tips).
- **Extraction & AI services** — text extraction from PDFs/decision documents, AFM/amount extraction, and AI provider integrations (`backend/gemi/`, `backend/core/ai_services/`). On the AI side, current shipped features: on-demand decision summaries, AI-summarized notification subscriptions with digest-of-summaries, and per-interaction usage/cost tracking — all via user-provided OpenRouter keys. Contributions welcome on: prompt quality (summaries are currently too verbose — we want crisp one-liners), a "SYSTEM" shared-key fallback (mechanism exists, untested), and longer term a user-built processing pipeline (chain steps like "extract between 'Αποφασίζουμε' and signatures" → AI prompt → stored result consumed by the next step).
- **Notifications** — batch notification pipeline (`backend/notifications/`, docs in `docs/notification-batch-impl/`), including AI-summarized subscriptions. Possible extension: making notification batches shareable like bookmark folders.
- **UX & UI** — the interface is functional but has had no dedicated design pass. Contributions welcome on: layout and visual polish (spacing, typography, color consistency), navigation and information architecture, mobile responsiveness, loading/empty/error states, and overall usability of the search & filtering flow. Useful even as small, incremental improvements — no big redesign required.
- **Performance** — query optimization (N+1 fixes), caching strategy (Redis usage: `docs_deprecated/architecture-redis-usage-and-monitoring.md`), DB performance (notes in `notes/db_performance/`).
- **i18n & accessibility** — Greek/English content parity and frontend accessibility passes.
- **Deployment & ops** — Coolify/Caddy production setup, backups (`docs_deprecated/backup_opensearch.md`), and a smoother no-DB dev setup.
