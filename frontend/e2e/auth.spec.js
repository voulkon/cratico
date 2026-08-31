/**
 * Auth matrix E2E — specs 1, 2, 4 from task 05 (no Clerk dependency).
 *
 * Spec 1: boot smoke — #root mounts in every config (white-page detector).
 * Spec 2: Django login flow (UI + API-seeded session).
 * Spec 4: /api/system/config/auth/ contract.
 *
 * Runs against an already-up docker stack. Skip-if-mismatch: the Clerk-only
 * specs live in clerk.spec.js and self-skip when the stack is Django-only.
 */
const { test, expect } = require('@playwright/test');
const {
  API_URL,
  TEST_EMAIL,
  TEST_PASSWORD,
  registerUser,
  loginViaApi,
  seedDjangoSession,
  expectAppMounted,
  getAuthMethods,
  isStealth,
  openDjangoLoginForm,
} = require('./helpers');

// ---------------------------------------------------------------------------
// Spec 1 — boot smoke (would have caught the 2026-08-30 white page)
// ---------------------------------------------------------------------------
test.describe('boot smoke', () => {
  test('app shell mounts — #root is non-empty', async ({ page }) => {
    await expectAppMounted(page);
  });

  test('login page renders the Django email form', async ({ page, request }) => {
    // Stealth ON: form is on `/` directly. Stealth OFF: open the auth modal.
    await openDjangoLoginForm(page, request);
    // Email input must exist regardless of provider mix.
    await expect(page.locator('input[type="email"], input[name="email"]').first())
      .toBeVisible({ timeout: 15_000 });
  });
});

// ---------------------------------------------------------------------------
// Spec 4 — auth config contract
// ---------------------------------------------------------------------------
test.describe('auth config endpoint', () => {
  test('returns auth_methods and never leaks a Clerk key when Clerk is off', async ({ request }) => {
    const res = await request.get(`${API_URL}/api/system/config/auth/`);
    expect(res.ok()).toBeTruthy();
    const data = await res.json();

    expect(Array.isArray(data.auth_methods)).toBeTruthy();
    expect(data.auth_methods).toContain('django'); // django is always available

    if (!data.auth_methods.includes('clerk')) {
      expect(data.clerk_publishable_key ?? null).toBeNull();
    } else {
      expect(data.clerk_publishable_key).toMatch(/^pk_/);
    }
  });
});

// ---------------------------------------------------------------------------
// Spec 2 — Django auth flow
// ---------------------------------------------------------------------------
test.describe('django auth flow', () => {
  test('API register + login yields a working token session', async ({ request, page }) => {
    await registerUser(request);
    const token = await loginViaApi(request); // throws on failure

    await seedDjangoSession(page, token);
    await expectAppMounted(page);

    // /auth/me/ must validate the seeded token — i.e. we are signed in,
    // not staring at the signed-out UI.
    const res = await request.get(`${API_URL}/api/auth/me/`, {
      headers: { Authorization: `Token ${token}` },
    });
    expect(res.ok()).toBeTruthy();
    const me = await res.json();
    expect(me.user?.email?.toLowerCase()).toBe(TEST_EMAIL.toLowerCase());
  });

  test('UI login form signs in and stores the token', async ({ page, request }) => {
    await registerUser(request);
    await openDjangoLoginForm(page, request);

    await page.locator('input[type="email"], input[name="email"]').first().fill(TEST_EMAIL);
    await page.locator('input[type="password"]').first().fill(TEST_PASSWORD);
    await page.getByRole('button', { name: /^sign in$|^log ?in$|^σύνδεση$/i }).last().click();

    // AuthContext writes the token on success.
    await page.waitForFunction(
      () => !!localStorage.getItem('django_auth_token'),
      { timeout: 15_000 },
    );
  });

  test('sign-out clears the Django token', async ({ page, request }) => {
    await registerUser(request);
    const token = await loginViaApi(request);
    await seedDjangoSession(page, token);

    // The seeded token must render the signed-in user menu before we act.
    await page.getByRole('button', { name: /open menu/i }).first().click();
    await expect(page.locator('.user-menu-dropdown .user-email-bold').first())
      .toBeVisible({ timeout: 15_000 });

    // Sign out from the dropdown, then the token must be gone.
    await page.locator('.user-menu-dropdown .sign-out-inline').first().click();
    await page.waitForFunction(
      () => !localStorage.getItem('django_auth_token'),
      { timeout: 15_000 },
    );
  });

  test('Django-only mode: zero requests to clerk.accounts.dev', async ({ page }) => {
    const methods = await getAuthMethods(page.request);
    test.skip(methods.includes('clerk'), 'Row B/C only — Clerk is active on this stack');

    const clerkRequests = [];
    page.on('request', (req) => {
      if (/clerk\.(accounts|com)/i.test(req.url())) clerkRequests.push(req.url());
    });

    await expectAppMounted(page);
    expect(clerkRequests).toEqual([]);
  });
});
