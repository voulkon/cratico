from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0013_notification_preference"),
    ]

    operations = [
        migrations.AddField(
            model_name="notificationbatch",
            name="ai_summary_manual_override",
            field=models.BooleanField(
                default=False,
                help_text="Whether an explicit user override triggered this summary",
                verbose_name="AI summary manual override",
            ),
        ),
        migrations.AddField(
            model_name="notificationbatch",
            name="ai_summary_skip_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("USER_DISABLED", "User-level AI summaries disabled"),
                    (
                        "SUBSCRIPTION_DISABLED",
                        "Subscription-level AI summaries disabled",
                    ),
                    ("DAILY_CEILING", "Daily summary ceiling reached"),
                    ("BUDGET_EXHAUSTED", "AI budget exhausted"),
                    ("NO_DECISIONS", "No decisions to summarize"),
                    ("PROVIDER_ERROR", "Provider error"),
                ],
                help_text="Machine-readable reason when the summary was skipped",
                max_length=32,
                null=True,
                verbose_name="AI summary skip reason",
            ),
        ),
        migrations.AlterField(
            model_name="notificationbatch",
            name="ai_summary_status",
            field=models.CharField(
                default="PENDING",
                help_text="PENDING / RUNNING / COMPLETED / PARTIAL / FAILED / SKIPPED",
                max_length=20,
                verbose_name="AI summary status",
            ),
        ),
    ]
