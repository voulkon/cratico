# Auto Import Flags: Behaviour and Interactions

This page describes how the three auto-import feature flags change what the
system does after an import. It covers the flag interactions, the post-import
pipeline, and the notification behaviour that depends on them.

## 1. The flags

Three flags decide what happens after each import:

| Flag | Default | What it controls |
| --- | --- | --- |
| `AUTO_DAILY_IMPORT_ENABLED` | off | Enqueues a DAILY job for yesterday at `AUTO_DAILY_IMPORT_TIME` (default 00:30). |
| `AUTO_HOURLY_IMPORT_ENABLED` | off | Enqueues an HOURLY job for the current submission-timestamp window at `AUTO_HOURLY_IMPORT_MINUTE` (default :10). |
| `POST_IMPORT_ORCHESTRATOR_ENABLED` | off | Runs the post-import pipeline: amount verification, cache warming, rankings, and notifications. |

Sub-flags that only matter when the orchestrator is on:

| Flag | Default | Effect |
| --- | --- | --- |
| `POST_IMPORT_AMOUNT_VERIFICATION_ENABLED` | on | Runs amount verification. When off, the post-verification tail runs immediately. |
| `POST_IMPORT_NOTIFICATIONS_ENABLED` | off | Runs the subscription check, the only path that creates notification batches and emails. |
| `POST_IMPORT_AMOUNT_ANOMALY_TREATMENT_ENABLED` | off | Applies anomaly treatment inside verification. |
| `ANALYTICS_PRECALC_ENABLED` | off | Computes entity rankings in the daily tail. |
| `ANALYTICS_WARMUP_ENABLED` | off | Warms analytics caches in the tail. |

Flag values are resolved from the database (cached for 300 seconds), then the
environment, then the default. A change can take up to five minutes to reach a
running worker.

## 2. What happens after an import

```
beat 00:30   auto_daily_import_task    (gate: AUTO_DAILY)  → DAILY job (yesterday)
beat :10     auto_hourly_import_task   (gate: AUTO_HOURLY) → HOURLY job (rolling window)

ImportJobQueue (one job at a time)
        │
        └─ job completes → _trigger_post_import_if_global   (no flag check)
                │
                ├─ DAILY  → post_daily_import_orchestrator   (60 s delay)
                └─ HOURLY → post_hourly_import_orchestrator  (300 s delay)
                        │
                        └─ gate: POST_IMPORT_ORCHESTRATOR_ENABLED
                                │
                                └─ verify_high_value_amounts
                                        ├─ verification children (flag: AMOUNT_VERIFICATION)
                                        └─ finalize → post-verification tail, dispatched once
                                                ├─ daily:  rankings → browse invalidate
                                                │          → warm all windows → notifications
                                                └─ hourly: warm today → notifications
                                                        (gate: NOTIFICATIONS)
                                                        └─ check_all_active_subscriptions
```

Several consequences are easy to miss:

- The AUTO flags only decide whether a job is enqueued.
- The completion hook has no flag check. A completed global job always queues an
  orchestrator; the orchestrator itself is the single gate for the pipeline.
  With the orchestrator off it returns `skipped` and logs a warning.
- Email needs an auto import, the orchestrator, the notifications flag, and the
  user's own email preference. Any one of them being off stops the email.
- The post-verification tail is queued exactly once, from verification. The
  orchestrator must not queue it again; doing so caused duplicate notification
  batches on 2026-09-15.

## 3. Flag combinations

`D` = `AUTO_DAILY_IMPORT_ENABLED`, `H` = `AUTO_HOURLY_IMPORT_ENABLED`,
`O` = `POST_IMPORT_ORCHESTRATOR_ENABLED`.

Assume `POST_IMPORT_NOTIFICATIONS_ENABLED` is on unless stated otherwise.

| D | H | O | Imports | Pipeline | Emails | Meaning |
| --- | --- | --- | --- | --- | --- | --- |
| off | off | off | none | none | none | Idle. Beat ticks, every task self-skips. |
| off | off | on | none | none | none | Safe idle state. |
| off | on | off | hourly | none | none | **Silent failure:** data arrives but is never verified, warmed, or notified. Logs a warning. |
| off | on | on | hourly | verify, warm today, notifications | per run, subject to user preference | Works, but no job runs the full daily tail. |
| on | off | off | daily | none | none | **Silent failure**, same as the hourly case. |
| on | off | on | daily | full daily tail | once per run, subject to user preference | Typical state before hourly is enabled. |
| on | on | off | daily + hourly | none | none | **Silent failure** for both jobs. |
| on | on | on | daily + hourly, serialized | one daily tail + light hourly tails | subject to user preference | Target state: the daily job supplies the full tail the hourly jobs do not run. |

Rows with an import on and the orchestrator off are the risky states: imports
succeed, so nothing looks broken, but no verification, warming, or notification
happens. The orchestrator logs a WARNING when it skips for this reason.

## 4. Post-import behaviour

### 4.1 Verification window

Verification selects decisions by **import time** (`Decision.created_at`), not
by issue date. Each job verifies the decisions it just inserted:

- HOURLY uses `fetch_started_at` → completion.
- DAILY uses the job's `created_at` → completion. The daily fetch does not write
  `fetch_started_at`, so `created_at` (the enqueue time) is the fallback. It is
  earlier than or equal to the real start, which can only widen the window.
  Decisions inserted by an earlier hourly job keep their old `created_at` and
  are not verified twice.

This was fixed after the previous daily behaviour verified `[yesterday 00:00,
today 00:00)`, which did not include the rows the run itself inserted after
midnight. In practice every decision used to be verified about 24 hours late.

### 4.2 Hourly catch-up

The hourly window is recomputed from the watermark at execution time:
`watermark − 10 min → now`. A single job is capped at
`HOURLY_IMPORT_MAX_WINDOW_HOURS = 24`. When the cap applies, the window ends at
start + 24 hours and the watermark advances to that end, so a long outage is
caught up by several bounded jobs instead of one job that blocks the queue.

The watermark advances only after the fetched decisions are durable in Redis and
their storage tasks have been dispatched. A failed fetch never advances it.

### 4.3 Repeated fetches

The daily run re-fetches and re-upserts up to a full day, and hourly runs
overlap by ten minutes. That does not mean the heavy pipeline runs again:

- Fetch and upsert are cheap. `created_at` and `id` are excluded from updates.
- A decision with a HEALTHY health check skips the pipeline on re-fetch.
- WARNING and ERROR decisions are re-processed on every re-fetch. This is the
  main source of repeated work, though the observed rate is small enough that
  the cost is usually negligible.
- Duplicate discovery tags are ignored.

Nothing is re-sent to users: deduplication happens before a batch is created,
backed by `unique_subscription_decision`. An all-duplicates run returns the
existing batch with `decisions_added=0` and is excluded from summary and email.

### 4.4 Cache windows

Analytics windows are filtered by issue date. The daily tail warms four nested
windows anchored on the reference date (yesterday): daily, weekly, monthly, and
yearly. The hourly tail warms only today.

An hourly import can bring a decision whose issue date is older. That decision
belongs to the larger windows, which are not re-warmed until the next daily
tail. Selective re-warming on the hourly tail was considered and deliberately
deferred; the staleness lasts at most until the nightly daily run.

### 4.5 Amount correction

Amount correction runs right after each import, as part of verification. The
old `amount_correction.daily` beat entry was removed because it corrected the
same decisions twice and re-downloaded their documents.

`daily_amount_correction` and `run_amount_correction_job` remain available for
manual and admin use. A beat sweeper (`amount_correction.sweep_jobs`, every ten
minutes) finalises admin-launched jobs once all per-decision results are
settled, and invalidates amount-dependent caches when anything was corrected or
flagged.

## 5. Notifications

### 5.1 Subscription cadence

`check_all_active_subscriptions` still decides which subscriptions are due:
`daily` subscriptions are checked on every run, `weekly` ones after seven days,
and `manual` ones never automatically. Under hourly imports, a `daily`
subscription is therefore checked up to 24 times a day. Deduplication means that
only runs with new decisions create a batch or send an email.

Matching uses `publish_timestamp >= now − 24h`. A decision imported late with an
older publish time is not matched by later runs, and the daily sweep uses the same
matcher.

### 5.2 User preference

Email cadence is controlled by `NotificationPreference`, one row per user:

| Field | Default | Meaning |
| --- | --- | --- |
| `email_enabled` | on | Turning it off stops email; in-app notifications continue. |
| `email_mode` | `daily_digest` | `every_run`, `daily_digest`, or `weekly_digest`. |
| `digest_hour_local` | 8 | Local hour for the digest. Weekly digests send on Monday. |
| `ai_summary_enabled` | off | User-level AI toggle; off skips batch summaries even if a subscription has them on. |

- `every_run` preserves the previous per-run email behaviour.
- `daily_digest` and `weekly_digest` leave batches un-emailed and send one email
  from the hourly digest task (`notification-digests`, minute :05).
- Existing users were migrated to `daily_digest`; a user can switch back to
  `every_run` in the API. New users get the defaults above.
- A user-level AI toggle on with no pipeline falls back to the default summary
  pipeline.

The preference is available at `/api/notifications/preferences/`.

If two senders pick up the same un-emailed batch at the same time, a duplicate
send is theoretically possible: there is no row lock between the send and the
`email_sent` update.

### 5.3 AI summary ceiling

At most `NOTIFICATION_AI_SUMMARIES_PER_SUBSCRIPTION_PER_DAY` (default 2)
batches per subscription per Athens calendar day are summarised. Further batches
are still created and emailed, with `ai_summary_status = SKIPPED`. The ceiling
keeps the AI bill close to its pre-hourly level when batches become more
frequent.

## 6. Test coverage

The behaviour above is covered by:

- `core/tests/tasks/test_auto_import_flag_matrix.py` — flag combinations and the
  silent-failure rows.
- `core/tests/services/test_import_queue_post_import_trigger.py` — completion
  hook and orchestrator dispatch.
- `core/tests/tasks/test_post_import_tasks.py` — daily window, tail shape, and
  notification gating.
- `core/tests/tasks/test_store_decisions_refetch_idempotency.py` — repeated
  fetches and the health-check guard.
- `core/tests/tasks/test_hourly_catchup_window.py` — the 24-hour cap and
  watermark behaviour.
- `core/tests/tasks/test_amount_correction_tasks.py` — finaliser sweeper.
- `notifications/tests/unit/test_hourly_notification_cadence.py` — overlapping
  runs, deduplication, and no re-sends.
- `notifications/tests/unit/test_notification_preference.py` and
  `test_notification_preference_api.py` — preference defaults, digests, the AI
  ceiling, and the API.
