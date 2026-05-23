from django.db import connection, migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0007b_add_unaccent_extension"),
    ]

    # Only attempt pgvector if we're using PostgreSQL
    operations = []
    if connection.vendor == "postgresql":
        try:
            # Check if pgvector can be created
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM pg_available_extensions WHERE name = 'pgvector'"
                )
                if cursor.fetchone()[0] > 0:
                    operations = [
                        migrations.RunSQL(
                            sql="CREATE EXTENSION IF NOT EXISTS pgvector;",
                            reverse_sql="",
                        ),
                    ]
        except Exception:
            # If there's any error, don't try to create the extension
            pass
