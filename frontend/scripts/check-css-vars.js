#!/usr/bin/env node
/**
 * check-css-vars.js
 *
 * Scans all .css files under src/ for CSS custom properties used via var(--*)
 * that are NOT defined in src/index.css.
 *
 * Usage:
 *   node scripts/check-css-vars.js
 *
 * Exit code:
 *   0 — no missing variables
 *   1 — missing variables found (report printed to stderr)
 */

const fs = require('fs');
const path = require('path');

const SRC_DIR = path.resolve(__dirname, '..', 'src');
const INDEX_CSS = path.join(SRC_DIR, 'index.css');

// ── 1. Extract all --var names DEFINED in index.css ──────────────────────
const indexContent = fs.readFileSync(INDEX_CSS, 'utf8');
// Match `--foo-bar:` definitions (property declarations)
const defined = new Set();
const defRe = /(--[\w-]+)\s*:/g;
let m;
while ((m = defRe.exec(indexContent)) !== null) {
  defined.add(m[1]);
}

// ── 2. Walk all .css files in src/ ──────────────────────────────────────
function walk(dir) {
  const results = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...walk(full));
    } else if (entry.isFile() && entry.name.endsWith('.css')) {
      results.push(full);
    }
  }
  return results;
}

const cssFiles = walk(SRC_DIR);

// ── 3. Find var(--*) usages not in the defined set ──────────────────────
const useRe = /var\((--[\w-]+)/g;
let totalMissing = 0;
const missingByFile = {};

for (const file of cssFiles) {
  // Skip index.css itself
  if (file === INDEX_CSS) continue;

  const content = fs.readFileSync(file, 'utf8');
  const used = new Set();
  while ((m = useRe.exec(content)) !== null) {
    used.add(m[1]);
  }

  const missing = [...used].filter(v => !defined.has(v)).sort();
  if (missing.length > 0) {
    missingByFile[path.relative(SRC_DIR, file)] = missing;
    totalMissing += missing.length;
  }
}

// ── 4. Report ───────────────────────────────────────────────────────────
if (totalMissing === 0) {
  console.log(`[OK] All CSS variables used in ${cssFiles.length - 1} files are defined in index.css`);
  process.exit(0);
} else {
  console.error(`[WARNING] Found ${totalMissing} undefined CSS variable(s) across ${Object.keys(missingByFile).length} file(s):\n`);
  for (const [file, vars] of Object.entries(missingByFile)) {
    console.error(`  ${file}:`);
    for (const v of vars) {
      console.error(`    ${v}`);
    }
  }
  console.error(`\nAdd missing variables to src/index.css or use them with a fallback: var(${Object.values(missingByFile).flat()[0]}, fallback-value)`);
  process.exit(1);
}
