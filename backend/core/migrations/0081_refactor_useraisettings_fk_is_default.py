# Generated manually — refactor UserAISettings OneToOne → ForeignKey with is_default

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def mark_existing_as_default(apps, schema_editor):
    """Existing rows are the sole row per user (OneToOne) — set is_default=True."""
    UserAISettings = apps.get_model("core", "UserAISettings")
    UserAISettings.objects.all().update(is_default=True)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0080_decisionaianalysis"),
    ]

    operations = [
        # 1. Add new nullable fields first (no constraint yet)
        migrations.AddField(
            model_name="UserAISettings",
            name="label",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Optional human-friendly name to distinguish multiple keys.",
                max_length=100,
            ),
        ),
        migrations.AddField(
            model_name="UserAISettings",
            name="is_default",
            field=models.BooleanField(
                default=False,
                help_text="The default row is used for key resolution and billing. "
                "At most one row per user may be the default.",
            ),
        ),
        # 2. Data migration — mark existing rows as default
        migrations.RunPython(mark_existing_as_default, migrations.RunPython.noop),
        # 3. Drop the unique constraint from the old OneToOne (Django creates one on the FK column)
        migrations.AlterField(
            model_name="UserAISettings",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="ai_settings",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # 4. Add partial unique constraint on (user, is_default=True)
        migrations.AddConstraint(
            model_name="UserAISettings",
            constraint=models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_default=True),
                name="unique_default_ai_settings_per_user",
            ),
        ),
    ]
