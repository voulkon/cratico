#!/usr/bin/env node
/**
 * Translation coverage checker.
 *
 * Compares the keys referenced from `t('…')` calls in src/ with the keys
 * defined in src/locales/*.json and reports:
 *
 *   - keys used in code but missing from a locale (per locale)
 *   - keys present in one locale but missing from the base locale (en)
 *   - keys defined in a locale but never referenced in code (stale keys)
 *   - interpolation placeholders that differ between locales for the same key
 *   - double-brace placeholders such as `{{count}}` (not supported by the
 *     TranslationContext interpolator, which only matches `{count}`)
 *
 * Dynamic keys built with a template literal, e.g. `t(`entityTypes.${type}`)`,
 * are recorded as prefixes and excluded from the "unused" report so whole
 * key families are not flagged.
 *
 * Usage:
 *   node scripts/check-i18n.js                 # fail on missing/parity errors
 *   node scripts/check-i18n.js --fail-on-unused
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const SRC_DIR = path.join(ROOT, 'src');
const LOCALES_DIR = path.join(SRC_DIR, 'locales');
const BASE_LOCALE = 'en';
const SOURCE_EXTENSIONS = new Set(['.js', '.jsx', '.ts', '.tsx']);
const IGNORED_DIRS = new Set(['node_modules', 'build', '.git', '__tests__']);

const failOnUnused = process.argv.includes('--fail-on-unused');

function walk(dir, files = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name.startsWith('.')) continue;
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (IGNORED_DIRS.has(entry.name)) continue;
      walk(fullPath, files);
    } else if (SOURCE_EXTENSIONS.has(path.extname(entry.name))) {
      files.push(fullPath);
    }
  }
  return files;
}

function flatten(value, prefix = '', out = {}) {
  for (const [key, child] of Object.entries(value)) {
    const fullKey = prefix ? `${prefix}.${key}` : key;
    if (child && typeof child === 'object' && !Array.isArray(child)) {
      flatten(child, fullKey, out);
    } else {
      out[fullKey] = child;
    }
  }
  return out;
}

/**
 * Returns the interpolation parameter names used by a translation string.
 * Plural/format blocks such as `{count, plural, one {…} other {…}}` contribute
 * only `count`; the nested branch text is not treated as placeholders.
 */
function extractPlaceholders(value) {
  if (typeof value !== 'string') return new Set();
  const names = new Set();
  let i = 0;
  while (i < value.length) {
    if (value[i] !== '{') {
      i += 1;
      continue;
    }
    const blockStart = i;
    i += 1;
    let name = '';
    while (i < value.length && /[A-Za-z0-9_]/.test(value[i])) {
      name += value[i];
      i += 1;
    }
    if (!name) continue;

    while (i < value.length && /\s/.test(value[i])) i += 1;

    if (value[i] === '}') {
      names.add(name);
      i += 1;
      continue;
    }

    if (value[i] === ',') {
      names.add(name);
      let depth = 1;
      i = blockStart + 1;
      while (i < value.length && depth > 0) {
        if (value[i] === '{') depth += 1;
        else if (value[i] === '}') depth -= 1;
        i += 1;
      }
    }
  }
  return names;
}

function formatSet(set) {
  return [...set].sort().join(', ');
}

function main() {
  const localeFiles = fs
    .readdirSync(LOCALES_DIR)
    .filter((file) => file.endsWith('.json'))
    .sort();

  const locales = {};
  for (const file of localeFiles) {
    const name = path.basename(file, '.json');
    const json = JSON.parse(fs.readFileSync(path.join(LOCALES_DIR, file), 'utf8'));
    locales[name] = flatten(json);
  }

  if (!locales[BASE_LOCALE]) {
    console.error(`Base locale "${BASE_LOCALE}.json" not found in ${LOCALES_DIR}`);
    process.exit(1);
  }

  const usedKeys = new Map(); // key -> first file (relative)
  const dynamicPrefixes = new Map(); // prefix -> first file (relative)

  const callPattern =
    /(?<![.\w$])t\s*\(\s*(?:'((?:\\.|[^'\\])*)'|"((?:\\.|[^"\\])*)"|`((?:\\.|[^`\\])*)`)/g;

  for (const file of walk(SRC_DIR)) {
    const source = fs.readFileSync(file, 'utf8');
    const relative = path.relative(ROOT, file);
    let match;
    while ((match = callPattern.exec(source)) !== null) {
      const literal = match[1] ?? match[2] ?? match[3];
      if (literal === undefined) continue;

      if (match[3] !== undefined && literal.includes('${')) {
        const prefix = literal.slice(0, literal.indexOf('${'));
        if (prefix && !dynamicPrefixes.has(prefix)) {
          dynamicPrefixes.set(prefix, relative);
        }
        continue;
      }

      if (!usedKeys.has(literal)) usedKeys.set(literal, relative);
    }
  }

  const isDynamicKey = (key) =>
    [...dynamicPrefixes.keys()].some((prefix) => key.startsWith(prefix));

  const errors = [];
  const warnings = [];

  // 1. Keys referenced in code but missing from each locale.
  for (const [locale, keys] of Object.entries(locales)) {
    const missing = [...usedKeys.keys()]
      .filter((key) => !(key in keys) && !isDynamicKey(key))
      .sort();
    if (missing.length) {
      errors.push(
        `[${locale}] ${missing.length} key(s) used in code but missing from ${locale}.json:`
      );
      for (const key of missing) {
        errors.push(`  - ${key}  (${usedKeys.get(key)})`);
      }
    }
  }

  // 2. Locale key parity against the base locale.
  const baseKeys = new Set(Object.keys(locales[BASE_LOCALE]));
  for (const [locale, keys] of Object.entries(locales)) {
    if (locale === BASE_LOCALE) continue;
    const localeKeys = new Set(Object.keys(keys));

    const missingInLocale = [...baseKeys].filter((key) => !localeKeys.has(key)).sort();
    if (missingInLocale.length) {
      errors.push(`[${locale}] ${missingInLocale.length} key(s) present in ${BASE_LOCALE}.json but missing:`);
      for (const key of missingInLocale) errors.push(`  - ${key}`);
    }

    const missingInBase = [...localeKeys].filter((key) => !baseKeys.has(key)).sort();
    if (missingInBase.length) {
      errors.push(`[${locale}] ${missingInBase.length} key(s) present only in ${locale}.json (not in ${BASE_LOCALE}.json):`);
      for (const key of missingInBase) errors.push(`  - ${key}`);
    }
  }

  // 3. Keys defined in JSON but never referenced from code.
  for (const [locale, keys] of Object.entries(locales)) {
    const unused = Object.keys(keys)
      .filter((key) => !usedKeys.has(key) && !isDynamicKey(key))
      .sort();
    if (unused.length) {
      warnings.push(`[${locale}] ${unused.length} unused key(s):`);
      for (const key of unused) warnings.push(`  - ${key}`);
    }
  }

  // 4. Placeholder parity between locales.
  for (const [locale, keys] of Object.entries(locales)) {
    if (locale === BASE_LOCALE) continue;
    for (const [key, baseValue] of Object.entries(locales[BASE_LOCALE])) {
      if (!(key in keys)) continue;
      const baseParams = extractPlaceholders(baseValue);
      const localeParams = extractPlaceholders(keys[key]);
      if (formatSet(baseParams) !== formatSet(localeParams)) {
        warnings.push(
          `[${locale}] placeholder mismatch for ${key}: ${BASE_LOCALE} has {${formatSet(baseParams)}}, ${locale} has {${formatSet(localeParams)}}`
        );
      }
    }
  }

  // 5. Double-brace placeholders (the t() interpolator only supports single braces).
  for (const [locale, keys] of Object.entries(locales)) {
    for (const [key, value] of Object.entries(keys)) {
      if (typeof value === 'string' && /\{\{[^}]+\}\}/.test(value)) {
        warnings.push(
          `[${locale}] ${key} contains a double-brace placeholder that will not be interpolated: ${JSON.stringify(value)}`
        );
      }
    }
  }

  // Report.
  console.log('Translation coverage check');
  console.log(`  base locale: ${BASE_LOCALE}`);
  console.log(`  locales: ${Object.keys(locales).join(', ')}`);
  console.log(`  referenced keys: ${usedKeys.size}`);
  if (dynamicPrefixes.size) {
    console.log(
      `  dynamic key prefixes (excluded from unused check): ${[...dynamicPrefixes.keys()].join(', ')}`
    );
  }
  console.log('');

  if (errors.length) {
    console.log('ERRORS');
    for (const line of errors) console.log(line);
    console.log('');
  } else {
    console.log('No missing keys or locale parity errors.');
    console.log('');
  }

  if (warnings.length) {
    console.log('WARNINGS');
    for (const line of warnings) console.log(line);
    console.log('');
  } else {
    console.log('No warnings.');
    console.log('');
  }

  if (errors.length || (failOnUnused && warnings.length)) {
    process.exit(1);
  }
}

main();
