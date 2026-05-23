from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_alter_documentanalysis_provider_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS pg_trgm;",
            reverse_sql="",
        ),
    ]
