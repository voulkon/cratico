# Generated migration to remove display_text field

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0044_searchsuggestion"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="searchsuggestion",
            name="display_text",
        ),
    ]
