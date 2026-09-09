"""
E2E data lifecycle — registry of per-spec setup/teardown phases.

PARITY CONTRACT
===============
The key is the e2e spec file stem (e.g. ``auth`` for ``e2e/auth.spec.js``).
Each entry declares which phases exist for that spec:

    {"auth": {"setup": "auth.setup", "teardown": "auth.teardown"}}

Values are "module.function" paths relative to this package. A phase that is
absent from the entry simply never runs — a spec that only needs teardown
(e.g. clerk, which registers users inside the test body) declares only
``teardown`` and the dispatcher no-ops the missing setup.

All fixture functions are run-scoped: they receive ``run_id`` and tag every
created row with it (``uid``/``ada``/``username`` prefixes). Teardown deletes
ONLY rows carrying that run id, so concurrent or abandoned runs never clobber
each other. See shared.py for the factories and the prefix conventions.

Discover the registry with:
    python manage.py e2e_data --list
"""

REGISTRY = {
    # auth.spec.js: creates users via the public register endpoint.
    "auth": {
        "setup": "auth.setup",
        "teardown": "auth.teardown",
    },
    # clerk.spec.js: registers its user inside the test body (real email),
    # needs no seeding — only the sweep after the run.
    "clerk": {
        "teardown": "clerk.teardown",
    },
    # free-access-throttling.spec.js: no DB data (synthetic IPs + Redis
    # buckets are cleaned by the throttle spec itself). Declared here so the
    # parity smoke test can assert every spec file is registered.
    "free-access-throttling": {},
    # Reserved for issue #137 (search flows with seeded data). Factories are
    # ready in search.py; the spec lands with the search E2E work.
    "search": {
        "setup": "search.setup",
        "teardown": "search.teardown",
    },
}


def get_phase(spec: str, phase: str):
    """Return the callable for (spec, phase), or None when not declared."""
    entry = REGISTRY.get(spec) or {}
    target = entry.get(phase)
    if not target:
        return None
    import importlib

    package = __package__
    module_name, fn_name = target.rsplit(".", 1)
    module = importlib.import_module(f"{package}.{module_name}")
    return getattr(module, fn_name)
