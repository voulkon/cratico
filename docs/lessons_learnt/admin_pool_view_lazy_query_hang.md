# Admin pool page hangs (499/524): a lazy post-view query with a 148M-cost scan

**Status:** root-caused and fixed — **plan verified** (see “Measured before/after”).
**Occurred:** 2026-09-10 (prod).
**Related:** [runaway_query_lock_pileup.md](runaway_query_lock_pileup.md) — same class
of bug (an unbounded query on the request path), different mechanism.

> **Correction:** an earlier draft of this file blamed **Redis** (socket timeouts).
> That was disproven: `redis-cli --latency` was flat (p99 3 ms), `INFO` showed 26 MB
> used, 0 evictions, 0 blocked clients, no BGSAVE — and the `py-spy` stack (below)
> showed the worker waiting on **Postgres**, not Redis. The Redis socket timeouts
> added in `settings/cache.py` are kept as **defensive hardening only**; they are not
> the fix for this incident.

---

## Symptom

`/api/admin/core/decision/feedback-pool/` spun for ~100 s, then the proxy returned
**524** (Cloudflare) and nginx logged:

```
"GET /api/admin/core/decision/feedback-pool/ HTTP/1.1" 499 0
```

`499` = nginx saw the client disconnect before it could respond; `0` = **zero
response bytes**. Meanwhile the Django view logged success:

```
feedback_pool_view timing: stats=0.056s count=0.000s page=0.000s
```

## Why the view's timing log was worthless

`Paginator.page()` only **slices** the queryset — it does **not** execute it. The
SQL runs later, lazily, when the view iterates `page_obj.object_list`:

```python
for d in page_obj.object_list:      # ← the query actually executes HERE
```

The `timing` log is emitted **before** that loop. So it measured the stats and the
slicing — never the query. The view reported "0.000s page" and then blocked for
minutes. A lazy QuerySet evaluated outside the instrumented region is invisible.

## Root cause

```python
qs = (
    Decision.objects
    .filter(id__in=corrected_ids)          # EXISTS over the amount-field table
    ...
    .order_by("-issue_date")               # ORDER BY
)[:25]                                     # LIMIT
```

`EXPLAIN` (prod):

```
Limit  (cost=1.00..4935.23 rows=25)
  ->  Nested Loop Semi Join  (cost=1.00..148384082.95 rows=751809)
        ->  Index Scan Backward using core_decisi_issue_d_3d1e92_idx on core_decision
              (cost=0.56..121096929.49 rows=32332802)
        ->  Index Scan using core_decisionamountfield_decision_id_bcd23c82
              Filter: ((verified_amount IS NOT NULL) OR (invalid_amount_reason IS NOT NULL))
```

To satisfy `ORDER BY issue_date DESC LIMIT 25`, PostgreSQL walked `core_decision`
**backwards by `issue_date`** (32 M rows) and probed the amount-field table for
each row. **Recent decisions mostly do not have an amount issue**, so it had to
walk an enormous number of rows before accumulating 25 matches. Total plan cost:
**~148,000,000**. The `OR` filter also defeats the two partial indexes on the
semi-join side, so it fell back to the plain `decision_id` index plus a filter.

It was not *hung* — it was grinding, with no output, for minutes.

## Fix

Drive paging from the **selective side** (the amount-field table) instead of
ordering the huge `Decision` table:

1. materialise the bounded set of decision ids that have an amount issue, straight
   from the partial indexes (`~3.9k` rows, index-only);
2. apply the filters to that small set;
3. **sort it in Python** (never touches `core_decision` broadly);
4. fetch only the 25 rows for the requested page by PK.

```python
corrected_ids = list(
    DecisionAmountField.objects.filter(_has_amount_issue_q())
    .values_list("decision_id", flat=True).distinct()
)
qs = Decision.objects.filter(id__in=corrected_ids)
# ... apply filters ...
ordered_ids = [
    row[0] for row in sorted(
        qs.values_list("id", "issue_date"),
        key=lambda r: (r[1] is None, r[1]), reverse=True,
    )
]
page_ids = ordered_ids[(page_number - 1) * per_page : page_number * per_page]
```

A small `_SimplePage` object replaces `Paginator` for this view so the count is
**not** recomputed (the view already knows it).

Verify the new plan is bounded (should be an index/bitmap scan over the `IN` list,
**no** backward `issue_date` scan over millions of rows):

```python
Decision.objects.filter(id__in=corrected_ids).values_list("id", "issue_date").explain()
```

### Measured before/after (prod)

Confirmed on the production database — same data, same view, before vs after the
rewrite. Numbers are PostgreSQL plan costs.

| | Plan | Cost | Shape |
|---|---|---|---|
| **Before** | `Limit → Nested Loop Semi Join` | **148,384,082** | Backward `Index Scan core_decisi_issue_d_3d1e92_idx` over `core_decision`, probing amount fields per row |
| **After** | `Index Scan core_decision_pkey` | **33,373** | `Index Cond: (id = ANY (…))` over **3,912** ids |

Before:

```
Limit  (cost=1.00..4935.23 rows=25 width=1537)
  ->  Nested Loop Semi Join  (cost=1.00..148384082.95 rows=751809 width=1537)
        ->  Index Scan Backward using core_decisi_issue_d_3d1e92_idx on core_decision
              (cost=0.56..121096929.49 rows=32332802 width=1537)
        ->  Index Scan using core_decisionamountfield_decision_id_bcd23c82 on core_decisionamountfield u0
              (cost=0.44..13.54 rows=33 width=8)
              Filter: ((verified_amount IS NOT NULL) OR (invalid_amount_reason IS NOT NULL))
```

After:

```
Index Scan using core_decision_pkey on core_decision  (cost=0.56..33373.24 rows=3912 width=16)
  Index Cond: (id = ANY ('{77923,87261,90721,…}'::bigint[]))
```

The plan cost dropped ~4,400× and the 32M-row backward scan is gone entirely.
The query is now bounded by the number of decisions with an amount issue
(**3,912**), not by the size of `core_decision`.

### Proven vs not proven

- **Proven (plan):** the old query shape forced a backward index scan over
  `core_decision` to satisfy `ORDER BY issue_date DESC LIMIT 25`; the new shape
  does a PK lookup over a bounded id set.
- **Proven (runtime):** the worker was blocked in `cursor.execute` inside
  `feedback_pool_view`'s iteration (`py-spy` stack), on Postgres, not Redis.
- **Not yet proven:** wall-clock improvement on prod (pending deploy/observation).
  The plan change makes the old 148M shape unreachable, so a regression would
  require a further code change.

---

## Lessons

### 1. `Paginator.page()` does not run the query — and a lazy query evaluated after your timing block is invisible

Instrument around **evaluation**, not around slicing. If a view logs a fast
"page" step but hangs, the query is almost certainly executing in the iteration
that follows. Force evaluation inside the timed region (`list(qs)`), or log after
the loop.

### 2. `ORDER BY … LIMIT n` over a low-selectivity correlated filter can scan the whole table

`LIMIT` only helps if the driving scan finds `n` matches quickly. When the filter
is a correlated `EXISTS`/`IN` against another table and the *sort key* is
anti-correlated with the filter (here: newest decisions rarely have the issue),
the planner walks the sort index until it accumulates `n` hits — potentially
millions of rows. Drive the query from the **selective** side and sort the small
result.

### 3. `EXPLAIN` before trusting a "slow page"

A single `EXPLAIN` (which only *plans*, and is safe to run) would have shown the
148M cost immediately. Do it before theorising about the stack.

### 4. `py-spy` gives the actual answer — but needs ptrace

`py-spy` **inside** the container fails (`Failed to copy Py_Version symbol …
Permission denied`) because the container lacks `CAP_SYS_PTRACE`. Join its PID
namespace from a throwaway container instead:

```bash
docker run --rm --pid=container:<backend> --cap-add SYS_PTRACE \
  --security-opt seccomp=unconfined \
  python:3.12-slim sh -c 'pip install -q py-spy && py-spy dump --pid <worker_pid>'
```

The dumped stack named the exact line (`feedback_pool_view`, the `for` loop) and
settled the question in one shot.

### 5. "View logged success" ≠ "the response was sent", and ≠ "the work is done"

Both can be true at once: the log fires, then a lazy query blocks. When a proxy
reports a timeout but the app logs a fast completion, look at (a) work **after**
the log, and (b) work **after** the view (response middleware).

---

## Defensive change kept from the disproven theory

`diavgeia_project/settings/cache.py` now sets `SOCKET_TIMEOUT` /
`SOCKET_CONNECT_TIMEOUT` (env `REDIS_SOCKET_TIMEOUT` /
`REDIS_SOCKET_CONNECT_TIMEOUT`, default 5 s) on both Redis connections. Redis was
healthy in this incident, but an unbounded socket is still a hang waiting to
happen, so the bound stays.

## Detection toolkit

```sql
-- 1. Who is blocked, and on what?
SELECT pid, state, wait_event_type, wait_event, now()-query_start AS age,
       left(query, 100)
FROM pg_stat_activity WHERE state <> 'idle' ORDER BY age DESC NULLS LAST;
```

```bash
# 2. The actual Python stack (needs SYS_PTRACE — see lesson 4)
docker run --rm --pid=container:<backend> --cap-add SYS_PTRACE \
  --security-opt seccomp=unconfined python:3.12-slim \
  sh -c 'pip install -q py-spy && py-spy dump --pid <pid>'

# 3. The plan (safe — does not execute)
#    from manage.py shell: qs.explain()
```
