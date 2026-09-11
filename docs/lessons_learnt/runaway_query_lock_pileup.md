# Runaway query → lock pileup (post-import amount verification)

**Status:** diagnosed; fixes proposed (query rewrite primary).
**Occurred:** 2026-09-10 (prod).
**Related:** [non_monetary_value_as_amount.md](non_monetary_value_as_amount.md) (migration 0096),
[db_issues.md](db_issues.md) (DB operational tuning).

---

## TL;DR

A single post-import `SELECT COUNT(*)` ran for **16 hours**. Because it held an
`AccessShareLock` on `core_decisionamountfield`, a pending migration's
`ALTER TABLE` (needing `AccessExclusiveLock`) could not proceed — and Postgres
queues **every later reader behind the pending ALTER**. The result:

- `manage.py shell` queries on that table hung forever (Ctrl+C had no effect).
- The admin page `feedback_pool_view` stopped loading.
- No error, no log line, no interrupt — just a process sleeping in `poll()`.

Nobody "did" anything wrong. An ordinary read arrived while a migration was
waiting for a lock; Postgres's strict FIFO lock queue did the rest.

---

## The chain

```
pid 235034  SELECT COUNT(*) … (post-import amount verification, 2026-09-09)
            └─ holds AccessShareLock on core_decisionamountfield   (16h)
                └─ blocks ▶ pid 375993  ALTER TABLE … ADD COLUMN invalid_amount_*  (migration 0096)
                                └─ blocks ▶ pid 376076  your SELECT WHERE decision_id = 121013
                                └─ blocks ▶ feedback_pool_view  (any admin read of the table)
```

Migrations run in a single transaction, so **all four operations of 0096**
(3 × `AddField` + the partial index `idx_daf_invalid_amounts`) waited together.

Two amplifiers:

- **`backend_xmin` set for 16h** — the long transaction held back `VACUUM`
  cluster-wide (bloat / xid-horizon risk), not just this ALTER.
- **No `statement_timeout`, no `lock_timeout`** — see
  `diavgeia_project/settings/database.py`. Both were deliberately removed
  ("PgBouncer doesn't support it in transaction mode"), so a runaway query has
  no ceiling and a migration queues forever instead of failing fast.

---

## Root cause of the runaway query

`AmountVerificationService.verify_high_value_decisions()`
(`core/services/amount_verification_service.py`) — called by the post-import
task `tasks_post_import.verify_high_value_amounts` for the 2026-09-09 run:

```python
candidates = (
    Decision.objects.annotate(calc_total=amount_sum_excluding_kae())
    .filter(calc_total__gte=self.threshold)
    .exclude(
        text_process_resolutions__process=PROCESS_SLUG,
        text_process_resolutions__winning_run__status=TextProcessStatus.COMPLETED,
    )
    .order_by("-calc_total")
)
...
total_candidates = candidates.count()   # ← the 16h query
...
if limit:
    candidates = candidates[:limit]     # ← limit is applied AFTER the count
```

`candidates.count()` **executes the entire candidate query** — the
`LEFT OUTER JOIN core_decisionamountfield`, the correlated `EXISTS` subqueries
on `core_textprocessresolution`/`core_textprocessrun`, the `GROUP BY
decision.id` and the `HAVING SUM(COALESCE(verified_amount, amount)) >= …` —
wrapped in `SELECT COUNT(*) FROM (…)`. The `limit=500` slice that follows does
not reduce that work at all.

The observed SQL matches the code clause-for-clause (captured from
`pg_stat_activity`), including the `created_at` window from the post-import
scoping (`imported_since` / `imported_until`).

### Contributing plan factors

- **`Decision.created_at` is not indexed.** `Meta.indexes` in
  `core/models/decisions.py` covers `ada`, `status`, `organization`,
  `issue_date`, several composites — but **not `created_at`**, which is what
  the post-import scoping filters on. The range filter is therefore not
  index-backed, so the planner has little option but a broad scan feeding the
  join + aggregate.
- **`verify_amounts_against_grouped` / facet helpers** are fine; the cost is
  the unbounded candidate selection, not the per-decision work.

---

## Diagnosis toolkit (what actually worked)

Everything below is read-only and cheap. Do these *before* killing anything.

1. **Find the stuck work.**
   ```sql
   SELECT pid, state, wait_event_type, wait_event,
          now() - query_start AS age, left(query, 90)
   FROM pg_stat_activity
   WHERE datname = current_database()
   ORDER BY age DESC NULLS LAST;
   ```
   Look for `state='active'` with a large `age` (the culprit) and rows with
   `wait_event_type='Lock'` (the victims).

2. **Get the exact blocking graph.**
   ```sql
   SELECT blocked.pid AS blocked_pid, blocking.pid AS blocking_pid,
          now() - blocked.query_start AS blocked_age,
          blocked.query AS blocked_query, blocking.query AS blocking_query
   FROM pg_stat_activity blocked
   JOIN LATERAL unnest(pg_blocking_pids(blocked.pid)) AS b(pid) ON true
   JOIN pg_stat_activity blocking ON blocking.pid = b.pid
   WHERE cardinality(pg_blocking_pids(blocked.pid)) > 0;
   ```

3. **Full context on the culprit.**
   ```sql
   SELECT pid, backend_start, query_start, state, client_addr,
          application_name, backend_xmin, query
   FROM pg_stat_activity WHERE pid = <pid>;
   ```

4. **Prove it's the DB socket, not the app.** Inside the container:
   ```bash
   docker exec <container> sh -c 'cat /proc/<pid>/wchan; echo; grep -i "^State" /proc/<pid>/status'
   docker exec <container> sh -c 'cat /proc/<pid>/net/tcp'   # find the fd's inode
   ```
   - `wchan = do_poll` + a socket fd to port `1538` (hex 5432) → blocked on
     Postgres.
   - `Sl+` in `ps` (sleeping, threaded, foreground) → I/O wait, not CPU.

5. **Kill only the blocker.**
   ```sql
   SELECT pg_cancel_backend(<pid>);        -- graceful
   SELECT pg_terminate_backend(<pid>);     -- fallback
   ```
   Then let the chain unwind on its own: the ALTER commits, the queued readers
   proceed. Verify 0096 landed:
   ```sql
   SELECT column_name FROM information_schema.columns
   WHERE table_name = 'core_decisionamountfield' AND column_name LIKE 'invalid_amount%';
   ```

---

## Why Ctrl+C did nothing

`psycopg2` (2.9.x) executes queries inside a C extension and **does not poll
Python signals while blocked in libpq**. A `SIGINT` handler cannot run until
the C call returns, so `^C` is printed by the tty but never delivered. The
process looks dead because it *is* waiting on a socket the kernel won't wake
until the server replies.

This also means: **the app can never time out on its own.** Only a server-side
`statement_timeout` (or a client-side socket timeout) can bound it.

---

## Lessons

### 1. Never `.count()` a query you also intend to slice

`qs.count()` pays for the **entire** result. If a `limit` follows, the count is
usually pointless and always wasteful. Prefer:

- drop the count (log "processing up to N"), or
- count a cheap, index-backed projection (`values("decision_id").distinct()`
  via the partial indexes — the pattern already used in the admin views), or
- slice first and count only the page.

### 2. `ADD COLUMN` is instant; the *lock wait* is the danger

`ALTER TABLE … ADD COLUMN <nullable, no default>` takes no rewrite — but it
needs `AccessExclusiveLock`, which any open reader blocks. Because Postgres is
FIFO, a blocked ALTER freezes **all subsequent readers** of that table. Set a
`lock_timeout` for migrations so they fail fast instead of wedging the app.

### 3. An index is about range selectivity, not uniqueness

Common misconception: "this column is unique per row, so an index is pointless."
Wrong — a **B-tree index on a high-cardinality column is exactly what makes a
range predicate fast**, because it is *ordered*: seek to the low bound, walk
forward. Uniqueness only matters for a `UNIQUE` index. A `created_at >= X AND
created_at < Y` filter is the textbook beneficiary.

That said: an index is **secondary** here. The dominant fix is #1 — the
full-set count. Even a perfectly selective index leaves an O(day's rows)
join + aggregate if the count over the whole set is still executed. Fix the
query shape first; add the index as support.

### 4. Bound runaway queries server-side

`settings/database.py` has neither `statement_timeout` nor `lock_timeout`. Under
PgBouncer transaction pooling a session-level `SET` is not reliably preserved;
set them on the **role** or via PgBouncer (`query_wait_timeout`), so a stuck
query cannot live for 16 hours unnoticed.

### 5. Silence is not health

The task logs `Amount verification: N decisions…` only *after* `.count()`
returns — a stuck count emits nothing. Combined with
`CELERY_TASK_EVENT_LOG_LEVEL=WARNING` (per-task lifecycle logs hidden by
default), the incident produced **no log line at all**. Alert on
`pg_stat_activity` age (> 5 min active) rather than waiting for an error.

### 6. `EXPLAIN` needs the lock too

`EXPLAIN` (without `ANALYZE`) does not execute the query, but it still *plans*
it and therefore still takes the same `AccessShareLock`. Behind a pending
`AccessExclusive` it hangs exactly like the original query. Capture the SQL
text from `pg_stat_activity` first; run `EXPLAIN` only after the blocker is
cleared.

---

## Recommended fixes (in priority order)

1. **Rewrite `verify_high_value_decisions()`** (and `correct_high_value_decisions`)
   to stop doing a full-set `.count()`. Slice first, or count via the partial
   indexes. This is the fix that matters.
2. **Add `models.Index(fields=["created_at"])` on `Decision`** (migration) so
   the post-import range filter is index-backed. Cheap, low-risk, verify with
   `EXPLAIN` before/after that the planner actually uses it.
3. **Set `lock_timeout` for migrations** (role-level or `OPTIONS`) so an ALTER
   fails fast instead of queueing every reader behind it.
4. **Alert on long-running queries** (`pg_stat_activity` age) so the next one is
   caught in minutes, not after a working day.
5. **Make migrations visible** — raise `CELERY_TASK_EVENT_LOG_LEVEL`/migration
   logging so a pending migration is not silent.

---

## Reproducing the observation (safe, local)

The failure is a lock-wait, not data corruption, so it can be reproduced on a
scratch DB:

1. Session A: `BEGIN; SELECT count(*) FROM some_big_table;` (leave open).
2. Session B: `ALTER TABLE some_big_table ADD COLUMN x int;` → blocks.
3. Session C: `SELECT * FROM some_big_table LIMIT 1;` → **also blocks**, queued
   behind B's pending lock.

That third session is the whole incident in three lines: an innocent read
waiting behind a pending ALTER, which is waiting behind a long read.
