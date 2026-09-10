/**
 * Spec ↔ backend data-phase parity helper.
 *
 * Specs declare their lifecycle by calling these in test.beforeAll /
 * test.afterAll. Phases resolve through the backend's REGISTRY
 * (backend/api/e2e_fixtures/__init__.py) — an undeclared phase no-ops on the
 * backend side, so specs and fixtures stay in sync by declaration.
 *
 * Execution: shells out to `make e2e-phase` (needs COMPOSE_FILE / ENV_FILE /
 * RUN_ID env — see Makefile). afterAll runs even when tests fail, which is
 * the whole point: setup data is removed on every exit path.
 */
const { execSync } = require('child_process');
const path = require('path');

/** Workspace root (repo root = frontend/e2e/../../). */
const WORKSPACE_ROOT = path.resolve(__dirname, '..', '..');

/** Stable per-invocation run id — spread as RUN_ID to make + backend. */
const RUN_ID = process.env.E2E_RUN_ID || process.env.PLAYWRIGHT_RUN_ID ||
  Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

function runPhase(spec, phase) {
  const make = process.platform === 'win32' ? 'make' : 'make';
  execSync(
    `${make} e2e-phase SPEC=${spec} PHASE=${phase} RUN_ID=${RUN_ID}`,
    { stdio: 'inherit', cwd: process.env.E2E_WORKSPACE_ROOT || WORKSPACE_ROOT },
  );
}

/**
 * Wire a spec to its backend phases:
 *   const lifecycle = wireLifecycle('search');
 *   test.beforeAll(() => lifecycle.setup());
 *   test.afterAll(() => lifecycle.teardown());
 */
function wireLifecycle(spec) {
  return {
    runId: RUN_ID,
    setup: () => {
      try {
        runPhase(spec, 'setup');
      } catch (err) {
        // Setup failure should fail loudly — tests would run against missing data.
        throw new Error(`e2e setup phase failed for '${spec}': ${err.message}`);
      }
    },
    teardown: () => {
      try {
        runPhase(spec, 'teardown');
      } catch (err) {
        // Teardown must never mask test results, but do leave a trace.
        console.error(`[e2e] teardown phase failed for '${spec}':`, err.message);
      }
    },
  };
}

module.exports = { RUN_ID, wireLifecycle };
