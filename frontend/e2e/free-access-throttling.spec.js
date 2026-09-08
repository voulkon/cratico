/**
 * Free-access & throttling E2E (task 03 of the free-access-throttling project).
 *
 * Proves, against an already-up docker-compose stack:
 *   Suite A — a normal anonymous user can freely use a public endpoint
 *             (200 + X-RateLimit-* headers, per-IP isolation).
 *   Suite B — a spammer bursting past the anonymous per-IP daily limit gets
 *             HTTP 429 from RateLimitMiddleware (auto-ban must be OFF).
 *   Suite C — a velocity burst is auto-banned with HTTP 403 (security flags ON).
 *
 * Self-skip: every suite fetches /api/system/config/auth/ and reads the
 * guarded `throttle` block; when absent (EXPOSE_E2E_OPERATIONAL_CONFIG off —
 * the production default) the whole file skips cleanly.
 *
 * Synthetic per-test client IP via X-Forwarded-For (NOT CF-Connecting-IP:
 * Cloudflare strips client-set values at the edge). The E2E stacks are
 * non-Cloudflare compose, where nginx appends the gateway to whatever the
 * client sent; get_client_ip() returns the leftmost non-infrastructure entry.
 *
 * NOTE on IP choice: the plan doc suggested RFC 5737 198.51.100.x, but
 * Python's ipaddress marks TEST-NET ranges is_private=True, so the backend's
 * is_infrastructure_ip() would exempt them. Use genuinely public IPs
 * (8.8.x.x) instead — see helpers.syntheticClientIP().
 *
 * Running locally:
 *
 *   # minimal rate-limit stack (DEBUG must be false so the limiter runs)
 *   DEBUG=false EXPOSE_E2E_OPERATIONAL_CONFIG=true ANON_API_DAILY_LIMIT=8 \
 *     docker compose -f docker/docker-compose.yml --env-file=.env_files/.env.dev up -d
 *   cd frontend && npx playwright test free-access-throttling.spec.js
 *
 *   # for Suite C add:
 *   #   SECURITY_MONITORING_ENABLED=true SECURITY_AUTO_BAN_ENABLED=true \
 *   #   SECURITY_VELOCITY_THRESHOLD=5
 *   # (Suite B self-skips on that stack: auto-ban must be off for a
 *   #  deterministic 429.)
 */
const { test, expect } = require('@playwright/test');
const {
  API_URL,
  getThrottleConfig,
  syntheticClientIP,
  anonApiGet,
  expectAppMounted,
} = require('./helpers');

// Representative free endpoint: PublicReadOnly, 24h response cache, cheap to
// repeat, not in the security "noisy" list.
const FREE_PATH = '/api/browse/entities/?type=organization&letter=%CE%91&limit=5';

// Exempt paths (never 429 even once the IP is throttled).
const EXEMPT_PATHS = ['/api/auth/login/', '/api/system/rate-limit/status/1/'];

// Buckets live in Redis for 24h, so a deterministic IP sequence would collide
// with leftovers from a previous run (locally or a retried CI job). Offset the
// seed by a run-unique random value (syntheticClientIP has ~62k slots, so
// collision odds between overlapping runs are negligible).
const RUN_OFFSET = Math.floor(Math.random() * 62500);
let ipSeed = 0;
function nextIP() {
  ipSeed += 1;
  return syntheticClientIP(RUN_OFFSET + ipSeed);
}

test.describe('free access & throttling', () => {
  let cfg;

  test.beforeEach(async ({ request }) => {
    cfg = await getThrottleConfig(request);
    test.skip(!cfg, 'throttle config not exposed on this stack (EXPOSE_E2E_OPERATIONAL_CONFIG off)');
  });

  // ── Suite A — free access (normal use) ────────────────────────────────
  test.describe('suite A: free access', () => {
    test('anonymous normal burst stays 200 with decreasing Remaining', async ({ request }) => {
      const ip = nextIP();
      let lastRemaining = null;

      for (let i = 0; i < 5; i++) {
        const res = await anonApiGet(request, ip, FREE_PATH);
        expect(res.status()).toBe(200);

        const limit = Number(res.headers()['x-ratelimit-limit']);
        const remaining = Number(res.headers()['x-ratelimit-remaining']);
        expect(limit).toBeGreaterThan(0);
        expect(remaining).toBeGreaterThan(0);
        expect(res.headers()['x-ratelimit-reset']).toBeTruthy();

        if (lastRemaining !== null) {
          expect(remaining).toBeLessThan(lastRemaining);
        }
        lastRemaining = remaining;
      }
    });

    test('per-IP isolation: a second IP has its own full bucket', async ({ request }) => {
      const ip1 = nextIP();
      const ip2 = nextIP();

      // Burn a few requests from IP1.
      for (let i = 0; i < 3; i++) {
        await anonApiGet(request, ip1, FREE_PATH);
      }

      // IP2's first request is 200 with a (near-)full remaining.
      const res = await anonApiGet(request, ip2, FREE_PATH);
      expect(res.status()).toBe(200);
      const remaining = Number(res.headers()['x-ratelimit-remaining']);
      const limit = Number(res.headers()['x-ratelimit-limit']);
      expect(remaining).toBeGreaterThanOrEqual(limit - 2);
    });

    test('free page loads anonymously (UI smoke)', async ({ page }) => {
      await expectAppMounted(page);
      // STEALTH_MODE=false on this stack: no auth prompt.
      const emailInput = page.locator('input[type="email"], input[name="email"]');
      await expect(emailInput).toHaveCount(0);
    });
  });

  // ── Suite B — spammer caught by the per-IP rate limiter (429) ─────────
  test.describe('suite B: 429 rate limiter', () => {
    test.beforeEach(async () => {
      test.skip(
        cfg.security_auto_ban_enabled !== false,
        'auto-ban must be OFF for a deterministic 429 (use the rate-limit stack)',
      );
    });

    test('burst past anon_daily_limit yields 429 with Remaining 0', async ({ request }) => {
      const ip = nextIP();
      const limit = cfg.anon_daily_limit;

      // `limit` sequential requests → all 200, last Remaining: 0.
      let last;
      for (let i = 0; i < limit; i++) {
        last = await anonApiGet(request, ip, FREE_PATH);
        expect(last.status()).toBe(200);
      }
      expect(Number(last.headers()['x-ratelimit-remaining'])).toBe(0);

      // Next 3 requests → 429 JSON with Remaining: 0.
      for (let i = 0; i < 3; i++) {
        const res = await anonApiGet(request, ip, FREE_PATH);
        expect(res.status()).toBe(429);
        const body = await res.json();
        expect(JSON.stringify(body)).toContain('Rate limit exceeded');
        expect(Number(res.headers()['x-ratelimit-remaining'])).toBe(0);
        expect(Number(res.headers()['x-ratelimit-limit'])).toBe(limit);
      }
    });

    test('exempt endpoints stay reachable once throttled', async ({ request }) => {
      const ip = nextIP();
      const limit = cfg.anon_daily_limit;

      for (let i = 0; i < limit; i++) {
        await anonApiGet(request, ip, FREE_PATH);
      }
      // Confirm the bucket is exhausted.
      expect((await anonApiGet(request, ip, FREE_PATH)).status()).toBe(429);

      for (const path of EXEMPT_PATHS) {
        const res = await anonApiGet(request, ip, path);
        expect(res.status()).not.toBe(429);
      }
    });
  });

  // ── Suite C — spammer auto-banned (403) ───────────────────────────────
  test.describe('suite C: security auto-ban (403)', () => {
    test.beforeEach(async () => {
      test.skip(
        !(cfg.security_monitoring_enabled && cfg.security_auto_ban_enabled),
        'security monitoring + auto-ban must be ON (use the security stack)',
      );
    });

    test('velocity burst crosses the threshold and gets 403', async ({ request }) => {
      const ip = nextIP();
      const velocity = cfg.security_velocity_threshold || 5;

      // Rapidly send velocity + ~5 requests; a 403 must appear once the
      // threshold is crossed.
      let saw403 = false;
      for (let i = 0; i < velocity + 5; i++) {
        const res = await anonApiGet(request, ip, FREE_PATH);
        if (res.status() === 403) {
          saw403 = true;
          break;
        }
      }
      expect(saw403).toBe(true);

      // Banned fast path: subsequent requests from the same IP stay 403.
      const again = await anonApiGet(request, ip, FREE_PATH);
      expect(again.status()).toBe(403);

      // A different IP is unaffected.
      const other = await anonApiGet(request, nextIP(), FREE_PATH);
      expect(other.status()).toBe(200);
    });
  });
});
