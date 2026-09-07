from django.db import migrations

# Partial indexes that make the prerequisite-check NULL probes O(1).
#
# The prerequisite check service probes each FTS table with:
#     SELECT EXISTS (SELECT 1 FROM <table> WHERE search_vector IS NULL LIMIT 1)
# On a fully backfilled table this predicate cannot use the GIN index on
# search_vector (it asks about NULLs, not tokens), so it degrades into a
# full sequential scan: measured ~35-70s on core_decision (~10.7M rows)
# and ~1-3s on core_documentextraction. Every cache miss paid this cost,
# and concurrent misses paid it N times (dogpile).
#
# These tiny partial indexes contain ONLY rows whose search_vector is NULL
# (typically zero rows after backfill), so the probe becomes an index
# existence check in microseconds.
#
# WHY a raw psycopg2 connection instead of RunSQL:
#   CREATE INDEX CONCURRENTLY cannot run inside a transaction block. Setting
#   atomic = False stops DJANGO from opening one, but if the migrate command
#   is invoked with the shared connection already in a transaction (persistent
#   connections, entrypoint wrappers, call_command inside atomic, tests), the
#   DDL still fails with InternalError. Running on a dedicated autocommit
#   connection makes this migration self-sufficient: it succeeds regardless
#   of the caller's transaction state.

PARTIAL_INDICES = [
    # table, index name
    ("core_decision", "core_decision_sv_null_idx"),
    ("core_documentextraction", "core_documentextraction_sv_null_idx"),
    ("core_afmentity", "core_afmentity_sv_null_idx"),
    ("core_organization", "core_organization_sv_null_idx"),
    ("core_unit", "core_unit_sv_null_idx"),
    ("core_signer", "core_signer_sv_null_idx"),
    ("companies", "companies_sv_null_idx"),
    ("company_persons", "company_persons_sv_null_idx"),
]


# Statement timeout so a pathological build can't hang the deploy forever.
DDL_TIMEOUT_MS = 20 * 60 * 1000  # 20 minutes


def _run_on_dedicated_connection(statements) -> None:
    """Execute statements on one fresh autocommit connection.

    `statements` is a callable taking a cursor, so generators can run catalog
    lookups (PK column names) on the same connection as the DDL.
    """
    from django.db import connection

    if connection.vendor != "postgresql":
        return

    import psycopg2

    db = connection.settings_dict
    conn = psycopg2.connect(
        dbname=db["NAME"],
        user=db["USER"],
        password=db["PASSWORD"],
        host=db.get("HOST") or None,
        port=db.get("PORT") or None,
    )
    conn.autocommit = True
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"SET statement_timeout = {DDL_TIMEOUT_MS};")
            for sql in statements(cursor):
                cursor.execute(sql)
    finally:
        conn.close()


def _get_pk_column(cursor, table: str) -> str:
    """Look up the table's PK column from the catalog.

    Not all FTS tables use `id`: core_organization/core_unit/core_signer
    have a UUID `uid` PK. Reading it from the catalog keeps this migration
    correct even if a PK is renamed later.
    """
    cursor.execute(
        """
        SELECT a.attname
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indrelid
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(i.indkey)
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname = %s AND i.indisprimary
        """,
        [table],
    )
    row = cursor.fetchone()
    if not row:
        raise RuntimeError(f"No primary key found for table {table}")
    return row[0]


def create_indexes(apps, schema_editor):
    def _statements(cursor):
        for tbl, idx in PARTIAL_INDICES:
            pk = _get_pk_column(cursor, tbl)
            yield (
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx} ON {tbl} "
                f"({pk}) WHERE search_vector IS NULL;"
            )

    _run_on_dedicated_connection(_statements)


def drop_indexes(apps, schema_editor):
    def _statements(cursor):
        for _, idx in PARTIAL_INDICES:
            yield f"DROP INDEX CONCURRENTLY IF EXISTS {idx};"

    _run_on_dedicated_connection(_statements)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0094_user_ai_model_preference_max_tokens"),
    ]

    atomic = False

    operations = [
        migrations.RunPython(create_indexes, reverse_code=drop_indexes),
    ]
