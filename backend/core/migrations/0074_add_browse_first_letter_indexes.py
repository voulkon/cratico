# Generated manually on 2026-06-26
# Adds first-letter functional indexes for the Browse API.
# Uses unaccent() so that accented letters (Ά, Ί, Ύ etc.) collapse
# to their base form (Α, Ι, Υ) — i.e. letter=Α matches both "Αθήνα" and "Άργος".
# Indexes store precomputed UPPER(immutable_unaccent(LEFT(field,1))) on disk.
#
# NOTE: PostgreSQL's built-in unaccent(text) is only STABLE (it depends on the
# unaccent dictionary), so it cannot be used directly in a functional index.
# We wrap it in an IMMUTABLE SQL function so the planner accepts it in indexes.
# The same wrapper MUST be used in browse_service.py queries so the index is hit.
# The unaccent extension itself is created in 0007b_add_unaccent_extension.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0073_add_import_type_to_importjob"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            -- IMMUTABLE wrapper around unaccent() so it can be used in indexes.
            -- Safe because we never change the unaccent dictionary at runtime.
            CREATE OR REPLACE FUNCTION immutable_unaccent(input text)
            RETURNS text
            LANGUAGE SQL
            IMMUTABLE
            AS $$ SELECT public.unaccent($1) $$;

            CREATE INDEX IF NOT EXISTS idx_browse_org_first_letter
            ON core_organization (UPPER(immutable_unaccent(LEFT(label, 1))));

            CREATE INDEX IF NOT EXISTS idx_browse_unit_first_letter
            ON core_unit (UPPER(immutable_unaccent(LEFT(label, 1))));

            CREATE INDEX IF NOT EXISTS idx_browse_signer_first_letter
            ON core_signer (UPPER(immutable_unaccent(LEFT(last_name, 1))));

            CREATE INDEX IF NOT EXISTS idx_browse_company_first_letter
            ON companies (UPPER(immutable_unaccent(LEFT(co_name_el, 1))));

            CREATE INDEX IF NOT EXISTS idx_browse_companyperson_first_letter
            ON company_persons (UPPER(immutable_unaccent(LEFT(person_name, 1))));

            CREATE INDEX IF NOT EXISTS idx_browse_afmentity_first_letter
            ON core_afmentity (UPPER(immutable_unaccent(LEFT(name, 1))));
            """,
            reverse_sql="""
            DROP INDEX IF EXISTS idx_browse_org_first_letter;
            DROP INDEX IF EXISTS idx_browse_unit_first_letter;
            DROP INDEX IF EXISTS idx_browse_signer_first_letter;
            DROP INDEX IF EXISTS idx_browse_company_first_letter;
            DROP INDEX IF EXISTS idx_browse_companyperson_first_letter;
            DROP INDEX IF EXISTS idx_browse_afmentity_first_letter;
            DROP FUNCTION IF EXISTS immutable_unaccent(text);
            """,
        ),
    ]
