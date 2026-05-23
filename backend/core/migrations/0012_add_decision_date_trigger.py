from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        (
            "core",
            "0011_remove_decisionamountkae_core_decisi_decisio_21023b_idx_and_more",
        ),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE OR REPLACE FUNCTION update_decision_date_parts()
            RETURNS TRIGGER AS $$
            BEGIN
                IF NEW.issue_date IS NOT NULL THEN
                    NEW.issue_date_day := DATE(NEW.issue_date);
                    NEW.issue_date_month := DATE_TRUNC('month', NEW.issue_date)::date;
                    NEW.issue_date_year := EXTRACT(year FROM NEW.issue_date);
                ELSE
                    NEW.issue_date_day := NULL;
                    NEW.issue_date_month := NULL;
                    NEW.issue_date_year := NULL;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """,
            reverse_sql="""
            DROP FUNCTION IF EXISTS update_decision_date_parts() CASCADE;
            """,
        ),
        migrations.RunSQL(
            sql="""
            CREATE TRIGGER trg_update_decision_date_parts
            BEFORE INSERT OR UPDATE OF issue_date ON core_decision
            FOR EACH ROW
            EXECUTE FUNCTION update_decision_date_parts();
            """,
            reverse_sql="""
            DROP TRIGGER IF EXISTS trg_update_decision_date_parts ON core_decision;
            """,
        ),
    ]
