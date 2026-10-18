"""
Enable the shared per-decision one-liner cache on the seeded batch pipeline.

The ``notification_batch_summary_v1`` AI_CALL map step gains:
    "cache_one_liners": True,
    "prompt_kind": "batch_one_liner"

so existing installs behave like fresh seeds: map-mode AI calls read/write
the ``DecisionOneLiner`` cache and identical
(decision × extraction × generation-circumstances) pairs are never billed
twice.

Fresh installs get the same keys from the seed function
(``notifications.tasks.ai_summary_tasks._get_or_create_default_pipeline``).

Legacy-guard: only rows whose config lacks BOTH keys are updated — an
operator who deliberately disabled the cache (or renamed the lineage) is
never overwritten.
"""

from django.db import migrations

# Inlined (not imported) — migrations are historical records.  Keep in sync
# with core.ai_services.summary_prompts constants.
CACHE_ONE_LINERS_KEY = "cache_one_liners"
PROMPT_KIND_KEY = "prompt_kind"
CACHE_ONE_LINERS_VALUE = True
BATCH_ONE_LINER_PROMPT_KIND = "batch_one_liner"


def enable_one_liner_cache(apps, schema_editor):
    PipelineStep = apps.get_model("core", "PipelineStep")

    steps = PipelineStep.objects.filter(
        pipeline__name="notification_batch_summary_v1",
        step_type="AI_CALL",
    )
    for step in steps:
        config = dict(step.config or {})
        if CACHE_ONE_LINERS_KEY in config or PROMPT_KIND_KEY in config:
            # Already flagged (or deliberately renamed) — leave alone.
            continue
        config[CACHE_ONE_LINERS_KEY] = CACHE_ONE_LINERS_VALUE
        config[PROMPT_KIND_KEY] = BATCH_ONE_LINER_PROMPT_KIND
        step.config = config
        step.save(update_fields=["config"])


def noop(apps, schema_editor):
    """Reverse is a no-op — cached one-liners stay valid history."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0105_onelinerconfig_decisiononeliner"),
    ]

    operations = [
        migrations.RunPython(enable_one_liner_cache, noop),
    ]
