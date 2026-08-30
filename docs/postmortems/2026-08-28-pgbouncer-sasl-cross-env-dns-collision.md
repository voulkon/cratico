# Postmortem: PgBouncer "SASL authentication failed" — cross-environment DNS collision

**Date:** 2026-08-28
**Status:** Root cause confirmed
**Impact:** Production Celery Beat unable to reach the database; risk of cross-environment service routing

---

## Summary

Starting 2026-08-27 ~22:55, the production `beat` container began failing to connect to
the database through PgBouncer with `FATAL: SASL authentication failed`. The web backend
kept working, and every credential on the production side appeared correct.

Root cause: the production and development stacks both define a Docker Compose service
named `pgbouncer` attached to the **same shared `coolify` network**. This makes the DNS
name `pgbouncer` ambiguous — Docker DNS returns the IPs of *both* PgBouncer containers and
round-robins their order, so clients get routed to the wrong environment's PgBouncer,
whose `userlist.txt` holds a different password.

---

## Symptoms

- `beat-iwwc8…` (prod) repeatedly logs `FATAL: SASL authentication failed` connecting to
  `pgbouncer` (172.20.0.16).
- `beat-ossk04…` (dev) logs the same error connecting to `pgbouncer` (172.20.0.4).
- `backend-iwwc8…` (prod) keeps working normally.
- Failures begin at 2026-08-27 ~22:55 — the same time the dev stack was deployed.

---

## What we know for sure (confirmed)

### 1. The credentials were not the problem

- SHA-256 of prod beat's `DATABASE_URL` password == SHA-256 of prod PgBouncer's
  `userlist.txt` password (`12ffc932…`, both 64 bytes).
- The password contains no special characters.
- `psycopg2` (`2.9.12`) and libpq (`170009`) are identical in the beat and backend images.

### 2. Beat and backend used identical connection parameters

An A/B test from both containers with the same explicit `host/port/user/password/dbname`:

- `backend-iwwc8…` → `pgbouncer` **succeeds**
- `beat-iwwc8…` → `pgbouncer` **fails** with `SASL authentication failed`

### 3. `pgbouncer` resolves to two containers

`getent hosts pgbouncer` from both prod containers returns:

```
172.20.0.4   pgbouncer
172.20.0.16  pgbouncer
```

### 4. The two PgBouncers store different passwords

| Container (on `coolify`) | IP | Role | `userlist.txt` password |
|---|---|---|---|
| `pgbouncer-iwwc8…` | 172.20.0.4 | prod | `C3j…TzTm` |
| `pgbouncer-ossk04…` | 172.20.0.16 | dev | `qaB…pIZJ` |

Each container also has a second, environment-specific network (prod: 172.18.0.3,
dev: 172.29.0.4); the collision is on the shared `coolify` (172.20.0.x) network.

### 5. The beats were cross-wired into the wrong bouncer

- Prod beat error: `connection to "pgbouncer" (172.20.0.16)` → the **dev** bouncer
  (password `qaB…pIZJ`) → prod password rejected.
- Dev beat error: `connection to "pgbouncer" (172.20.0.4)` → the **prod** bouncer
  (password `C3j…TzTm`) → dev password rejected.

### 6. PgBouncer itself was not misconfigured or restarted

- `auth_type = scram-sha-256` with a plain-text password in `userlist.txt` is a supported
  combination (per PgBouncer documentation).
- Prod PgBouncer: `RestartCount=0`, `StartedAt=2026-08-26T16:33:06Z` — unchanged when the
  failures began.

---

## Root cause (confirmed)

Both the dev and prod compose stacks define a service named `pgbouncer` and attach it to
the shared `coolify` network. Docker's embedded DNS therefore resolves `pgbouncer` to
**both** containers and round-robins the address order; clients connect to whichever IP
comes first. Because the two bouncers store different passwords, any client that lands on
the wrong environment's bouncer is rejected with `SASL authentication failed`.

The timing follows directly: before the dev stack existed, `pgbouncer` resolved to exactly
one container.

---

## What we believe but did not fully prove (hypotheses)

- **Why the backend kept working while beat failed.** `getent` showed different address
  ordering (backend: prod-first; beat: dev-first), and the backend holds long-lived DB
  connections (`CONN_MAX_AGE=60` + `CONN_HEALTH_CHECKS`), while beat opens a new connection
  every scheduler tick. The backend's exact resolved IP at connection time was not captured,
  so this is strongly supported but not directly observed.
- **The collision is not limited to PgBouncer.** Any service name shared by both stacks on
  the `coolify` network (`redis`, `rabbitmq`, `worker`, `flower`, `frontend`, `nginx`, …) is
  subject to the same ambiguity. Only the PgBouncer case was directly observed.

---

## What was ruled out

- Password mismatch between prod beat and prod PgBouncer (hashes identical).
- PgBouncer misconfiguration (plaintext + SCRAM is valid; prod bouncer unchanged since
  8/26; backend reaches it fine).
- Special characters in the password (alphanumeric).
- psycopg2 / libpq version drift between beat and backend (identical).

---

## Impact

- Production Celery Beat could not read the schedule from the DB → scheduled tasks stopped
  being dispatched; beat kept restarting (`RestartCount=17`, last start 03:30 UTC).
- Cross-environment routing: prod workers/cache/broker may reach their dev equivalents
  (and vice versa) — a data-leak and wrong-queue risk.

---

## Timeline (UTC)

- **2026-08-26 16:29–16:33** — prod deployment; prod PgBouncer created and started.
- **2026-08-27 ~19:55** (22:55 local) — dev stack deployed; a second `pgbouncer` alias
  appears on the shared network; SASL failures begin.
- **2026-08-28** — ongoing; beat crash-looping.

---

## Evidence

```text
# A/B connection test (identical explicit params)
backend-iwwc8… : backend -> pgbouncer OK
beat-iwwc8…    : FATAL: SASL authentication failed

# Name resolution
$ docker exec backend-iwwc8… getent hosts pgbouncer
172.20.0.4   pgbouncer
172.20.0.16  pgbouncer

$ docker exec beat-iwwc8… getent hosts pgbouncer
172.20.0.16  pgbouncer
172.20.0.4   pgbouncer

# PgBouncer IPs (two networks each; coolify = 172.20.0.x)
$ docker inspect pgbouncer-iwwc8…  --format 'prod {{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'
prod 172.20.0.4 172.18.0.3

$ docker inspect pgbouncer-ossk04… --format 'dev  {{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'
dev  172.20.0.16 172.29.0.4

# Password hashes (byte-identical)
beat DATABASE_URL password   → 12ffc932032096c1e6f68bca12202bd72d03d01b71173f4880f8ef86b2f55260
pgbouncer userlist password  → 12ffc932032096c1e6f68bca12202bd72d03d01b71173f4880f8ef86b2f55260
```

---

## Lessons

- Do not use a single shared Docker network (e.g. `coolify`) for **internal service
  discovery** across multiple environments. A shared name (`pgbouncer`, `redis`,
  `rabbitmq`, …) becomes ambiguous as soon as a second environment is deployed.
- The shared proxy network should carry only proxy-facing traffic (nginx); internal
  services need a per-environment, compose-created network.
- "The backend works, so PgBouncer is fine" is a misleading signal under DNS ambiguity —
  long-lived connections can mask intermittent cross-routing.
