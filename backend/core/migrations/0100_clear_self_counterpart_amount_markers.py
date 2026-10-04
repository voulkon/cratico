from django.db import migrations


def clear_self_counterpart_markers(apps, schema_editor):
    """
    Un-flag amounts marked ``invalid_amount_reason = "self_as_counterpart"``.

    The self-as-counterpart variant is decision-level, not an amount problem:
    the amount may be perfectly well-formed (the counterpart is what is
    broken/unknown).  Marking every amount unusable — the previous treatment —
    hid amounts we actually believe, so legacy markers are cleared and the
    rows return to every monetary aggregation.  The counterpart issue itself
    is exposed by the decision detail API (``has_self_counterpart``).
    """
    DecisionAmountField = apps.get_model("core", "DecisionAmountField")
    DecisionAmountField.objects.filter(
        invalid_amount_reason="self_as_counterpart"
    ).update(
        invalid_amount_reason=None,
        invalid_amount_value=None,
        invalid_amount_flagged_at=None,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0099_amountcorrectionjob_mode_max_amount_flagged"),
    ]

    operations = [
        migrations.RunPython(
            clear_self_counterpart_markers,
            migrations.RunPython.noop,
        ),
    ]
