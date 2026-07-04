# Generated manually on 2026-06-02

import django.contrib.postgres.search
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0066_fix_decision_date_trigger_timezone"),
    ]

    operations = [
        # Add the search_vector column to core_decision
        migrations.AddField(
            model_name="decision",
            name="search_vector",
            field=django.contrib.postgres.search.SearchVectorField(
                blank=True, null=True
            ),
        ),
        # Trigger and GIN index for decision subject FTS
        migrations.RunSQL(
            sql="""
            CREATE OR REPLACE FUNCTION decision_search_vector_update() RETURNS trigger AS $$
            BEGIN
                NEW.search_vector = to_tsvector('greek', unaccent(
                    COALESCE(NEW.subject, '')
                ));
                RETURN NEW;
            END
            $$ LANGUAGE plpgsql;

            DROP TRIGGER IF EXISTS decision_search_vector_update ON core_decision;

            CREATE TRIGGER decision_search_vector_update
            BEFORE INSERT OR UPDATE OF subject
            ON core_decision
            FOR EACH ROW
            EXECUTE FUNCTION decision_search_vector_update();

            CREATE INDEX IF NOT EXISTS core_decision_search_vector_idx
            ON core_decision USING GIN(search_vector);
            """,
            reverse_sql="""
            DROP INDEX IF EXISTS core_decision_search_vector_idx;
            DROP TRIGGER IF EXISTS decision_search_vector_update ON core_decision;
            DROP FUNCTION IF EXISTS decision_search_vector_update();
            """,
        ),
    ]
