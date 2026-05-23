from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0007a_add_pg_trgm_extension"),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS unaccent;",
            reverse_sql="",
        ),
    ]
