# Generated data migration to populate decision_issue_date field

from django.db import migrations


def populate_decision_issue_date_forward(apps, schema_editor):
    """Populate decision_issue_date field for existing DecisionHealthCheck records"""
    DecisionHealthCheck = apps.get_model("core", "DecisionHealthCheck")

    updated_count = 0
    for health_check in DecisionHealthCheck.objects.select_related(
        "decision"
    ).iterator():
        if (
            health_check.decision
            and health_check.decision.issue_date
            and not health_check.decision_issue_date
        ):
            health_check.decision_issue_date = health_check.decision.issue_date
            health_check.save(update_fields=["decision_issue_date"])
            updated_count += 1

    print(f"Populated decision_issue_date for {updated_count} health check records")


def populate_decision_issue_date_reverse(apps, schema_editor):
    """Reverse migration - clear decision_issue_date field"""
    DecisionHealthCheck = apps.get_model("core", "DecisionHealthCheck")
    DecisionHealthCheck.objects.update(decision_issue_date=None)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0026_decisionhealthcheck_decisionhealthsummary"),
    ]

    operations = [
        migrations.RunPython(
            populate_decision_issue_date_forward, populate_decision_issue_date_reverse
        ),
    ]
