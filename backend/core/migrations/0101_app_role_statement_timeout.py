"""
Set a server-side statement_timeout on the application's PostgreSQL role.

Generic backstop for any future runaway query (postmortem
2026-10-03-document-search-worker-timeout, fix #5). pgbouncer transaction
mode drops connection-startup options, but ``ALTER ROLE ... SET`` persists
the setting in the catalog and applies to every new session of the role —
that is the supported way to give runaway SQL a ceiling in this stack.

- Default: 30 s, overridable via the DB_STATEMENT_TIMEOUT env var
  (e.g. '60s'; '0' disables the ceiling).
- Non-fatal: if the connected role lacks ALTER ROLE permission (e.g. a
  managed/limited DB user), we log a warning with the manual command instead
  of failing the migration.
- No-op on non-PostgreSQL backends (SQLite test runs without PG_TEST).
"""

import os

from django.db import migrations
from loguru import logger


def set_statement_timeout(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    from django.conf import settings

    role = settings.DATABASES["default"].get("USER")
    timeout = os.environ.get("DB_STATEMENT_TIMEOUT", "30s")

    if not role:
        logger.warning(
            "statement_timeout migration skipped: no DB USER configured"
        )
        return
    if timeout.strip().lower() in ("", "0", "0s", "off", "none"):
        return

    quoted_role = role.replace('"', '""')
    sql = f'ALTER ROLE "{quoted_role}" SET statement_timeout = %s'
    try:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(sql, [timeout])
        logger.info(
            f"statement_timeout migration: ALTER ROLE {role} SET statement_timeout = {timeout}"
        )
    except Exception as e:
        logger.warning(
            f"statement_timeout migration could not run (non-fatal): {e}. "
            f'Apply manually with: ALTER ROLE "{role}" SET statement_timeout = \'{timeout}\';'
        )


def unset_statement_timeout(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    from django.conf import settings

    role = settings.DATABASES["default"].get("USER")
    if not role:
        return

    quoted_role = role.replace('"', '""')
    try:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(f'ALTER ROLE "{quoted_role}" RESET statement_timeout')
    except Exception as e:
        logger.warning(
            f"statement_timeout reverse migration could not run (non-fatal): {e}"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0100_clear_self_counterpart_amount_markers"),
    ]

    operations = [
        migrations.RunPython(set_statement_timeout, unset_statement_timeout),
    ]