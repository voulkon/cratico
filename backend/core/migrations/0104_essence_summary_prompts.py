"""
Switch the seeded AI summary pipelines to essence-focused prompts.

Existing ``PipelineStep.config`` rows are updated in place — the
``get_or_create`` seed helpers only apply defaults on creation, so fresh
configs alone would never change live pipelines.  The essence prompts
produce:

- ``notification_batch_summary_v1`` AI_CALL (order 2): ONE Greek sentence
  per decision (what was decided, counterpart, amount) — the per-decision
  one-liner surfaced as email bullets.
- ``notification_batch_summary_v1`` AGGREGATE (order 3): 2-4 sentence
  Greek overview synthesized from the one-liners, no new facts.
- ``simple_summary_v1`` AI_CALL (order 2): 2-3 sentence Greek essence
  summary.

The prompt texts are inlined here (not imported) because migrations are
historical records.  They mirror the seeds in
``core.ai_services.summary_prompts`` at the time of this migration.

Mirrors the 0092 precedent: only rows whose ``system_prompt`` still equals
the original seed value are replaced; anything else is treated as a
deliberate operator override and left untouched.
"""

from django.db import migrations

BATCH_MAP_SYSTEM_PROMPT = (
    "You are a legal analyst for Greek government decisions (published on a platform called Διαύγεια). "
    "Reply with ONE sentence (max ~25 words) in Greek capturing only the "
    "operative outcome: what was decided/approved, the counterpart "
    "(contractor/consultant/person) if any, and the amount if any. "
    "Ignore procedural content (who convened, where, when, attendees). "
    "Output only the sentence — no preamble, no quotes."
)

BATCH_MERGE_SYSTEM_PROMPT = (
    "You are a legal analyst for Greek government decisions (published on a platform called Διαύγεια). "
    "Synthesize the provided one-sentence decision summaries into a "
    "coherent overview of 2-4 sentences in Greek. Group related decisions "
    "when it helps, but never invent facts that are not in the summaries. "
    "Output only the overview text — no preamble, no quotes."
)

DECISION_ESSENCE_SYSTEM_PROMPT = (
    "You are a legal analyst for Greek government decisions (published on a platform called Διαύγεια). "
    "Summarize this decision in 2-3 sentences in Greek, capturing only the "
    "essence: what was decided or approved, the counterpart "
    "(contractor/consultant/person) if any, and the amount if any. "
    "Ignore procedural narrative (who convened, where, when, attendees). "
    "Output only the summary — no preamble, no quotes."
)

# pipeline name -> [(step_type, order, legacy seed system_prompt, new system_prompt)]
PROMPT_UPDATES = {
    "notification_batch_summary_v1": [
        (
            "AI_CALL",
            2,
            "You are a legal analyst. Summarize the key points of this government decision concisely.",
            BATCH_MAP_SYSTEM_PROMPT,
        ),
        (
            "AGGREGATE",
            3,
            "You are a legal analyst. Synthesize the provided decision summaries into a single coherent overview.",
            BATCH_MERGE_SYSTEM_PROMPT,
        ),
    ],
    "simple_summary_v1": [
        (
            "AI_CALL",
            2,
            (
                "You are a legal analyst specializing in Greek government decisions (published on a platform called Διαύγεια). "
                "Summarize the decision concisely in the same language as the original text. "
                "Include: (1) who issued it, (2) what was decided, (3) key financial amounts if any, "
                "(4) the legal basis referenced. Keep the summary to 3-5 short paragraphs."
            ),
            DECISION_ESSENCE_SYSTEM_PROMPT,
        ),
    ],
}


def update_summary_prompts(apps, schema_editor):
    PipelineStep = apps.get_model("core", "PipelineStep")

    for pipeline_name, updates in PROMPT_UPDATES.items():
        for step_type, order, legacy_prompt, new_prompt in updates:
            steps = PipelineStep.objects.filter(
                pipeline__name=pipeline_name,
                step_type=step_type,
                order=order,
            )
            for step in steps:
                config = dict(step.config or {})
                if config.get("system_prompt") != legacy_prompt:
                    # Absent or a deliberate operator override — leave alone.
                    continue
                config["system_prompt"] = new_prompt
                step.config = config
                step.save(update_fields=["config"])


def noop(apps, schema_editor):
    """Reverse is a no-op — restoring the old generic prompts would undo the
    feature this migration ships."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0103_alter_importjob_import_type"),
    ]

    operations = [
        migrations.RunPython(update_summary_prompts, noop),
    ]
