import csv
import json
from statistics import mean
from django.core.management.base import BaseCommand
from silk.models import Request, SQLQuery


class Command(BaseCommand):
    help = 'Export Django Silk performance data to CSV or analytical JSON'

    def add_arguments(self, parser):
        parser.add_argument(
            '--format',
            type=str,
            choices=['csv', 'json'],
            default='csv',
            help='The output format for the exported data (csv or json)'
        )
        parser.add_argument(
            '--output',
            type=str,
            default=None,
            help='Custom output file name/path'
        )
        parser.add_argument(
            '--omit-queries',
            action='store_true',
            default=False,
            help='Omit SQL query details from the output (reduces file size)'
        )
        parser.add_argument(
            '--omit-ids',
            action='store_true',
            default=False,
            help='Omit request IDs from the output'
        )
        parser.add_argument(
            '--compact',
            action='store_true',
            default=False,
            help='Use compact JSON (no indentation, shorter keys)'
        )
        parser.add_argument(
            '--group-by-path',
            action='store_true',
            default=False,
            help='Group requests by path with aggregated stats (JSON only)'
        )
        parser.add_argument(
            '--include-response',
            action='store_true',
            default=False,
            help='Include response body in the output'
        )
        parser.add_argument(
            '--lite',
            action='store_true',
            default=False,
            help='Lite mode: only export path, timestamp, total_duration_ms, '
                 'sql_query_count, and response body. Lists in response bodies '
                 'are truncated (JSON only, implies --group-by-path and --include-response)'
        )

    def handle(self, *args, **options):
        file_format = options['format']
        output_file = options['output']
        omit_queries = options['omit_queries']
        omit_ids = options['omit_ids']
        compact = options['compact']
        group_by_path = options['group_by_path']
        include_response = options['include_response']
        lite = options['lite']

        # Lite mode implies JSON, group-by-path, include-response, omit-queries
        if lite:
            if file_format == 'csv':
                self.stdout.write(self.style.WARNING(
                    "Lite mode is only supported with --format json. "
                    "Switching to JSON."
                ))
                file_format = 'json'
            group_by_path = True
            include_response = True
            omit_queries = True
            omit_ids = True

        requests = Request.objects.all().order_by('-start_time')

        if not requests.exists():
            self.stdout.write(self.style.WARNING("No Silk data found to export."))
            return

        if file_format == 'csv':
            filename = output_file or 'silk_export.csv'
            self.export_to_csv(requests, filename, omit_ids)
        elif file_format == 'json':
            filename = output_file or 'silk_analytics_export.json'
            self.export_to_json(requests, filename, omit_queries, omit_ids,
                                compact, group_by_path, include_response,
                                lite)

        self.stdout.write(self.style.SUCCESS(
            f"Successfully exported Silk data to {filename}"
        ))

    def export_to_csv(self, requests, filename, omit_ids):
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            headers = ['Request ID', 'Path', 'Method', 'Status',
                       'Total Time (ms)', 'DB Time (ms)', 'SQL Query Count']
            if omit_ids:
                headers = headers[1:]  # remove 'Request ID'

            writer.writerow(headers)

            for r in requests:
                row = [
                    r.id, r.path, r.method,
                    r.response.status_code if r.response else None,
                    r.time_taken, r.meta_time_spent_queries, r.num_sql_queries
                ]
                if omit_ids:
                    row = row[1:]
                writer.writerow(row)

    def _build_request_entry(self, r, omit_queries, omit_ids, include_response,
                              is_grouped=False, lite=False):
        """Build a single request entry dict, optionally including queries/response."""
        entry = {}

        if not omit_ids:
            entry['request_id'] = r.id

        meta = {
            'status_code': r.response.status_code if r.response else None,
            'timestamp': r.start_time.isoformat() if r.start_time else None,
        }
        # Only include path/method at request level when not grouped
        if not is_grouped:
            meta['path'] = r.path
            meta['method'] = r.method
        entry['meta'] = meta

        entry['performance'] = {
            'total_duration_ms': r.time_taken,
            'database_duration_ms': r.meta_time_spent_queries,
            'sql_query_count': r.num_sql_queries,
            'query_density_pct': round(
                (r.meta_time_spent_queries / r.time_taken) * 100, 2
            ) if r.time_taken and r.meta_time_spent_queries else 0
        }

        if not omit_queries:
            queries = SQLQuery.objects.filter(request=r).order_by('start_time')
            entry['queries'] = [
                {
                    'query_id': q.id,
                    'execution_time_ms': q.time_taken,
                    'raw_sql': q.query,
                    'traceback': q.traceback if q.traceback else "None"
                }
                for q in queries
            ]

        if include_response:
            body = r.response.body if r.response else None
            # Try to parse as JSON so it renders formatted in the output
            if body:
                try:
                    body = json.loads(body)
                except (json.JSONDecodeError, TypeError):
                    pass  # keep as plain string

            entry['response'] = {
                'status_code': r.response.status_code if r.response else None,
                'body': body,
            }

        # Lite mode: keep only timestamp, total_duration_ms, sql_query_count,
        # and response (response is later moved to group level by dedup)
        if lite:
            lite_entry = {
                'meta': {'timestamp': meta['timestamp']},
                'performance': {
                    'total_duration_ms': entry['performance']['total_duration_ms'],
                    'sql_query_count': entry['performance']['sql_query_count'],
                },
            }
            if include_response and 'response' in entry:
                lite_entry['response'] = entry['response']
            return lite_entry

        return entry

    def _compact_keys(self, entry):
        """Translate verbose keys to short aliases for compact output."""
        key_map = {
            'request_id': 'rid',
            'meta': 'm',
            'path': 'p',
            'method': 'mt',
            'status_code': 'sc',
            'timestamp': 'ts',
            'performance': 'perf',
            'total_duration_ms': 'tot',
            'database_duration_ms': 'db',
            'sql_query_count': 'qc',
            'query_density_pct': 'qd',
            'queries': 'q',
            'query_id': 'qid',
            'execution_time_ms': 'et',
            'raw_sql': 'sql',
            'traceback': 'tb',
            'response': 'rsp',
            'responses': 'rsps',
            'body': 'b',
            'occurrences': 'occ',
        }
        if isinstance(entry, dict):
            return {key_map.get(k, k): self._compact_keys(v)
                    for k, v in entry.items()}
        elif isinstance(entry, list):
            return [self._compact_keys(i) for i in entry]
        return entry

    def export_to_json(self, requests, filename, omit_queries, omit_ids,
                       compact, group_by_path, include_response, lite=False):
        indent = None if compact else 4

        if group_by_path:
            analytics_data = self._build_grouped_output(
                requests, omit_queries, omit_ids, compact, include_response,
                lite
            )
        else:
            analytics_data = [
                self._build_request_entry(r, omit_queries, omit_ids,
                                          include_response, lite=lite)
                for r in requests
            ]
            # In lite (non-grouped) mode, also truncate response bodies
            if lite:
                for entry in analytics_data:
                    if 'response' in entry:
                        entry['response'] = self._truncate_body_lists(
                            entry['response']
                        )

        if compact:
            analytics_data = [self._compact_keys(e) for e in analytics_data]

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(analytics_data, f, indent=indent, ensure_ascii=False)

    def _build_grouped_output(self, requests, omit_queries, omit_ids,
                               compact, include_response, lite=False):
        """Group requests by path, compute aggregate stats per group."""
        from collections import defaultdict, Counter
        groups = defaultdict(list)

        for r in requests:
            groups[r.path].append(r)

        result = []
        for path, reqs in sorted(groups.items()):
            durations = [r.time_taken or 0 for r in reqs]
            # Keep None values as None; don't coerce to 0
            db_times = [r.meta_time_spent_queries for r in reqs
                        if r.meta_time_spent_queries is not None]
            sql_counts = [r.num_sql_queries or 0 for r in reqs]
            statuses = [r.response.status_code if r.response else None
                        for r in reqs]

            # Compute db stats only when there is actual data
            if db_times:
                db_stats = {
                    'avg': round(mean(db_times), 2),
                    'min': min(db_times),
                    'max': max(db_times),
                }
            else:
                db_stats = None

            # Query density: only average requests that actually have db time
            valid_densities = [
                round((r.meta_time_spent_queries / r.time_taken) * 100, 2)
                for r in reqs
                if r.time_taken and r.meta_time_spent_queries
            ]

            group = {
                'path': path,
                'count': len(reqs),
                'methods': sorted(set(r.method for r in reqs)),
                'status_codes': sorted(set(
                    s for s in statuses if s is not None
                )),
                'performance': {
                    'total_duration_ms': {
                        'avg': round(mean(durations), 2),
                        'min': min(durations),
                        'max': max(durations),
                        'sum': round(sum(durations), 2),
                    },
                    'database_duration_ms': db_stats,
                    'sql_query_count': {
                        'avg': round(mean(sql_counts), 1),
                        'min': min(sql_counts),
                        'max': max(sql_counts),
                    },
                    'avg_query_density_pct': (
                        round(mean(valid_densities), 2)
                        if valid_densities else 0
                    ),
                },
                'requests': [
                    self._build_request_entry(r, omit_queries, omit_ids,
                                              include_response,
                                              is_grouped=True, lite=lite)
                    for r in sorted(reqs, key=lambda x: x.start_time,
                                    reverse=True)
                ]
            }

            # ---- Response deduplication ----
            if include_response:
                self._deduplicate_responses(group)

            result.append(group)

        # Sort groups by total time (descending) for quick identification of
        # most expensive endpoints (must sort BEFORE lite-mode stripping)
        result.sort(
            key=lambda g: g['performance']['total_duration_ms']['sum'],
            reverse=True
        )

        # Lite mode: strip each group to only path, requests, response/responses
        # and truncate list bodies in responses
        if lite:
            stripped = []
            for group in result:
                lite_group = {'path': group['path']}
                if 'response' in group:
                    lite_group['response'] = self._truncate_body_lists(
                        group['response']
                    )
                if 'responses' in group:
                    lite_group['responses'] = [
                        self._truncate_body_lists(r)
                        for r in group['responses']
                    ]
                lite_group['requests'] = group['requests']
                stripped.append(lite_group)
            return stripped

        return result

    def _deduplicate_responses(self, group):
        """Move response bodies out of individual requests and show each
        unique body once with its occurrence count at the group level."""
        from collections import Counter

        requests = group['requests']
        responses = []
        for entry in requests:
            resp = entry.pop('response', None)
            if resp is not None:
                responses.append(resp)

        if not responses:
            return

        # Use JSON-serialised body as a hashable key for deduplication
        body_keys = [
            json.dumps(r.get('body'), sort_keys=True, ensure_ascii=False)
            for r in responses
        ]
        counts = Counter(body_keys)

        if len(counts) == 1:
            # All responses are identical — show once at group level
            unique = dict(responses[0])
            unique['occurrences'] = len(responses)
            group['response'] = unique
        else:
            # Different responses — list each unique one with its count
            seen_keys = set()
            unique_list = []
            for i, r in enumerate(responses):
                key = body_keys[i]
                if key not in seen_keys:
                    seen_keys.add(key)
                    entry = dict(r)
                    entry['occurrences'] = counts[key]
                    unique_list.append(entry)
            group['responses'] = unique_list

    def _truncate_body_lists(self, obj):
        """Recursively truncate lists in a response body.

        For any list with more than one item, keep the first item in full,
        show only the first key of the second item (if it's a dict) followed
        by '...', and drop all remaining items.
        """
        if isinstance(obj, dict):
            return {k: self._truncate_body_lists(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            if len(obj) <= 1:
                return [self._truncate_body_lists(i) for i in obj]
            # Keep first item fully, truncate second, drop the rest
            result = [self._truncate_body_lists(obj[0])]
            second = obj[1]
            if isinstance(second, dict):
                # Show only the first key-value pair of the second object
                first_key = next(iter(second))
                truncated = {
                    first_key: self._truncate_body_lists(second[first_key]),
                    '...': '...'
                }
                result.append(truncated)
            else:
                # For non-dict items, just show the item then '...'
                result.append(self._truncate_body_lists(second))
                result.append('...')
            return result
        return obj
