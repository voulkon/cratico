/**
 * Bad-amount display semantics on the decision detail page.
 *
 * Backend phases (api/e2e_fixtures/bad_amounts.py) seed one decision per
 * wrong-amount case from docs/en/DATA_QUALITY.md and drive it through the
 * real correction pipeline. The four display states the page must
 * distinguish:
 *
 *   i=0 decimal shift        → corrected amount + corrected badge
 *   i=1 AFM as amount        → invalid hero (not money, real value unknown)
 *   i=2 KAE as amount        → invalid hero (not money, real value unknown)
 *   i=3 self-as-counterpart  → amount stays shown + counterpart warning
 *
 * Amount assertions are locale-tolerant (Greek 30.000,00 / English 30,000.00)
 * because the page formats with the browser locale.
 */
const { test, expect } = require('@playwright/test');
const { createHash } = require('crypto');
const { wireLifecycle } = require('./lifecycle');
const {
  isStealth,
  registerUser,
  loginViaApi,
  seedDjangoSession,
} = require('./helpers');

const lifecycle = wireLifecycle('bad-amounts');
test.beforeAll(() => lifecycle.setup());
test.afterAll(() => lifecycle.teardown());

/**
 * Mirrors shared._ada_token (backend): the ADAs are minted from the run id,
 * so the spec derives them instead of hardcoding.
 */
function decisionAda(index) {
  const hex = createHash('md5').update(lifecycle.runId).digest('hex');
  const token = (BigInt('0x' + hex) % (36n ** 8n)).toString(16)
    .slice(0, 8)
    .replace(/-/g, '0');
  return `E2E${token}${index}`.toUpperCase();
}

/** Locale-tolerant euro amount: euro('30', '000') matches €30.000,00 and €30,000.00. */
const euro = (...groups) =>
  new RegExp(`€\\s*${groups.join('[.,\\u00A0 ]?')}[.,]00`);

const ADAS = [0, 1, 2, 3].map(decisionAda);

test.describe('bad-amount display semantics', () => {
  test.beforeEach(async ({ page, request }) => {
    // Stealth mode requires a session; public stacks render without one.
    if (await isStealth(request)) {
      await registerUser(request);
      const token = await loginViaApi(request);
      await seedDjangoSession(page, token);
    }
  });

  test('decimal shift shows the corrected amount with the corrected badge', async ({
    page,
  }) => {
    await page.goto(`/decision/${ADAS[0]}`);

    const heroValue = page.locator(
      '.amount-hero:not(.amount-hero-invalid) .amount-hero-value'
    );
    await expect(heroValue).toContainText(euro('30', '000'));
    await expect(page.locator('.amount-corrected-badge')).toBeVisible();
    await expect(page.locator('.amount-hero-invalid')).toHaveCount(0);
    await expect(page.locator('.self-counterpart-note')).toHaveCount(0);
  });

  test('AFM-as-amount states the amount is not money', async ({ page }) => {
    await page.goto(`/decision/${ADAS[1]}`);

    const hero = page.locator('.amount-hero-invalid');
    await expect(hero).toBeVisible();
    // The counterpart VAT number the field actually holds.
    await expect(hero).toContainText('099370337');
    // The raw recorded value is shown even though it is excluded from totals.
    await expect(hero.locator('.amount-invalid-recorded')).toContainText(
      euro('99', '370', '337')
    );
    // No monetary amount is presented.
    await expect(
      page.locator('.amount-hero-value:not(.amount-invalid)')
    ).toHaveCount(0);
    await expect(page.locator('.amount-corrected-badge')).toHaveCount(0);
  });

  test('KAE-as-amount states the amount is not money', async ({ page }) => {
    await page.goto(`/decision/${ADAS[2]}`);

    const hero = page.locator('.amount-hero-invalid');
    await expect(hero).toBeVisible();
    await expect(hero).toContainText('706273001');
    await expect(hero.locator('.amount-invalid-recorded')).toContainText(
      euro('706', '273', '001')
    );
    await expect(
      page.locator('.amount-hero-value:not(.amount-invalid)')
    ).toHaveCount(0);
  });

  test('self-as-counterpart keeps the amount shown and warns about the counterpart', async ({
    page,
  }) => {
    await page.goto(`/decision/${ADAS[3]}`);

    // The amount is believed — it is displayed as money.
    const heroValue = page.locator(
      '.amount-hero:not(.amount-hero-invalid) .amount-hero-value'
    );
    await expect(heroValue).toContainText(euro('22', '000'));
    await expect(page.locator('.amount-hero-invalid')).toHaveCount(0);
    // …while the counterpart issue is called out separately.
    const note = page.locator('.self-counterpart-note');
    await expect(note).toBeVisible();
    await expect(note).toContainText('090064864');
  });
});