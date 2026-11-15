#!/usr/bin/env node
/**
 * check-theme-defaults.js
 *
 * Verifies that the pre-paint theme script in public/index.html resolves
 * themes/palettes exactly like src/constants/theme.json says it should
 * (ids, defaults, and system-mode counterparts).
 *
 * The inline script cannot import the JSON (it runs before the bundle), so it
 * is a hand-maintained copy. This check executes that copy in a sandbox with
 * a stubbed localStorage/document/matchMedia and compares the resulting
 * data-theme / data-palette attributes.
 *
 * Usage:
 *   node scripts/check-theme-defaults.js
 *
 * Exit code:
 *   0 — inline script matches src/constants/theme.json
 *   1 — drift found (report printed to stderr)
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const DEFAULTS = require(path.join(ROOT, 'src', 'constants', 'theme.json'));
const INDEX_HTML = path.join(ROOT, 'public', 'index.html');

const html = fs.readFileSync(INDEX_HTML, 'utf8');

const inlineScripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(
  (match) => match[1]
);
const themeScript = inlineScripts.find((script) => script.includes('data-theme'));

if (!themeScript) {
  console.error(
    'check-theme-defaults: could not find the inline theme script in public/index.html'
  );
  process.exit(1);
}

function runInlineScript({ storage = {}, prefersDark = false } = {}) {
  const store = new Map(Object.entries(storage));
  const attrs = {};

  const context = {
    localStorage: {
      getItem: (key) => (store.has(key) ? store.get(key) : null),
      setItem: (key, value) => store.set(key, String(value)),
      removeItem: (key) => store.delete(key)
    },
    window: {
      matchMedia: () => ({
        matches: prefersDark,
        addEventListener() {},
        removeEventListener() {}
      })
    },
    document: {
      documentElement: {
        setAttribute: (name, value) => {
          attrs[name] = value;
        }
      }
    }
  };

  vm.runInNewContext(themeScript, context);
  return { attrs, store };
}

const failures = [];

function check(name, actual, expected) {
  if (actual !== expected) {
    failures.push(`${name}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
}

// ── JSON self-consistency ────────────────────────────────────────────────
if (!DEFAULTS.themeIds.includes(DEFAULTS.defaultTheme)) {
  failures.push(`theme.json: defaultTheme "${DEFAULTS.defaultTheme}" is not in themeIds`);
}
if (!DEFAULTS.concreteThemeIds.includes(DEFAULTS.defaultSystemBase)) {
  failures.push(
    `theme.json: defaultSystemBase "${DEFAULTS.defaultSystemBase}" is not in concreteThemeIds`
  );
}
const paletteIds = DEFAULTS.palettes.map((entry) => entry.id);
if (new Set(paletteIds).size !== paletteIds.length) {
  failures.push('theme.json: palettes contains duplicate ids');
}
for (const entry of DEFAULTS.palettes) {
  for (const field of ['id', 'name', 'color', 'darkColor']) {
    if (!entry[field]) failures.push(`theme.json: palette "${entry.id}" is missing "${field}"`);
  }
}
if (!paletteIds.includes(DEFAULTS.defaultPalette)) {
  failures.push(`theme.json: defaultPalette "${DEFAULTS.defaultPalette}" is not in palettes`);
}
for (const [from, to] of Object.entries(DEFAULTS.darkCounterpart)) {
  if (!DEFAULTS.concreteThemeIds.includes(from) || !DEFAULTS.concreteThemeIds.includes(to)) {
    failures.push(`theme.json: darkCounterpart "${from}" -> "${to}" uses a non-concrete theme`);
  }
}
for (const [from, to] of Object.entries(DEFAULTS.lightCounterpart)) {
  if (!DEFAULTS.concreteThemeIds.includes(from) || !DEFAULTS.concreteThemeIds.includes(to)) {
    failures.push(`theme.json: lightCounterpart "${from}" -> "${to}" uses a non-concrete theme`);
  }
}

// ── Inline id lists match the JSON exactly ───────────────────────────────
function extractInlineArray(name) {
  const match = themeScript.match(new RegExp(`${name}\\s*=\\s*\\[([^\\]]*)\\]`));
  if (!match) return null;
  return [...match[1].matchAll(/'([^']*)'|"([^"]*)"/g)].map((entry) => entry[1] ?? entry[2]);
}

check(
  'inline THEME_IDS',
  JSON.stringify(extractInlineArray('THEME_IDS')),
  JSON.stringify(DEFAULTS.themeIds)
);
check(
  'inline CONCRETE_THEME_IDS',
  JSON.stringify(extractInlineArray('CONCRETE_THEME_IDS')),
  JSON.stringify(DEFAULTS.concreteThemeIds)
);
check(
  'inline PALETTE_IDS',
  JSON.stringify(extractInlineArray('PALETTE_IDS')),
  JSON.stringify(paletteIds)
);

// ── No stored preference ─────────────────────────────────────────────────
{
  const { attrs } = runInlineScript();
  check('default theme', attrs['data-theme'], DEFAULTS.defaultTheme);
  check('default palette', attrs['data-palette'], DEFAULTS.defaultPalette);
}

// ── Every concrete theme id is accepted verbatim ─────────────────────────
for (const id of DEFAULTS.concreteThemeIds) {
  const { attrs } = runInlineScript({ storage: { theme: id } });
  check(`theme=${id}`, attrs['data-theme'], id);
}

// ── Invalid / legacy values fall back to the defaults ────────────────────
{
  const legacy = runInlineScript({ storage: { theme: 'auto' } });
  const expectedLegacy =
    DEFAULTS.lightCounterpart[DEFAULTS.defaultSystemBase] || DEFAULTS.defaultSystemBase;
  check('legacy theme "auto"', legacy.attrs['data-theme'], expectedLegacy);

  const invalid = runInlineScript({ storage: { theme: 'neon' } });
  check('invalid theme', invalid.attrs['data-theme'], DEFAULTS.defaultTheme);

  const invalidPalette = runInlineScript({ storage: { palette: 'neon' } });
  check('invalid palette', invalidPalette.attrs['data-palette'], DEFAULTS.defaultPalette);
}

// ── "system" follows the OS preference within the captured family ────────
{
  const defaultBaseDarkOs = runInlineScript({
    storage: { theme: 'system' },
    prefersDark: true
  });
  check(
    'system/default base + dark OS',
    defaultBaseDarkOs.attrs['data-theme'],
    DEFAULTS.darkCounterpart[DEFAULTS.defaultSystemBase] || DEFAULTS.defaultSystemBase
  );

  const lightBaseDarkOs = runInlineScript({
    storage: { theme: 'system', 'system-theme-base': 'light' },
    prefersDark: true
  });
  check(
    'system/light base + dark OS',
    lightBaseDarkOs.attrs['data-theme'],
    DEFAULTS.darkCounterpart.light || 'light'
  );

  const darkBaseLightOs = runInlineScript({
    storage: { theme: 'system', 'system-theme-base': 'dark' },
    prefersDark: false
  });
  check(
    'system/dark base + light OS',
    darkBaseLightOs.attrs['data-theme'],
    DEFAULTS.lightCounterpart.dark || 'dark'
  );

  const solarizedBaseDarkOs = runInlineScript({
    storage: { theme: 'system', 'system-theme-base': 'solarized-light' },
    prefersDark: true
  });
  check(
    'system/solarized-light base + dark OS',
    solarizedBaseDarkOs.attrs['data-theme'],
    DEFAULTS.darkCounterpart['solarized-light'] || 'solarized-light'
  );

  const solarizedBaseLightOs = runInlineScript({
    storage: { theme: 'system', 'system-theme-base': 'solarized-dark' },
    prefersDark: false
  });
  check(
    'system/solarized-dark base + light OS',
    solarizedBaseLightOs.attrs['data-theme'],
    DEFAULTS.lightCounterpart['solarized-dark'] || 'solarized-dark'
  );
}

// ── Every palette id is accepted verbatim ────────────────────────────────
for (const id of paletteIds) {
  const { attrs } = runInlineScript({ storage: { palette: id } });
  check(`palette=${id}`, attrs['data-palette'], id);
}

if (failures.length > 0) {
  console.error('Theme defaults drifted between public/index.html and src/constants/theme.json:');
  for (const failure of failures) console.error(`  - ${failure}`);
  process.exit(1);
}

console.log(
  `Theme defaults OK (theme: ${DEFAULTS.defaultTheme}, palette: ${DEFAULTS.defaultPalette}).`
);
