"""
Fix the decision date-parts trigger to use Europe/Athens timezone instead of
bare DATE() which returns the UTC date.

Migration 0012 created update_decision_date_parts() using DATE(NEW.issue_date),
which gives the UTC calendar date.  Diavgeia issue-dates are midnight Athens
time, so the UTC representation is 22:00 the *previous* day — meaning every
record inserted or updated after migration 0012 has issue_date_day set one day
early.

This migration replaces the trigger function so all three columns are derived
from the Athens-local timestamp, matching what Decision.save() and the
recompute_issue_date_fields management command do.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0065_decision_publish_date_day"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
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
            # Restore the broken UTC version (allows rolling back this migration)
            reverse_sql="""
            CREATE OR REPLACE FUNCTION update_decision_date_parts()
            RETURNS TRIGGER AS $$
            BEGIN
                IF NEW.issue_date IS NOT NULL THEN
                    NEW.issue_date_day   := DATE(NEW.issue_date);
                    NEW.issue_date_month := DATE_TRUNC('month', NEW.issue_date)::date;
                    NEW.issue_date_year  := EXTRACT(year FROM NEW.issue_date);
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
