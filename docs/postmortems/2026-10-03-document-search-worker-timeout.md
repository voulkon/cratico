# Postmortem: gunicorn WORKER TIMEOUT on document search — silent worker occupation

**Severity:** availability — one request can occupy a sync gunicorn worker for up to `--timeout 300`, i.e. 50 % of HTTP capacity with `--workers 2`.
**Component:** `backend/core/services/search_service.py` (`_search_documents_postgresql`), its callers, and gunicorn/nginx timeout alignment.

---

## 1. What happened

Home-page search typed `ACME`; first queries were fast, then the UI hung
indefinitely. Backend did not crash and logged no exception. One gunicorn
worker sat on a single request for the full `--timeout 300`, was declared
`WORKER TIMEOUT`, then `SIGKILL`ed ~1 s later (gunicorn's own SIGABRT→SIGKILL
escalation — "Perhaps out of memory?" is appended to *any* SIGKILL and is not
a diagnosis). Master respawned a worker; in-flight requests on the killed
worker died silently. nginx `proxy_read_timeout 300s` fires at the same
instant → clients see 504/dropped connection, never an error page. The
triggering request logged **zero** lines because it never returned.

## 2. Root cause chain (every link verified)

1. **Unsanitized tsquery input** — `_build_prefix_search_query` lowercases each
   word and appends `:*`, passing it as a *raw* tsquery. Input containing
   tsquery metacharacters (`:` `&` `|` `!` quotes — trivially produced by a
   typo like Shift+; instead of L while typing uppercase, e.g. `DE:`) raises
   `syntax error in tsquery` in Postgres. Observed in DB log: `δε::*`.
2. **Broad `except Exception` routes errors into the ILIKE fallback** — in
   `_search_documents_postgresql` the FTS try/except swallows *everything*
   (syntax errors included) and falls back to
   `qs.filter(raw_text__icontains=query)`.
3. **The ILIKE fallback is an unbounded sequential scan** — `raw_text` is a
   plain `TextField`, no trigram index (migration `0007a` only creates the
   pg_trgm *extension*). Table on the affected environment: **1.4 M rows /
   17 GB**. A `count(*)` with `ILIKE '%QZXW%'` did not finish in 60 s and was
   manually aborted.
4. **The min-length guard protects entity search only** — a 1–2 char query
   produces no Greek FTS lexemes (stemmer drops them), so FTS matches nothing
   → ILIKE fallback. Document search has no such guard (see §4).
5. **No `statement_timeout` anywhere** (pgbouncer transaction mode prevents
   connection startup options) → runaway SQL has no ceiling.
6. **`vector_results.count()` re-executes the entire FTS scan** — the hit path
   is nearly as bad at this volume (see §3, second pattern).
7. **Architecture amplifies it** — 2 sync workers + 300 s timeout: one stuck
   request = 50 % capacity for 5 min; the request that never returns is the
   one that never logs (the defect named in the issue).

## 3. Historical evidence (proves this predates today by a month)

`api_endpointaccesslog` (forensic logging) — **all** top-slow requests are
`/api/search/documents/`, all returned 200, 400–1470 s:

| Query | Latency | Path |
|---|---|---|
| `ΑΠΟΦΑΣΗ`, `ΥΠΟΥΡΓΕΙΟ`, `ΔΗΜΟΣ`, `ΔΗΜ` | 600–1050 s | FTS prefix **hit**, then `vector_results.count()` re-runs the full FTS over the match set |
| `ΑΔΨΝΙ` (gibberish) | 509 s | FTS miss → ILIKE scans until `limit` matches, then `.count()` scans to the end |
| `Α`, `Δ`, `Μ`, `O` | 400–1470 s | 1-char → no FTS lexemes → ILIKE fallback |

Severity inversion worth stating: the modal trigger is not the rare
metacharacter typo — it is **any single common Greek letter**, i.e. the first
keystroke of essentially every Greek search. The ILIKE fallback's runtime is
also data-dependent in the worst way: it is fast iff the pattern happens to
match ≥ `limit` rows early; gibberish (`QZXW`) forces a full 17 GB scan.

## 4. The two controls that exist — and their gaps

Both memories were correct; both controls leak.

### 4a. Min-query-length control — exists in three layers, none covers document search

| Layer | Location | Threshold | Covers document search? |
|---|---|---|---|
| Backend constant | `SearchService.MIN_FTS_QUERY_LENGTH = 3` + `_is_query_too_short_for_fts` | 3 | **No** — applied only in the 6 entity `_search_*` methods, never in `_search_documents_postgresql` |
| Backend entity endpoint | `get_entities_fast` (`MIN_ENTITY_QUERY_LENGTH`) | ~3 | n/a (entity-only endpoint — this is why `entities-fast/?q=DE:` in the incident log never hit the bug) |
| Frontend | `streamSearch` in `frontend/src/api/searchApi.js` (`MIN_QUERY_LENGTH = 3`) | 3 | **Nominally yes, but it's client-side** — and `searchDocuments`, `searchCategories` (`documents > 0`), `getSearchSuggestions` (threshold 2) have **no** guard |

So: home-page typing *does* skip <3-char searches via `streamSearch` — which is
why you remember the control — but `/api/search/documents/?q=Δ` is wide open
to direct calls, other frontend paths, and any length-≥3 query that FTS-misses
or syntax-errors.

### 4b. "Disable document search" control — exists only as an emergent double-off

There is **no dedicated flag**. Document search is disabled only when *both*
`INDEX_THE_OPENSEARCH` **and** `INDEX_THE_POSTGRES` are off — and even then
`search_documents` returns the empty stub **without any per-query length
check** (empty early-return precedes everything). In the incident environment
OpenSearch was disabled and `INDEX_THE_POSTGRES` on → every document query
took the PostgreSQL path. What does not exist:

- a flag that disables document search *independently* of indexing flags
  (i.e. "entities only" as a first-class, admin-toggleable posture);
- a flag gating the ILIKE fallback specifically;
- any server-side ceiling (timeout) that would make the above survivable.

### 4c. The crime, stated plainly

> Reverting to unindexed `raw_text ILIKE '%...%'` when FTS conditions are met
> is a crime. The fallback path exists (`try/except → except → ILIKE`) and is
> reached silently — by syntax errors swallowed by a bare `except Exception`,
> by FTS misses, and by sub-threshold queries — with no flag, no timeout, no
> log line naming the query, and no index. A degraded-tier decision must be
> explicit, logged, bounded, and off by default.

## 5. Fix plan (ordered; 1–4 are the bug, 5–8 make it survivable/diagnosable)

1. **Remove the ILIKE fallback** from `_search_documents_postgresql` (return
   empty + `source: "none"`), or gate it behind a new flag
   `DOCUMENT_SEARCH_ILIKE_FALLBACK` defaulting to **off** until a pg_trgm GIN
   index on `raw_text` exists. Flag belongs in `KNOWN_FLAGS`, category `search`.
2. **Sanitize tsquery input** in `_build_prefix_search_query`: strip/neutralize
   tsquery operators (`: & | ! ' ( )` etc.) per word before appending `:*`;
   a word that sanitizes to empty is dropped. Fixes both the 500s (entity
   path) and the silent route into the fallback (document path).
3. **Apply the min-length guard to document search server-side** — in
   `search_documents` (not only the view): `max(len(w)) < MIN_FTS_QUERY_LENGTH`
   → return empty immediately. Mirrors the entity guard; removes the
   1–2-letter trigger class regardless of which endpoint/flag path is taken.
4. **Stop double-executing FTS**: remove `vector_results.count()` (and the
   `fallback_results.count()` counterpart) from `_search_documents_postgresql`
   — same fix previously applied to all 6 entity `_search_*_fts` methods. If a
   total count is needed, cap it (e.g. count over a sliced subquery) or report
   `count = len(results)` + a "has more" signal.
5. **Server-side statement ceiling**: `ALTER ROLE <app_role> SET
   statement_timeout = '30s'` (works with pgbouncer transaction mode, unlike
   connection startup options). This is the generic backstop for *any* future
   runaway query, not just search.
6. **Right-size the gunicorn posture**: `--timeout 300 --workers 2` sync is a
   single-request-DoS amplifier. Lower timeout (30–60 s), add workers/threads
   (or `gthread`), and align nginx `proxy_read_timeout`. Separate decision
   from the code fix but same blast-radius budget.
7. **Close the observability hole** (the core defect named in the issue): the
   "falling back to PostgreSQL search" start log does not include the query
   (the completion line does — which is exactly why hung requests are
   anonymous). Log `query=` + `search_id` at start, or log request entry in
   the callers before invoking `search_documents`.
8. **First-class "entities only" flag**: add e.g. `DOCUMENT_SEARCH_ENABLED`
   (default true; document search returns the empty stub when false),
   delivered to the frontend like other config so the UI can hide the
   documents category instead of letting it spin. Distinct from
   `INDEX_THE_POSTGRES` (indexing ≠ serving).

   This flag is deliberately **separate** from the ILIKE-fallback gate in
   item 1: #8 is a product posture ("do we serve document content search at
   all"), #1 is a safety invariant ("if we serve it, it may never degrade to
   an unindexed scan"). #1 must hold even when document search is enabled;
   #8 is the escape hatch while the ecosystem (OpenSearch, trigram index)
   is unhealthy.

   Before flipping it off permanently, measure actual utility — see §6a.
   Note the suspicion "it has never returned anything" is already
   contradicted once: the incident-day logs contain "PostgreSQL fallback
   returned 5 results for query: <name>" (a real Latin-name query with an
   FTS hit). The open question is not whether it *can* return results but
   whether users *click* them.

## 6. Tests & verification

**pytest (data-volume independent — the real regression harness):**

- `_search_documents_postgresql("QZXW:")` (metachar), `("QZXW")` (miss),
  `("Q")` (short): assert **no** query containing `raw_text ... ILIKE` is
  issued (via `CaptureQueriesContext` / `assertNumQueries`-style capture) and
  the result returns immediately with `count == 0`.
- FTS-hit path: assert the executed query count does not include a second
  scan (the `.count()` regression) — query-count assertion, not timing.
- Sanitizer unit tests: `DE:` → no exception; metachar-only words dropped.

**Playwright e2e (contract only):** type `QZXW:` into super-search, assert 200
within a few seconds. On the CI corpus this passes pre- and post-fix — it
cannot prove the hang (CI volume is tiny) — it locks "metacharacter queries
never error and return fast". Extraction fixture exists in the `search.py`
registry entry.

### 6a. Measuring whether document search earns its keep (input to fix #8)

- **Volume + cost** (durable, available now): `api_endpointaccesslog` gives
  request counts and latencies for `/api/search/documents/` — the September
  data shows it is both used and catastrophically slow.
- **Value (clicks)** — measurement gap, recorded as a finding: search
  *selection* tracking (`track_search_selection_api`, `result_type:
  'document'`) persists to **Redis sorted sets** (`search_history:user:<id>`
  / `search_history:ip:<ip>`) — volatile, not an audit source. The durable
  `SearchAnalytics` table (`clicked_result_type`, `results_count`) is only
  written by views that call `SearchAnalyticsService.log_search_start`
  (`decisions_unified`, `entity_analytics`, `temporal_exploration`) —
  **document search endpoints never log there**, so "did anyone ever click a
  document result" is currently unanswerable from durable storage. If the
  #8 decision should be evidence-based, first add
  `log_search_start`/`log_search_complete` + click recording to
  `document_search_api` (and/or `super_search_api`), let it run, then decide.

**Manual live repro (preview env, one bounded run; each run costs one worker
≤300 s):** control query = a real organization name (FTS hit, <1 s, completion
line present); trigger = `QZXW:` (unique token). Expect: fallback start line
with **no** completion line; `pg_stat_activity` shows the `raw_text ILIKE`
query aging (`SELECT pid, now()-query_start AS age, left(query,140) FROM
pg_stat_activity WHERE state='active' AND query ILIKE '%raw_text%';`); at
+300 s `WORKER TIMEOUT` → SIGKILL. Clean up the orphaned SQL afterwards with
`SELECT pg_cancel_backend(<pid>);` — the query survives SIGKILL until Postgres
tries to write results.

## 7. Open items / things to verify on the incident environment

- Whether a **second** `WORKER TIMEOUT` followed ~24 s after the first — the
  logs show two unmatched fallback-start lines (`Δ` at 10:27:33.649 local and
  `D` at 10:27:57.598 local), implying both sync workers were occupied, which
  would explain why even trivial shell calls (`suggestions`,
  `recently-visited`) returned 499 during the window.
- Which endpoint carried the hung request (`stream/` vs `super/` vs
  `documents/`) — visible as a 499 in the nginx access log ~10 s after the
  fallback-start line (axios timeout).
- Note: two timestamp conventions coexist in the logs — gunicorn/nginx/DB in
  UTC, app JSON logs in local time (UTC+3). Align before computing windows.
  (Fix: render TZ in the loguru formatters.)

## 8. Key file references

- `backend/core/services/search_service.py` — `_build_prefix_search_query`
  (sanitization gap), `_is_query_too_short_for_fts` (entity-only guard),
  `_search_documents_postgresql` (fallback + `count()`), `search_documents`
  (missing guard, start-log without query).
- `backend/api/views/search/document_search.py` — `/api/search/documents/`
  view: no length validation before calling `search_documents`.
- `backend/api/views/search/entity_search_utils.py` — `get_entities_fast`
  (`MIN_ENTITY_QUERY_LENGTH` — the guard that works).
- `frontend/src/api/searchApi.js` — `streamSearch` (`MIN_QUERY_LENGTH = 3`),
  unguarded `searchDocuments` / `searchCategories` / `getSearchSuggestions`.
- `frontend/src/components/SuperSearch.js` — `includeDocuments: showFullResults`.
- `backend/core/services/feature_flag_service.py` — `KNOWN_FLAGS` (add
  `DOCUMENT_SEARCH_ENABLED` / `DOCUMENT_SEARCH_ILIKE_FALLBACK` here).
- `backend/core/migrations/0007a_add_pg_trgm_extension.py` — extension only,
  no index.
- `backend/entrypoint.sh` — gunicorn `--timeout 300 --workers 2`.
- `nginx/` config — `proxy_read_timeout 300s`.
