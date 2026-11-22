# Final (post-optimization) measurement

To conclude and wrap up this optimization iteration, we measured on 2026-11-23 01:07 for the baseline URL (the `http://localhost/entity/organization/100054489?sort=amount_desc&direct_assignments_only=true&start_date=2025-11-01&end_date=2026-10-31`), cold cache, `DEBUG` SQL
logging on and found the following:

| Metric | Baseline | Final (cold) | Delta |
|---|---:|---:|---:|
| HTTP requests | 35 | 7* | −28 (−80%) |
| SQL queries | 531 | 46 | −485 (−91%) |
| Database time | 1.78 s | 0.53 s | −1.25 s (−70%) |
| Wall time (first → last log line) | 1.82 s | 1.47 s | −0.35 s (−19%) |
| Unique query shapes | 35 | 15 | −20 |

\*The saved cold log is missing the authenticated sidebar calls
(`/api/user-data/bookmarks/`, `/api/user-data/folders/`,
`/api/notifications/*`), so 7 undercounts a logged-in visit. A full
logged-in recapture should land near 12 requests and ~55 queries. The query
and time deltas are otherwise representative.

A second, warm load of the same page (cache populated) removes the three
entity aggregates entirely: 3/3 cache lookups hit (`unified` ×2,
`top_org_counterparts`), leaving the list at 62.5 ms (`COUNT(*)`) + 34.2 ms
(page query), so roughly 100–150 ms of DB time for the whole page.

The 1.47 s wall window includes a ~0.6 s client-side gap between
`/api/system/config/auth/` and `/api/system/legal/` (bundle load, not
backend), so DB time is the honest comparison.

## Notes on what changed and why

**Integer feature flags are cached.** The missing `integer` branch and the
blank-row backfill are in (`b57603b`). Flag lookups went from 141 to 27, and
the 27 now fire once at process start instead of on every lookup. Boolean
flags were already cached; this closes the gap that made the `SECURITY_*`
thresholds and `SEARCH_DEBOUNCE_MS` re-query.

**Token authentication is cached.** `CachedTokenAuthentication` resolves the
token once per `sha256(key)` for 60 s (`dad95fa`). The baseline read the
token table 64 times; a cold authenticated burst now costs 1–2 reads and
later requests cost zero. The occasional double read is two concurrent
requests missing an empty cache at the same time (no stampede guard); it is
bounded and disappears on the next request.

**The list payload no longer fans out.** `paginate_decisions` annotates
`has_document_content` with an `EXISTS` instead of joining
`DocumentExtraction`, and prunes columns with `only(...)`. The list query
dropped from 199.3 ms to 43.3 ms and no longer pulls `raw_text` /
`search_vector`. `ai_analyses` is prefetched in one batched query for the 20
rows. Cards load detail lazily (`b34cf7b`, `35d4758`), which removes the 20
detail requests and 5 content requests per visit.

**Entity aggregates are cached.** `source=entity` now caches `date_range` and
`decision_types`, and `organization_top_counterparts_api` is cached with the
organization uid in the key. On the cold load all three miss (as expected);
on the reload all three hit and their 170.7 / 49.2 / 59.8 / 25.1 / 43.1 ms
queries disappear.
