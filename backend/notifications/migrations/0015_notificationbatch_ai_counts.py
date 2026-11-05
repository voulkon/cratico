from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0014_notificationbatch_ai_summary_reason"),
    ]

    operations = [
        migrations.AddField(
            model_name="notificationbatch",
            name="ai_summary_cached_count",
            field=models.IntegerField(
                default=0, help_text="Decisions reused from the shared one-liner cache"
            ),
        ),
        migrations.AddField(
            model_name="notificationbatch",
            name="ai_summary_new_count",
            field=models.IntegerField(
                default=0,
                help_text="Uncached decisions that required a provider call in this run",
            ),
        ),
    ]
