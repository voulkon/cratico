from django.conf import settings
from django.db import connection


class DatabaseStatsService:
    def get_postgres_stats(self):
        with connection.cursor() as cursor:
            # Get DB Size
            cursor.execute(
                "SELECT pg_size_pretty(pg_database_size(current_database()));"
            )
            db_size = cursor.fetchone()[0]

            # Get all user tables to iterate over for exact counts
            cursor.execute(
                """
                SELECT relname, relid
                FROM pg_stat_user_tables;
            """
            )
            table_data = cursor.fetchall()

            tables = []
            for relname, relid in table_data:
                # Get exact count for accuracy (replaces estimated n_live_tup)
                quoted_table = connection.ops.quote_name(relname)
                cursor.execute(
                    f"SELECT count(*) FROM {quoted_table}"
                )  # nosec: B608 - Using Django's quote_name() for identifier safety
                row_count = cursor.fetchone()[0]

                # Get size info
                cursor.execute(
                    f"SELECT pg_total_relation_size({relid}), pg_size_pretty(pg_total_relation_size({relid}))"
                )
                size_bytes, size_pretty = cursor.fetchone()

                tables.append(
                    {
                        "name": relname,
                        "rows": row_count,
                        "size_bytes": size_bytes,
                        "size_pretty": size_pretty,
                    }
                )

            # Sort by size descending
            tables.sort(key=lambda x: x["size_bytes"], reverse=True)

        return {"size": db_size, "tables": tables}

    def get_opensearch_stats(self):
        """Get OpenSearch statistics. Returns None if OpenSearch is disabled."""
        if not settings.INDEX_THE_OPENSEARCH:
            return None

        from core.services.opensearch_service import OpenSearchService

        service = OpenSearchService()
        return service.analyze_index_health()
