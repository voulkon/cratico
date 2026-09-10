"""
E2E data lifecycle dispatcher.

Parity between Playwright specs and their data phases is declared in
api/e2e_fixtures/REGISTRY (keyed by spec file stem). This command resolves
and runs the requested phase — no-ops when the phase isn't declared.

Usage (usually via `make e2e-phase` from the frontend lifecycle helper):
    python manage.py e2e_data --spec=auth --phase=setup --run-id=abc123
    python manage.py e2e_data --spec=clerk --phase=teardown --run-id=abc123
    python manage.py e2e_data --list
    python manage.py e2e_data --sweep-stale            # GC crashed runs
    python manage.py e2e_data --phase=teardown --all   # teardown every spec
"""

from api.e2e_fixtures import REGISTRY, get_phase
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run per-spec e2e data setup/teardown phases (see e2e_fixtures.REGISTRY)"

    def add_arguments(self, parser):
        parser.add_argument("--spec", help="Spec file stem, e.g. 'auth' or 'clerk'")
        parser.add_argument("--phase", choices=["setup", "teardown"])
        parser.add_argument("--run-id", default=None, help="Run identifier for scoping")
        parser.add_argument("--list", action="store_true", help="Print the registry")
        parser.add_argument(
            "--all", action="store_true", help="Apply --phase to every registered spec"
        )
        parser.add_argument(
            "--sweep-stale", action="store_true", help="GC abandoned e2e data"
        )
        parser.add_argument("--max-age-hours", type=int, default=6)

    def handle(self, *args, **opts):
        if opts["list"]:
            self.stdout.write("e2e_data registry (spec → declared phases):")
            for spec, entry in sorted(REGISTRY.items()):
                phases = ", ".join(sorted(k for k, v in entry.items() if v)) or "—"
                self.stdout.write(f"  {spec:<26} {phases}")
            return

        run_id = opts["run_id"]

        if opts["sweep_stale"]:
            from api.e2e_fixtures.shared import sweep_stale

            summary = sweep_stale(max_age_hours=opts["max_age_hours"])
            self.stdout.write(f"sweep-stale: {summary}")
            return

        if not opts["phase"]:
            self.stderr.write("error: --phase is required (or use --list/--sweep-stale)")
            return

        if opts["all"]:
            targets = list(REGISTRY.keys())
        else:
            if not opts["spec"]:
                self.stderr.write("error: --spec is required")
                return
            targets = [opts["spec"]]

        for spec in targets:
            fn = get_phase(spec, opts["phase"])
            if fn is None:
                # Not declared = nothing to run; parity by declaration.
                self.stdout.write(f"{spec}/{opts['phase']}: not declared — skipping")
                continue
            if not run_id:
                # Run-scoped teardown/setup always needs a run id. Bulk GC is
                # the --sweep-stale path.
                self.stderr.write("error: --run-id is required")
                return
            summary = fn(run_id)
            self.stdout.write(f"{spec}/{opts['phase']}: {summary or 'ok'}")
