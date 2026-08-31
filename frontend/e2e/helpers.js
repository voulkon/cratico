/**
 * Shared helpers for the auth E2E specs.
 *
 * The Django auth token lives in localStorage under 'django_auth_token'
 * (see frontend/src/contexts/AuthContext.js). Seeding it directly lets us
 * skip the UI login form where the test's focus is elsewhere.
 */
export const TOKEN_KEY = 'django_auth_token';

export const API_URL = process.env.E2E_API_URL || process.env.E2E_BASE_URL || 'http://localhost';

export const TEST_EMAIL = process.env.E2E_EMAIL || `e2e-${Date.now()}@example.com`;
export const TEST_PASSWORD = process.env.E2E_PASSWORD || 'E2e-Sup3r-Secret!';

/** Register a user via the API. Idempotent-ish: 400 on duplicate is fine. */
export async function registerUser(request, email = TEST_EMAIL, password = TEST_PASSWORD) {
  const res = await request.post(`${API_URL}/api/auth/register/`, {
    data: { email, password, password2: password },
  });
  // 201 created, 400 already-exists — both acceptable for seeding.
  return res.status();
}

/** Login via the API and return the auth token. */
export async function loginViaApi(request, email = TEST_EMAIL, password = TEST_PASSWORD) {
  const res = await request.post(`${API_URL}/api/auth/login/`, {
    data: { email, password },
  });
  if (!res.ok()) {
    throw new Error(`API login failed: ${res.status()} ${await res.text()}`);
  }
  const data = await res.json();
  return data.token;
}

/** Seed localStorage with a valid Django token, then reload. */
export async function seedDjangoSession(page, token) {
  await page.goto('/');
  await page.evaluate(
    ([key, value]) => localStorage.setItem(key, value),
    [TOKEN_KEY, token],
  );
  await page.reload();
}

/** Wait until the SPA has actually mounted (white-page detector). */
export async function expectAppMounted(page) {
  await page.goto('/');
  await page.waitForFunction(
    () => {
      const root = document.getElementById('root');
      return root && root.children.length > 0;
    },
    { timeout: 15_000 },
  );
}

/** True if the backend advertises Clerk in auth_methods. */
export async function getAuthMethods(request) {
  const res = await request.get(`${API_URL}/api/system/config/auth/`);
  if (!res.ok()) throw new Error(`auth config fetch failed: ${res.status()}`);
  const data = await res.json();
  return data.auth_methods ?? ['django'];
}

/** Full auth config (auth_methods + authentication.required/stealth). */
export async function getAuthConfig(request) {
  const res = await request.get(`${API_URL}/api/system/config/auth/`);
  if (!res.ok()) throw new Error(`auth config fetch failed: ${res.status()}`);
  return res.json();
}

/** True when the backend requires auth (STEALTH_MODE on). */
export async function isStealth(request) {
  const cfg = await getAuthConfig(request);
  return !!cfg.authentication?.required;
}

/**
 * Make the Django email login form visible.
 *
 * Stealth ON  → `/` renders LoginPage directly, so the form is already there.
 * Stealth OFF → `/` is the public home page; open the user menu and click the
 *               sign-in button to mount the (self-contained) AuthModal.
 */
export async function openDjangoLoginForm(page, request) {
  await expectAppMounted(page);
  if (await isStealth(request)) {
    return; // LoginPage renders the form directly.
  }
  // Open the user menu (aria-label "Open menu"), then click its Sign In.
  await page.getByRole('button', { name: /open menu/i }).first().click();
  await page
    .locator('.user-menu-dropdown button, .menu-action')
    .filter({ hasText: /sign in|log ?in|σύνδεση/i })
    .first()
    .click();
}
