from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        # Reference your latest migration
        ("core", "0004_documentanalysis_documentembedding_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE OR REPLACE FUNCTION document_extraction_search_vector_update() RETURNS trigger AS $$
            BEGIN
                NEW.search_vector = to_tsvector('greek', unaccent(COALESCE(NEW.raw_text, '')));
                RETURN NEW;
            END
            $$ LANGUAGE plpgsql;

            DROP TRIGGER IF EXISTS document_extraction_search_vector_update ON core_documentextraction;

            CREATE TRIGGER document_extraction_search_vector_update
            BEFORE INSERT OR UPDATE OF raw_text
            ON core_documentextraction
            FOR EACH ROW
            EXECUTE FUNCTION document_extraction_search_vector_update();
            """,
            reverse_sql="""
            DROP TRIGGER IF EXISTS document_extraction_search_vector_update ON core_documentextraction;
            DROP FUNCTION IF EXISTS document_extraction_search_vector_update();
            """,
        ),
    ]
