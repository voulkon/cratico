"""
Warm the per-decision one-liner cache (``DecisionOneLiner``) for existing
decisions.

Enqueues ``generate_decision_one_liner`` per decision (real API calls when
the cache misses — billing goes to the resolved user).  By default decisions
without cached extraction text are skipped; pass ``--with-extraction`` to
also trigger extraction for them.

Examples:

    # Warm a date window (ops warm-up)
    python manage.py backfill_one_liners --since 2026-09-01 --until 2026-09-30 --limit 500

    # Specific decisions (repeatable), forcing fresh attempts
    python manage.py backfill_one_liners --ada 9Χ0Ι469Η4Σ-ΧΧΣ --decision-id 1304192 --force

    # Also extract decisions that have no cached text yet
    python manage.py backfill_one_liners --since 2026-10-01 --with-extraction
"""

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument(
            "--ada",
            action="append",
            default=[],
            metavar="ADA",
            help="Decision ADA to warm (repeatable)",
        )
        parser.add_argument(
            "--decision-id",
            action="append",
            default=[],
            type=int,
            metavar="ID",
            help="Decision primary key to warm (repeatable)",
        )
        parser.add_argument(
            "--since",
            default=None,
            metavar="YYYY-MM-DD",
            help="Only decisions with issue_date_day >= this date",
        )
        parser.add_argument(
            "--until",
            default=None,
            metavar="YYYY-MM-DD",
            help="Only decisions with issue_date_day <= this date",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Cap the number of decisions processed",
        )
        parser.add_argument(
            "--with-extraction",
            action="store_true",
            help="Also process decisions missing cached text (triggers "
            "extraction inside the task). Default: skip them.",
        )
        parser.add_argument(
            "--user-email",
            default=None,
            help="User for billing attribution (default: first superuser)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force fresh attempts even when a completed one-liner exists",
        )

    def handle(self, *args, **options):
        from django.contrib.auth import get_user_model
        from django.db.models import Q

        from core.models.decisions import Decision

        User = get_user_model()

        adas = options["ada"]
        decision_ids = options["decision_id"]
        if not adas and not decision_ids and not (options["since"] or options["until"]):
            raise CommandError(
                "Provide --ada/--decision-id and/or a --since/--until window"
            )

        # ── Resolve the billing user once ─────────────────────────────
        email = options["user_email"]
        if email:
            user = User.objects.filter(email=email).first()
            if user is None:
                raise CommandError(f"No user with email {email}")
        else:
            user = User.objects.filter(is_superuser=True).order_by("id").first()
            if user is None:
                raise CommandError("No superuser found — pass --user-email")

        # ── Resolve the target queryset ───────────────────────────────
        decisions = Decision.objects.select_related("text_extraction")
        missing = []
        if adas or decision_ids:
            decisions = decisions.filter(
                Q(ada__in=adas) | Q(id__in=decision_ids)
            )
            found_ids = set(decisions.values_list("id", flat=True))
            missing_adas = set(adas) - set(
                Decision.objects.filter(ada__in=adas).values_list("ada", flat=True)
            )
            found_decision_ids = set(
                Decision.objects.filter(id__in=decision_ids).values_list(
                    "id", flat=True
                )
            )
            missing_ids = set(decision_ids) - found_decision_ids
            missing = sorted(missing_adas) + [f"id:{i}" for i in missing_ids]
            if not found_ids:
                raise CommandError(f"No decisions found for: {missing}")

        if options["since"]:
            since = self._parse_date(options["since"])
            decisions = decisions.filter(issue_date_day__gte=since)
        if options["until"]:
            until = self._parse_date(options["until"])
            decisions = decisions.filter(issue_date_day__lte=until)

        if options["limit"]:
            decisions = decisions[: options["limit"]]

        # ── Dispatch ──────────────────────────────────────────────────
        from core.tasks.tasks_decision_ai import generate_decision_one_liner

        dispatched = 0
        skipped_no_extraction = 0
        for decision in decisions.iterator():
            # getattr (not attribute access): the reverse OneToOne raises
            # RelatedObjectDoesNotExist when no extraction row exists.
            extraction = getattr(decision, "text_extraction", None)
            if not (extraction and extraction.raw_text) and not options[
                "with_extraction"
            ]:
                skipped_no_extraction += 1
                continue
            generate_decision_one_liner.delay(
                decision_id=decision.id,
                user_id=user.id,
                force=options["force"],
            )
            dispatched += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"backfill_one_liners: dispatched={dispatched} "
                f"skipped_no_extraction={skipped_no_extraction} "
                f"missing={missing or 'none'} "
                f"billed_to_user={user.email} force={options['force']}"
            )
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _parse_date(self, value):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            raise CommandError(f"Invalid date {value!r} (expected YYYY-MM-DD)")
