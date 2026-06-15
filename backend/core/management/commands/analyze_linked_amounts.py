"""
Analyze DecisionAmountField rows that ARE linked to DecisionEntityRelationship
via associated_relationship_id.

This focuses on the "juicy" amounts — those that actually have an entity
counterpart — and answers:

1. Linkage rate: what % of amount fields are linked, by decision type?
2. Entity-level aggregation: which entities get what patterns?
3. Per-relationship: what amount patterns are tied to each role/path?

Run with:
    python manage.py analyze_linked_amounts [--type-uid TYPE_UID]
"""

from collections import defaultdict
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Analyze DecisionAmountField rows that are linked to a DecisionEntityRelationship"

    def add_arguments(self, parser):
        parser.add_argument(
            '--type-uid',
            type=str,
            help='Filter to a specific decision type UID (e.g., B.2.2)',
        )

    def classify_path(self, path: str) -> str:
        if path.startswith('sponsor[') and '.expenseAmount' in path:
            return 'sponsor[N].expenseAmount'
        elif path.startswith('sponsor['):
            return 'sponsor[N]'
        elif path.startswith('amountWithKae['):
            return 'amountWithKae[N]'
        elif path.startswith('amountWithVATAndKae[') and '.amountWithVAT' in path:
            return 'amountWithVATAndKae[N].amountWithVAT'
        elif path.startswith('amountWithVATAndKae['):
            return 'amountWithVATAndKae[N]'
        elif path == 'amountWithVAT':
            return 'amountWithVAT'
        elif path == 'awardAmount':
            return 'awardAmount'
        elif path == 'contractAmount':
            return 'contractAmount'
        elif path == 'estimatedAmount':
            return 'estimatedAmount'
        elif path == 'positionSalary':
            return 'positionSalary'
        else:
            return f'other: {path}'

    def handle(self, *args, **options):
        type_uid = options.get('type_uid')
        type_filter = f"AND dt.uid = '{type_uid}'" if type_uid else ""

        self.stdout.write("=" * 100)
        self.stdout.write("LINKED AMOUNT ANALYSIS (associated_relationship_id IS NOT NULL)")
        self.stdout.write("=" * 100)

        # ------------------------------------------------------------------
        # 1. LINKAGE RATE: linked vs total, by decision type
        # ------------------------------------------------------------------
        self.stdout.write("\n[SECTION] 1. LINKAGE RATE BY DECISION TYPE")
        self.stdout.write("-" * 100)

        with connection.cursor() as cursor:
            cursor.execute(f"""
                SELECT
                    dt.label,
                    dt.uid,
                    COUNT(daf.id) AS total_amounts,
                    COUNT(daf.associated_relationship_id) AS linked_amounts,
                    COUNT(DISTINCT d.id) AS total_decisions_with_amounts,
                    COUNT(DISTINCT CASE WHEN daf.associated_relationship_id IS NOT NULL
                                   THEN d.id END) AS decisions_with_linked_amounts,
                    COUNT(DISTINCT daf.associated_relationship_id) AS unique_relationships_linked
                FROM core_decisionamountfield daf
                JOIN core_decision d ON daf.decision_id = d.id
                JOIN core_acttype dt ON d.decision_type_id = dt.uid
                WHERE 1=1 {type_filter}
                GROUP BY dt.label, dt.uid
                HAVING COUNT(daf.id) > 0
                ORDER BY total_amounts DESC
            """)
            linkage = cursor.fetchall()

        self.stdout.write(
            f"  {'Decision Type':<45} {'Total $':>10} {'Linked $':>10} {'Link %':>8} "
            f"{'Decisions w/ $':>14} {'Decisions w/ linked':>18} {'Unique rels':>12}"
        )
        self.stdout.write("  " + "-" * 130)
        for label, uid, total, linked, total_d, linked_d, unique_rels in linkage:
            pct = (linked / total * 100) if total else 0
            d_pct = (linked_d / total_d * 100) if total_d else 0
            self.stdout.write(
                f"  {label:<45} {total:>10,} {linked:>10,} {pct:>7.1f}% "
                f"{total_d:>14,} {linked_d:>18,} ({d_pct:>5.1f}%) {unique_rels:>12,}"
            )

        # ------------------------------------------------------------------
        # 2. LINKED-ONLY: pattern distribution by decision type
        # ------------------------------------------------------------------
        self.stdout.write("\n\n[SECTION] 2. PATTERN DISTRIBUTION (linked amounts only)")
        self.stdout.write("-" * 100)

        with connection.cursor() as cursor:
            cursor.execute(f"""
                SELECT
                    dt.label,
                    dt.uid,
                    daf.parent_key_path,
                    COUNT(*) AS cnt,
                    COUNT(DISTINCT daf.associated_relationship_id) AS unique_rels,
                    SUM(daf.amount) AS total_amount_sum
                FROM core_decisionamountfield daf
                JOIN core_decision d ON daf.decision_id = d.id
                JOIN core_acttype dt ON d.decision_type_id = dt.uid
                WHERE daf.associated_relationship_id IS NOT NULL {type_filter}
                GROUP BY dt.label, dt.uid, daf.parent_key_path
                ORDER BY dt.label, cnt DESC
            """)
            linked_patterns = cursor.fetchall()

        # Aggregate by classified pattern (not raw path) to avoid duplicate labels
        type_patterns = defaultdict(lambda: defaultdict(lambda: {
            'count': 0, 'unique_rels': 0, 'total_sum': 0.0, 'raw_examples': set()
        }))
        for label, uid, path, cnt, unique_rels, total_sum in linked_patterns:
            classified = self.classify_path(path)
            agg = type_patterns[(label, uid)][classified]
            agg['count'] += cnt
            agg['unique_rels'] += unique_rels
            agg['total_sum'] += float(total_sum or 0)
            agg['raw_examples'].add(path)

        for (label, uid), classified_map in sorted(type_patterns.items()):
            patterns = sorted(classified_map.items(), key=lambda x: -x[1]['count'])
            total = sum(p[1]['count'] for p in patterns)
            total_euros = sum(p[1]['total_sum'] for p in patterns)
            self.stdout.write(f"\n  🔹 {label} ({uid}) — {total:,} linked amounts, €{total_euros:,.2f} total")
            for path_name, agg in patterns[:10]:
                pct = (agg['count'] / total * 100) if total else 0
                examples = sorted(agg['raw_examples'])
                detail = f"  e.g. {examples[0]}" if len(examples) == 1 else f"  ({len(examples)} variants, e.g. {examples[0]})"
                self.stdout.write(
                    f"       • {path_name:<40} {agg['count']:>8,} ({pct:>5.1f}%)  "
                    f"€{agg['total_sum']:>15,.2f}  [{agg['unique_rels']:,} relationships]{detail}"
                )
            if len(patterns) > 10:
                self.stdout.write(f"       ... and {len(patterns) - 10} more pattern groups")

        # ------------------------------------------------------------------
        # 3. ENTITY-LEVEL: which entities receive the most money?
        # ------------------------------------------------------------------
        self.stdout.write("\n\n[SECTION] 3. TOP ENTITIES BY LINKED AMOUNT (per decision type)")
        self.stdout.write("-" * 100)

        with connection.cursor() as cursor:
            cursor.execute(f"""
                SELECT
                    dt.label,
                    dt.uid,
                    e.afm,
                    e.name,
                    der.role,
                    COUNT(DISTINCT daf.id) AS amount_fields,
                    SUM(daf.amount) AS total_euros,
                    COUNT(DISTINCT d.id) AS unique_decisions
                FROM core_decisionamountfield daf
                JOIN core_decisionentityrelationship der
                    ON daf.associated_relationship_id = der.id
                JOIN core_afmentity e ON der.entity_id = e.id
                JOIN core_decision d ON daf.decision_id = d.id
                JOIN core_acttype dt ON d.decision_type_id = dt.uid
                WHERE 1=1 {type_filter}
                GROUP BY dt.label, dt.uid, e.afm, e.name, der.role
                ORDER BY total_euros DESC
            """)
            entity_rows = cursor.fetchall()

        # Group top 3 per type
        type_entities = defaultdict(list)
        for label, uid, afm, name, role, fields, euros, decisions in entity_rows:
            type_entities[(label, uid)].append({
                'afm': afm, 'name': name, 'role': role,
                'fields': fields, 'euros': float(euros), 'decisions': decisions,
            })

        for (label, uid), entities in sorted(type_entities.items()):
            top = sorted(entities, key=lambda x: -x['euros'])[:5]
            self.stdout.write(f"\n  🔹 {label} ({uid})")
            for e in top:
                name_short = (e['name'] or '(no name)')[:60]
                self.stdout.write(
                    f"       {e['afm']}  {name_short:<62} ({e['role']})  "
                    f"€{e['euros']:>15,.2f}  [{e['decisions']:,} decisions, {e['fields']:,} fields]"
                )

        # ------------------------------------------------------------------
        # 4. ROLE × PATTERN cross-tab
        # ------------------------------------------------------------------
        self.stdout.write("\n\n[SECTION] 4. ROLE × PATTERN CROSS-TAB (which roles get which amounts)")
        self.stdout.write("-" * 100)

        with connection.cursor() as cursor:
            cursor.execute(f"""
                SELECT
                    der.role,
                    daf.parent_key_path,
                    COUNT(*) AS cnt,
                    SUM(daf.amount) AS total_euros,
                    COUNT(DISTINCT e.afm) AS unique_entities
                FROM core_decisionamountfield daf
                JOIN core_decisionentityrelationship der
                    ON daf.associated_relationship_id = der.id
                JOIN core_afmentity e ON der.entity_id = e.id
                WHERE 1=1 {type_filter.replace('dt.uid', 'dt.uid') if type_filter else ''}
                GROUP BY der.role, daf.parent_key_path
                ORDER BY der.role, cnt DESC
            """)
            role_pattern_rows = cursor.fetchall()

        role_patterns = defaultdict(list)
        for role, path, cnt, euros, entities in role_pattern_rows:
            role_patterns[role].append({
                'pattern': self.classify_path(path),
                'raw_path': path,
                'count': cnt,
                'euros': float(euros or 0),
                'entities': entities,
            })

        for role in sorted(role_patterns.keys()):
            patterns = role_patterns[role]
            total = sum(p['count'] for p in patterns)
            total_e = sum(p['euros'] for p in patterns)
            self.stdout.write(f"\n  🔹 Role: {role}  ({total:,} linked amounts, €{total_e:,.2f}, {patterns[0]['entities'] if patterns else 0} entities)")
            for p in sorted(patterns, key=lambda x: -x['count'])[:8]:
                pct = (p['count'] / total * 100) if total else 0
                self.stdout.write(
                    f"       • {p['pattern']:<40} {p['count']:>8,} ({pct:>5.1f}%)  €{p['euros']:>15,.2f}"
                )

        # ------------------------------------------------------------------
        # 5. UNLINKED amounts: what are we missing?
        # ------------------------------------------------------------------
        self.stdout.write("\n\n[SECTION] 5. UNLINKED AMOUNTS — WHAT'S NOT CONNECTED TO ENTITIES?")
        self.stdout.write("-" * 100)

        with connection.cursor() as cursor:
            cursor.execute(f"""
                SELECT
                    dt.label,
                    dt.uid,
                    daf.parent_key_path,
                    COUNT(*) AS cnt,
                    SUM(daf.amount) AS total_euros,
                    COUNT(DISTINCT d.id) AS unique_decisions
                FROM core_decisionamountfield daf
                JOIN core_decision d ON daf.decision_id = d.id
                JOIN core_acttype dt ON d.decision_type_id = dt.uid
                WHERE daf.associated_relationship_id IS NULL {type_filter}
                GROUP BY dt.label, dt.uid, daf.parent_key_path
                ORDER BY cnt DESC
            """)
            unlinked = cursor.fetchall()

        if unlinked:
            self.stdout.write(f"  {'Path':<45} {'Count':>10} {'Decisions':>12} {'Total €':>18}  Type")
            self.stdout.write("  " + "-" * 100)
            for label, uid, path, cnt, euros, decs in unlinked[:30]:
                self.stdout.write(
                    f"  {self.classify_path(path):<45} {cnt:>10,} {decs:>12,} "
                    f"€{float(euros or 0):>17,.2f}  {label} ({uid})"
                )
        else:
            self.stdout.write("  ✅ All amount fields are linked to entities!")

        # ------------------------------------------------------------------
        # 6. SAMPLE UNLINKED: dump raw extra_field_values_json to understand why
        # ------------------------------------------------------------------
        self.stdout.write("\n\n[SECTION] 6. SAMPLE UNLINKED AMOUNTS WITH RAW extra_field_values_json")
        self.stdout.write("   (Shows the actual source JSON to diagnose why linkage fails)")
        self.stdout.write("-" * 100)

        # Get the top unlinked (type, path) combos, then grab samples
        with connection.cursor() as cursor:
            cursor.execute(f"""
                WITH unlinked_summary AS (
                    SELECT
                        dt.label,
                        dt.uid,
                        daf.parent_key_path,
                        COUNT(*) AS cnt
                    FROM core_decisionamountfield daf
                    JOIN core_decision d ON daf.decision_id = d.id
                    JOIN core_acttype dt ON d.decision_type_id = dt.uid
                    WHERE daf.associated_relationship_id IS NULL {type_filter}
                    GROUP BY dt.label, dt.uid, daf.parent_key_path
                ),
                top_combos AS (
                    SELECT label, uid, parent_key_path,
                           ROW_NUMBER() OVER (ORDER BY cnt DESC) AS rn
                    FROM unlinked_summary
                ),
                samples AS (
                    SELECT
                        tc.label,
                        tc.uid,
                        tc.parent_key_path,
                        daf.id AS daf_id,
                        daf.source_field_name,
                        daf.amount,
                        daf.structure_type,
                        d.id AS decision_id,
                        d.ada,
                        d.subject,
                        d.extra_field_values_json,
                        ROW_NUMBER() OVER (
                            PARTITION BY tc.label, tc.uid, tc.parent_key_path
                            ORDER BY daf.amount DESC
                        ) AS sample_rn
                    FROM top_combos tc
                    JOIN core_decisionamountfield daf
                        ON daf.parent_key_path = tc.parent_key_path
                        AND daf.associated_relationship_id IS NULL
                    JOIN core_decision d ON daf.decision_id = d.id
                    JOIN core_acttype dt ON d.decision_type_id = dt.uid
                        AND dt.uid = tc.uid
                    WHERE tc.rn <= 12
                )
                SELECT label, uid, parent_key_path, daf_id, source_field_name,
                       amount, structure_type, decision_id, ada, subject,
                       extra_field_values_json
                FROM samples
                WHERE sample_rn <= 2
                ORDER BY label, parent_key_path, amount DESC
            """)
            sample_rows = cursor.fetchall()

        if sample_rows:
            current_combo = None
            for row in sample_rows:
                label, uid, path, daf_id, field_name, amount, struct, dec_id, ada, subject, extra_json = row
                combo = (label, uid, path)
                if combo != current_combo:
                    current_combo = combo
                    self.stdout.write(f"\n  ┌─ TYPE: {label} ({uid}) | PATH: {path}")
                else:
                    self.stdout.write(f"\n  ├─ (another sample for same type+path)")

                subject_display = (subject or '(no subject)')[:100]
                self.stdout.write(f"  │  ADA: {ada}")
                self.stdout.write(f"  │  Subject: {subject_display}")
                self.stdout.write(f"  │  AmountField: source_field_name={field_name}, amount={amount}, structure_type={struct}")

                # Dump the relevant slice of extra_field_values_json
                if extra_json:
                    import json
                    try:
                        if isinstance(extra_json, str):
                            extra = json.loads(extra_json)
                        else:
                            extra = extra_json
                    except (json.JSONDecodeError, TypeError):
                        extra = extra_json

                    # Try to show the field at the path and its siblings
                    self.stdout.write(f"  │  extra_field_values_json (relevant portion):")
                    extra_str = json.dumps(extra, indent=2, ensure_ascii=False, default=str)

                    # Find and highlight the relevant field in the JSON
                    # Show the full JSON but limit to ~2000 chars, with the target path highlighted
                    if len(extra_str) > 2500:
                        # Try to find the relevant section
                        search_key = field_name if field_name else path.split('.')[-1]
                        # Show first 800 chars + context around the key
                        key_pos = extra_str.find(f'"{search_key}"')
                        if key_pos > 800:
                            self.stdout.write(f"  │    ...(truncated, {len(extra_str):,} chars total)...")
                            start = max(0, key_pos - 300)
                            snippet = extra_str[start:start + 2000]
                            self.stdout.write(f"  │    {snippet}")
                            if start + 2000 < len(extra_str):
                                self.stdout.write(f"  │    ...(further truncated)...")
                        else:
                            self.stdout.write(f"  │    {extra_str[:2500]}")
                            if len(extra_str) > 2500:
                                self.stdout.write(f"  │    ...({len(extra_str) - 2500:,} more chars)...")
                    else:
                        for line in extra_str.split('\n'):
                            self.stdout.write(f"  │    {line}")
                else:
                    self.stdout.write(f"  │  extra_field_values_json: NULL (empty)")

                self.stdout.write(f"  └─ (decision_id={dec_id}, daf_id={daf_id})")
        else:
            self.stdout.write("  (No unlinked samples to show)")

        self.stdout.write("\n" + "=" * 100)
        self.stdout.write("Analysis complete.")
        self.stdout.write("=" * 100)
