# Generated manually to fix JSONB array handling in search vector trigger

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0059_afmscoringconfig_created_at_and_more"),
    ]

    operations = [
        # Fix companies search vector trigger to handle JSONB arrays correctly
        migrations.RunSQL(
            sql="""
            CREATE OR REPLACE FUNCTION companies_search_vector_update() RETURNS trigger AS $$
            BEGIN
                NEW.search_vector = to_tsvector('greek', unaccent(
                    COALESCE(NEW.co_name_el, '') || ' ' ||
                    COALESCE((SELECT string_agg(value, ' ') FROM jsonb_array_elements_text(NEW.co_names_en)), '') || ' ' ||
                    COALESCE((SELECT string_agg(value, ' ') FROM jsonb_array_elements_text(NEW.co_titles_el)), '') || ' ' ||
                    COALESCE((SELECT string_agg(value, ' ') FROM jsonb_array_elements_text(NEW.co_titles_en)), '')
                ));
                RETURN NEW;
            END
            $$ LANGUAGE plpgsql;
            """,
            reverse_sql="""
            -- Revert to broken version (for rollback)
            CREATE OR REPLACE FUNCTION companies_search_vector_update() RETURNS trigger AS $$
            BEGIN
                NEW.search_vector = to_tsvector('greek', unaccent(
                    COALESCE(NEW.co_name_el, '') || ' ' ||
                    COALESCE(array_to_string(NEW.co_names_en, ' '), '') || ' ' ||
                    COALESCE(array_to_string(NEW.co_titles_el, ' '), '') || ' ' ||
                    COALESCE(array_to_string(NEW.co_titles_en, ' '), '')
                ));
                RETURN NEW;
            END
            $$ LANGUAGE plpgsql;
            """,
        ),
    ]
