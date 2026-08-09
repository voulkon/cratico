"""
Stop persisting ``max_tokens`` in the default notification batch summary
pipeline; scalar budget defaults belong in code
(``pipeline_steps.ai_call.DEFAULT_MAX_TOKENS``), not in rows.

The old 500-token persisted value on the map step was too low: a reasoning
model can spend its whole budget on "thinking" and return empty content
(``content=null`` with ``completion_tokens>0``).  Removing the persisted value
makes the step fall through to the code default (2000), and future tuning of
the default is a code change with no data migration.

Only the stale legacy defaults (map=500, merge=1000) are stripped.  Any value an
operator deliberately set is left untouched.
"""

from django.db import migrations

# step_type -> the legacy default that was persisted by
# ``ai_summary_tasks._get_or_create_default_pipeline``.  Only exact matches are
# removed; anything else is treated as a deliberate operator override.
LEGACY_PERSISTED = {
    "AI_CALL": 500,
    "AGGREGATE": 1000,
}


def stop_persisting_max_tokens(apps, schema_editor):
    PipelineStep = apps.get_model("core", "PipelineStep")

    steps = PipelineStep.objects.filter(
        pipeline__name="notification_batch_summary_v1",
        step_type__in=tuple(LEGACY_PERSISTED),
    )
    for step in steps:
        config = dict(step.config or {})
        if config.get("max_tokens") != LEGACY_PERSISTED[step.step_type]:
            # Either absent (already code-driven) or a deliberate override —
            # leave it alone.
            continue
        config.pop("max_tokens", None)
        step.config = config
        step.save(update_fields=["config"])


def noop(apps, schema_editor):
    """Reverse is a no-op — re-adding a persisted copy of the code default
    would be strictly worse and risks masking future code changes."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0091_diavgeiafeedbackjob_diavgeiafeedbackjobresult_and_more"),
    ]

    operations = [
        migrations.RunPython(stop_persisting_max_tokens, noop),
    ]
