from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0107_decisionentityrelationship_is_inferred_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="importjob",
            name="last_progress_at",
            field=models.DateTimeField(
                blank=True,
                help_text=(
                    "Last time a chunk reported completion/failure. Stall "
                    "detection must use this, not created_at."
                ),
                null=True,
                verbose_name="Last Progress At",
            ),
        ),
        migrations.RunSQL(
            sql=(
                "UPDATE core_importjob "
                "SET last_progress_at = COALESCE(completed_at, created_at) "
                "WHERE last_progress_at IS NULL "
                "AND status IN ('completed', 'partially_completed', 'failed', "
                "'cancelled');"
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
