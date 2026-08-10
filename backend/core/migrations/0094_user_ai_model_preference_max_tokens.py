# Generated manually — adds the per-user ``max_tokens`` preference to
# ``UserAIModelPreference``.  Written by hand to keep the help_text in sync
# with the model field.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0093_stop_persisting_simple_summary_max_tokens"),
    ]

    operations = [
        migrations.AddField(
            model_name="useraimodelpreference",
            name="max_tokens",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="User-set output-token budget for AI pipeline calls. Leave blank to use the code-level default. Clamped to a safe ceiling at call time.",
                null=True,
            ),
        ),
    ]
