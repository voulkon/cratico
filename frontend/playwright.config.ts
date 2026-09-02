import { defineConfig } from '@playwright/test';

/**
 * E2E config for the unified-auth matrix (task 05).
 *
 * Philosophy: tests run against an ALREADY-UP docker stack (same as the
 * manual matrix). No webServer — boot the stack first:
 *
 *   Row A (dual auth):   docker compose -f docker/docker-compose.yml \
 *                          --env-file=.env_files/.env.local.secrets up -d
 *   Row B/C (Django-only): same but with USE_CLERK_AUTH=false / keys unset
 *
 * Env vars:
 *   E2E_BASE_URL   — app origin (default http://localhost)
 *   E2E_API_URL    — API origin (default: same as base URL)
 *   E2E_EMAIL / E2E_PASSWORD — credentials for the Django test user
 *   E2E_CLERK_TEST_TOKEN — Clerk testing session token (row A Clerk spec;
 *     mint via @clerk/testing against the pk_test_ instance)
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: 1,
  workers: 1, // auth state is global (localStorage, backend users) — serialize
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
  ],
});
