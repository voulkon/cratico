import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0003_customuser_preferred_layout_and_more"),
        ("core", "0001_initial"),  # Make sure core app is migrated
    ]

    operations = [
        migrations.AddField(
            model_name="saveddecision",
            name="decision",
            field=models.ForeignKey(
                null=True,  # Temporarily nullable
                blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="saved_by_users",
                to="core.decision",
                to_field="ada",
            ),
        ),
    ]
