# Organization page performance

The optimization rabbithole started when timeouts were observed when a user tried to visit some organizations, like:

`https://crati.co/entity/organization/6`
for `ΥΠΟΥΡΓΕΙΟ ΕΘΝΙΚΗΣ ΑΜΥΝΑΣ`
or
`https://crati.co/entity/organization/100054489`
for `ΥΠΟΥΡΓΕΙΟ ΠΡΟΣΤΑΣΙΑΣ ΤΟΥ ΠΟΛΙΤΗ`

Running the app with:

```bash
DEBUG=True
DB_LOG_LEVEL=DEBUG
USE_JSON_LOGGING=true
```

shows every query the page runs, in plain SQL. 

It was a mess.

## Baseline

Captured on 2026-11-22 21:34 for `http://localhost/entity/organization/100054489?sort=amount_desc&direct_assignments_only=true&start_date=2025-11-01&end_date=2026-10-31`.

A trimmed excerpt and generated reports live in [`baseline/`](baseline/).

| Metric | Value |
|---|---|
| HTTP requests | 35 |
| SQL queries | 531 |
| Database time | 1.78 s |
| Wall time (first → last log line) | 1.82 s |
| Unique query shapes | 35 |

### Where the time goes

| Queries | DB time | Share | What |
|---:|---:|---:|---|
| 1 | 232.4 ms | 13.1% | `view=date_range` aggregate (min/max/count/sum) |
| 1 | 199.3 ms | 11.2% | `view=decisions` list page (20 rows) |
| 141 | 146.9 ms | 8.3% | repeated `core_feature_flags` lookups |
| 1 | 137.4 ms | 7.7% | `top-counterparts` aggregation |
| 64 | 137.1 ms | 7.7% | repeated token → user lookups |
| 1 | 107.9 ms | 6.1% | paginator `COUNT(*)` over the list join |
| 20 | 98.1 ms | 5.5% | units prefetch, one per decision detail |
| 20 | 73.6 ms | 4.1% | decision detail base query |
| 21 | 70.7 ms | 4.0% | signers prefetch, one per decision detail |
| 1 | 46.4 ms | 2.6% | `view=decision_types` aggregation |

Per-request attribution is in
[`baseline/org_loading.report.txt`](baseline/org_loading.report.txt). It shows
the page data (`date_range`, `decision_types`, `top-counterparts`, list) costing
~858 ms of attributed DB time, then 20 detail requests at ~19 queries each.

## Findings

1. **Integer feature flags are never cached** (141 queries, 27% of all queries).
   `core/management/commands/initialize_feature_flags.py:75-88` persists
   defaults only for `boolean`/`list`/`string`; there is no `integer` branch, so
   `string_value` stays empty. `FeatureFlag.get_value()`
   (`core/models/feature_flags.py:141-157`) then runs `int("")` and returns
   `None`, and `FeatureFlagService.get_value()`
   (`core/services/feature_flag_service.py:628-660`) only caches non-`None` DB
   values. Every lookup re-queries and falls back to the default. Confirmed with
   `manage.py shell`: the four `SECURITY_*` thresholds and `SEARCH_DEBOUNCE_MS`
   all return `None`. Boolean flags are cached, which is why only the integers
   repeat.

2. **The 20-row list triggers an N+1 from the frontend.** After
   `view=decisions` returns 20 rows, the UI requests detail for all 20 and
   content for 5. Each detail runs ~13 queries
   (`api/views/decisions/details.py:32-130`): signers, units, KAEs,
   attachments, relationships, document extraction, AI analyses, one-liners
   (two queries), amount fields, and two counterpart-recovery queries.

3. **The list payload fetches data it does not need.**
   `paginate_decisions` adds `select_related("text_extraction")`
   (`core/services/decision_projections.py:211-213`), so every row pulls
   `raw_text`, `ocr_metadata`, and `search_vector`. The serializer reads exactly
   one thing from it: `bool(raw_text)` (`api/views/search/base.py:224`) to set
   `has_document_content` (`:280`). `raw_text` and `search_vector` are
   TOAST-able, so those columns, not the row count, are the expensive part of
   the list query. The same serializer also calls `decision.ai_analyses.all()`
   per row (`:241-243`), and `paginate_decisions` never prefetches it. The
   existing test calls this out at
   `core/tests/services/test_one_liner_projections.py:142`.

4. **The list join also multiplies rows.** The `is_direct_assignment` join plus
   the amount-field join forces
   `GROUP BY decision.id, organization.uid, acttype.uid, documentextraction.id`,
   and the paginator repeats the join for `COUNT(*)`.

   Column width is not uniform. The 60+ extra `Decision` columns are narrow and
   sit in the row already, so they cost little. The wide, TOAST-able
   `DocumentExtraction` columns are the ones worth removing. Treat column
   pruning as the way to drop those columns, not as a rule that fewer columns is
   always faster.

5. **Entity aggregates run live on every visit.** The unified view only caches
   `source=temporal`; `source=entity` bypasses the cache, so `date_range`
   (232 ms), `decision_types` (46 ms), and `top-counterparts` (137 ms) are
   recomputed each time. `organization_top_counterparts_api` has no cache at
   all.

6. **Every request re-authenticates the same token.** The token is read from
   the database 64 times across 35 requests.

## Implementation plan

Ordered by payoff and risk. Each step ends with a query-count test and a
re-measurement on the baseline URL.

### Step 1: Cache integer feature flags

Add the missing `integer` branch in `initialize_feature_flags.py:75-88`, writing `string_value=str(default)`. The command uses `get_or_create`, so existing rows keep the empty `string_value`. Backfill them in the same command (or a data migration) for the four `SECURITY_*` thresholds and `SEARCH_DEBOUNCE_MS`. 
As a guard, make `FeatureFlagService.get_value()` cache the known-flag default when the DB value is `None`, so a blank row costs one query per TTL, not one per lookup.

Test: an integer flag returns its default, and a second `get_value()` issues zero queries. 
Add a backfill test that starts from a blank `string_value`.

Expected: ~141 queries removed.

### Step 2: Authenticate each token once

`rest_framework.authentication.TokenAuthentication` is first in `DEFAULT_AUTHENTICATION_CLASSES` (`diavgeia_project/settings/rest_framework.py:16-21`), and it queries `Token` on every request. We'll add a subclass in `api/authentication.py` that caches the resolved token with `select_related("user")` under `sha256(token)` with a short TTL (about 60 seconds), and returns the cached `(user, token)` pair. 
Invalidate on logout, token rotation, and password change (`api/views/django_auth.py`, `api/auth_views.py`). A per-request cache is not enough, because the 64 lookups span 35 requests.

We'll keep the TTL short and never log the token. A stale cached user is bounded by the TTL, and `is_active` is checked on the way in.

Test: two authenticated requests hit the token table once; logout forces a re-read.
Expected: ~63 queries removed.

### Step 3: Trim the list payload and the detail fan-out

Replace the `text_extraction` join with an annotation in `paginate_decisions`:

```python
from django.db.models import Exists, OuterRef
from core.models.document_analysis import DocumentExtraction

has_content = DocumentExtraction.objects.filter(
    decision=OuterRef("pk"), extraction_status="COMPLETED"
).exclude(raw_text__isnull=True).exclude(raw_text="")
qs = qs.annotate(has_document_content=Exists(has_content))
```

Drop `"text_extraction"` from `select_related`, and make `serialize_decision_with_content_info` read `decision.has_document_content` when present, falling back to the current check for the detail endpoint.

Prefetch `ai_analyses` for the page in one query, restricted to `COMPLETED` rows with a summary, instead of letting the serializer query per row.

Then prune columns with `.only(...)` covering only what the default serializer reads: 
`id`, 
`ada`, 
`subject`, 
`issue_date_day`, 
`amount`, 
`status`, 
`document_url`, 
`decision_type__uid`, 
`decision_type__label`, 
`organization__uid`, 
`organization__label`, 
plus the `calculated_amount` and
`has_document_content` annotations. 

Keep this behind an argument (`only_fields=...`) so callers that pass a custom `serialize_fn` are unaffected.

For the frontend N+1, load detail when a card expands instead of for all 20 rows. 
If cards do need detail data up front, add a batched `?ids=` mode to the detail endpoint and prefetch units and signers for the whole set, instead of one
request and two prefetches per decision.

Test: `CaptureQueriesContext` (or `django_assert_num_queries`) gives a constant query count for page sizes 1 and 20. 
`has_document_content` matches the old value for completed, empty, and missing extractions. 
One expanded card stays within a fixed query budget.

Expected: the list query loads only the fields the card renders, and the page makes zero detail requests until a card expands.

### Step 4: Cache the entity aggregates

Extend `_should_cache_unified` to allow `source=entity` for `date_range` and `decision_types`, and add `entity_type`, `entity_id`, `direct_assignments_only`,
and the other aggregate inputs to `cache_params`. 
Use a short TTL (5 minutes) so imports show up without invalidation plumbing.

For `top-counterparts`, add `@cached_view` to `organization_top_counterparts_api` with `start_date`, `end_date`, `limit`, `offset`, and `q`. 
The decorator builds its key only from query params (`core/decorators/cache_decorator.py:129-137`), so it must also include the path `organization_uid`; either add a `cache_path_params` option to `cached_view` or put the uid into the key explicitly. 
Without that, one organization's counterparts are served for another.

Test: same org and filters hit the cache; a different org misses; a new decision changes the result after the TTL.
Expected: ~416 ms removed from repeat visits.


## Follow-up (2026-11-25): aggregate projection grain

The four steps above removed query count and warm-path time, but did **not**
fix the first (cold) load of a high-activity organization. A prod profile of
org 6167 (~102k decisions) still showed `view=date_range` at ~13 s on the first
click and ~35 ms on the next (Redis hit).

The root cause was the **aggregate projections** (`date_range`, `decision_types`, `statistics`) **reused the queryset** from `apply_decision_facets`, which **already carries the `calculated_amount`** aggregate annotation. 

Django therefore nested every projection aggregate in a subquery grouped by `decision.id` **and every
amount column**, and `Count("id")` counted amount rows instead of decisions (102,897 reported vs ~80,820 actual). 
See [`../03.aggregation-grain/README.md`](../03.aggregation-grain/README.md) for the full mechanism and audit.

Fixed:

- `apply_decision_facets(..., aggregate_only=True)` keeps the amount annotation out of aggregate projections (`core/services/decision_facets.py`).
- `compute_date_range` now runs `MIN/MAX` only for the bounds (index-only) plus
  a single activity aggregate, and derives the summary totals from the chart.
- `aggregate_decision_types` / `compute_statistics` / the activity chart use
  `Count("id", distinct=True)`.

A caveat that still remains is that while the above mentioned changes remove the fan-out and one of the two cold scans, they cannot remove the remaining **amount-table read**. 
Making the *first* click fast needs a **caching/precompute change** (stale-while-revalidate, entity warmup, covering index, or a denormalized per-decision amount)

## Baseline artifacts

- [`baseline/org_loading.excerpt.log.txt`](baseline/org_loading.excerpt.log.txt)
  holds the trimmed raw log: request lines, slow queries, first config queries.
- [`baseline/org_loading.report.txt`](baseline/org_loading.report.txt)
  holds the grouped queries, slowest queries, and per-request breakdown.