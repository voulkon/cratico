"""
Stop persisting ``max_tokens`` in the single-decision summary pipeline
(``simple_summary_v1``); the batch pipeline was handled in 0092.

The persisted 1000-token value on the AI_CALL step was a legacy default that
now belongs in code (``pipeline_steps.ai_call.DEFAULT_MAX_TOKENS``).  Only an
exact match is stripped; anything else is treated as a deliberate operator
override and left untouched.
"""

from django.db import migrations

LEGACY_PERSISTED_MAX_TOKENS = 1000


def stop_persisting_simple_summary_max_tokens(apps, schema_editor):
    PipelineStep = apps.get_model("core", "PipelineStep")

    steps = PipelineStep.objects.filter(
        pipeline__name="simple_summary_v1",
        step_type="AI_CALL",
    )
    for step in steps:
        config = dict(step.config or {})
        if config.get("max_tokens") != LEGACY_PERSISTED_MAX_TOKENS:
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
        ("core", "0092_stop_persisting_summary_max_tokens"),
    ]

    operations = [
        migrations.RunPython(
            stop_persisting_simple_summary_max_tokens,
            noop,
        ),
    ]
