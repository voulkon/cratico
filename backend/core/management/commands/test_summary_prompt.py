"""
Iterate on AI summary prompts against real decisions.

Runs the configured summary pipeline synchronously (real API calls, no
Celery) on one or more decisions and prints the rendered prompt, the
per-decision one-liners keyed by ADA, the final merged output, and the
token/cost totals — instant feedback for prompt tuning.

Examples:

    # One-liners only (skip the merge step to save API calls)
    python manage.py test_summary_prompt --ada 9Χ0Ι469Η4Σ-ΧΧΣ --no-merge

    # Custom system prompt from a file, billing to the first superuser
    python manage.py test_summary_prompt \\
        --ada ADA1 --ada ADA2 \\
        --system-prompt-file prompt.txt \\
        --user-email admin@example.com

    # Per-decision pipeline by decision id
    python manage.py test_summary_prompt --decision-id 1304192 \\
        --pipeline simple_summary_v1
"""

import os

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument(
            "--ada",
            action="append",
            default=[],
            metavar="ADA",
            help="Decision ADA to summarize (repeatable)",
        )
        parser.add_argument(
            "--decision-id",
            action="append",
            default=[],
            type=int,
            metavar="ID",
            help="Decision primary key to summarize (repeatable)",
        )
        parser.add_argument(
            "--pipeline",
            default="notification_batch_summary_v1",
            help="Pipeline name (default: notification_batch_summary_v1)",
        )
        parser.add_argument(
            "--system-prompt-file",
            default=None,
            help="Replace the AI_CALL step system_prompt with this file's contents",
        )
        parser.add_argument(
            "--prompt-file",
            default=None,
            help="Replace the AI_CALL step prompt_template with this file's contents",
        )
        parser.add_argument(
            "--user-email",
            default=None,
            help="User for billing attribution (default: first superuser)",
        )
        parser.add_argument(
            "--no-merge",
            action="store_true",
            help="Deactivate AGGREGATE steps while running (saves API calls)",
        )

    def handle(self, *args, **options):
        from core.models.decisions import Decision
        from core.services.pipeline_engine import PipelineContext, PipelineEngine

        adas = options["ada"]
        decision_ids = options["decision_id"]
        if not adas and not decision_ids:
            raise CommandError("Provide --ada and/or --decision-id")

        pipeline_name = options["pipeline"]
        pipeline_def = self._get_pipeline(pipeline_name)

        decisions = []
        if adas:
            found = Decision.objects.filter(ada__in=adas)
            missing = set(adas) - set(found.values_list("ada", flat=True))
            if missing:
                raise CommandError(f"Decisions not found for ADA: {sorted(missing)}")
            decisions.extend(found)
        if decision_ids:
            found = Decision.objects.filter(id__in=decision_ids)
            missing = set(decision_ids) - set(found.values_list("id", flat=True))
            if missing:
                raise CommandError(f"Decisions not found for ids: {sorted(missing)}")
            decisions.extend(found)

        user = self._resolve_user(options["user_email"])

        # Mutated steps with their original values, restored in ``finally``
        # so the pipeline rows are untouched after the command finishes,
        # success or not.
        mutated = []  # [(step, original_config, original_is_active)]

        def _mutate(step, config=None, is_active=None):
            original = (step, dict(step.config or {}), step.is_active)
            if config is not None:
                step.config = config
                step.save(update_fields=["config"])
            if is_active is not None:
                step.is_active = is_active
                step.save(update_fields=["is_active"])
            mutated.append(original)

        for step in pipeline_def.steps.filter(step_type="AI_CALL"):
            config = dict(step.config or {})
            if options["system_prompt_file"]:
                config["system_prompt"] = self._read_file(
                    options["system_prompt_file"]
                )
            if options["prompt_file"]:
                config["prompt_template"] = self._read_file(options["prompt_file"])
            if config != (step.config or {}):
                _mutate(step, config=config)

        # --no-merge: deactivate AGGREGATE steps for this run only
        if options["no_merge"]:
            for step in pipeline_def.steps.filter(step_type="AGGREGATE", is_active=True):
                _mutate(step, is_active=False)

        try:
            context = PipelineContext(
                decisions=decisions,
                batch=None,
                user=user,
            )
            engine = PipelineEngine()
            run = engine.run(
                pipeline_def,
                context,
                trigger="prompt_iteration",
                trigger_ref="test_summary_prompt",
            )
        finally:
            for step, original_config, original_is_active in mutated:
                step.config = original_config
                step.is_active = original_is_active
                step.save(update_fields=["config", "is_active"])

        self._report(pipeline_def, decisions, context, run)

        # JSON result line — call_command() consumers (the env-gated test)
        # parse this; BaseCommand.execute() echoes it to stdout as-is.
        import json

        return json.dumps(
            {
                "run_id": run.id,
                "status": run.status,
                "total_input_tokens": run.total_input_tokens,
                "total_output_tokens": run.total_output_tokens,
                "total_cost_usd": str(run.total_cost_usd),
                "per_item_outputs": dict(context.per_item_outputs),
                "steps_output": dict(context.steps_output),
                "error": run.error_message,
            }
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_pipeline(self, name):
        """Resolve the pipeline definition, seeding the known defaults."""
        if name == "notification_batch_summary_v1":
            from notifications.tasks.ai_summary_tasks import (
                _get_or_create_default_pipeline,
            )

            return _get_or_create_default_pipeline()
        if name == "simple_summary_v1":
            from core.tasks.tasks_decision_ai import (
                _get_or_create_simple_summary_pipeline,
            )

            return _get_or_create_simple_summary_pipeline()

        from core.models.pipeline import PipelineDefinition

        pipeline_def = PipelineDefinition.objects.filter(name=name).first()
        if pipeline_def is None:
            raise CommandError(
                f"Pipeline '{name}' not found (known defaults: "
                f"notification_batch_summary_v1, simple_summary_v1)"
            )
        return pipeline_def

    def _resolve_user(self, email):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        if email:
            user = User.objects.filter(email=email).first()
            if user is None:
                raise CommandError(f"No user with email {email}")
            return user
        user = User.objects.filter(is_superuser=True).order_by("id").first()
        if user is None:
            raise CommandError("No superuser found — pass --user-email")
        return user

    def _read_file(self, path):
        if not os.path.isfile(path):
            raise CommandError(f"File not found: {path}")
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def _report(self, pipeline_def, decisions, context, run):
        """Print the iteration report: prompts, one-liners, merge, cost."""
        from core.models.pipeline import RunStatus

        self.stdout.write(self.style.MIGRATE_HEADING(f"Pipeline: {pipeline_def.name}"))
        for decision in decisions:
            self.stdout.write(f"  decision {decision.pk} ada={decision.ada}")

        # Rendered prompts are persisted on the AI_CALL step runs
        for step_run in run.step_runs.order_by("order"):
            if step_run.input_preview:
                self.stdout.write(self.style.MIGRATE_HEADING(
                    f"Rendered prompt (step {step_run.order}):"
                ))
                self.stdout.write(step_run.input_preview)

        self.stdout.write(self.style.MIGRATE_HEADING("Per-decision one-liners:"))
        per_item = context.per_item_outputs
        if isinstance(per_item, dict) and per_item:
            by_pk = {str(d.pk): d for d in decisions}
            for item_id, output in per_item.items():
                ada = by_pk[item_id].ada if item_id in by_pk else item_id
                self.stdout.write(f"  [{ada}] {output}")
        else:
            self.stdout.write("  (no per-item outputs — single-mode pipeline)")

        if context.steps_output:
            final_order = max(context.steps_output.keys())
            self.stdout.write(self.style.MIGRATE_HEADING("Merged output:"))
            self.stdout.write(context.steps_output[final_order] or "(empty)")

        self.stdout.write(self.style.MIGRATE_HEADING("Run:"))
        self.stdout.write(f"  status: {run.status} (expected {RunStatus.COMPLETED})")
        self.stdout.write(
            f"  tokens: {run.total_input_tokens} in / {run.total_output_tokens} out"
        )
        self.stdout.write(f"  cost: ${run.total_cost_usd}")
        if run.error_message:
            self.stdout.write(self.style.ERROR(f"  error: {run.error_message}"))
