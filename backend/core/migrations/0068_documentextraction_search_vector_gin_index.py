# Generated manually on 2026-06-02
# Adds the missing GIN index on core_documentextraction.search_vector.
# The trigger (document_extraction_search_vector_update) already exists
# from migration 0005. Only the index was missing.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0067_decision_search_vector"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE INDEX IF NOT EXISTS core_documentextraction_search_vector_idx
            ON core_documentextraction USING GIN(search_vector);
            """,
            reverse_sql="""
            DROP INDEX IF EXISTS core_documentextraction_search_vector_idx;
            """,
        ),
    ]
