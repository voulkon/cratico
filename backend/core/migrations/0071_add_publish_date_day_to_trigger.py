"""
Add publish_date_day computation to the decision date-parts trigger.

Migration 0066 added Athens-timezone handling for issue_date_day/month/year
but the trigger never handled publish_date_day (added in 0065).

publish_date_day mirrors the Diavgeia API's from_date / to_date parameters and
must use the same Europe/Athens timezone conversion that issue_date already uses,
so that update_decision_date_parts() stays in sync with Decision.save().
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0070_add_legal_document_type_title"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE OR REPLACE FUNCTION update_decision_date_parts()
            RETURNS TRIGGER AS $$
            BEGIN
                -- issue_date → issue_date_day / issue_date_month / issue_date_year
                IF NEW.issue_date IS NOT NULL THEN
                    NEW.issue_date_day   := (NEW.issue_date AT TIME ZONE 'Europe/Athens')::date;
                    NEW.issue_date_month := DATE_TRUNC(
                                               'month',
                                               NEW.issue_date AT TIME ZONE 'Europe/Athens'
                                           )::date;
                    NEW.issue_date_year  := EXTRACT(
                                               year FROM
                                               (NEW.issue_date AT TIME ZONE 'Europe/Athens')
                                           )::integer;
                ELSE
                    NEW.issue_date_day   := NULL;
                    NEW.issue_date_month := NULL;
                    NEW.issue_date_year  := NULL;
                END IF;

                -- publish_timestamp → publish_date_day
                IF NEW.publish_timestamp IS NOT NULL THEN
                    NEW.publish_date_day := (NEW.publish_timestamp AT TIME ZONE 'Europe/Athens')::date;
                ELSE
                    NEW.publish_date_day := NULL;
                END IF;

                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """,
            reverse_sql="""
            CREATE OR REPLACE FUNCTION update_decision_date_parts()
            RETURNS TRIGGER AS $$
            BEGIN
                IF NEW.issue_date IS NOT NULL THEN
                    NEW.issue_date_day   := (NEW.issue_date AT TIME ZONE 'Europe/Athens')::date;
                    NEW.issue_date_month := DATE_TRUNC(
                                               'month',
                                               NEW.issue_date AT TIME ZONE 'Europe/Athens'
                                           )::date;
                    NEW.issue_date_year  := EXTRACT(
                                               year FROM
                                               (NEW.issue_date AT TIME ZONE 'Europe/Athens')
                                           )::integer;
                ELSE
                    NEW.issue_date_day   := NULL;
                    NEW.issue_date_month := NULL;
                    NEW.issue_date_year  := NULL;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """,
        ),
    ]
