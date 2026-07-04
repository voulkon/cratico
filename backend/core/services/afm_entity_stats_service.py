"""
Simple bulk-computation service for AFMEntityStats.

Uses efficient aggregation queries that leverage foreign keys,
so no per-entity loops are needed.
"""

from collections import defaultdict
from decimal import Decimal
from typing import Dict

from core.models.afm_entity_stats import AFMEntityStats
from core.models.entities import (
    AFMEntity,
    DecisionAmountField,
    DecisionEntityRelationship,
)
from django.db import transaction
from django.db.models import Count, Max, Min, Q, Sum
from loguru import logger


class AFMEntityStatsService:
    """
    Computes or refreshes aggregated statistics for AFM entities.

    All methods use bulk-queries so the whole table can be refreshed
    in a handful of SQL statements regardless of how many entities exist.
    """

    def compute_all(self, batch_size: int = 5000) -> Dict[str, int]:
        """
        Compute stats for every AFM entity and upsert them in bulk.

        Returns a dict with counts: created, updated, total.
        """
        logger.info("Computing AFMEntityStats for all entities...")

        # 1. Gather raw metrics for every entity (bulk aggregations)
        raw = self._gather_all_metrics()

        # 2. Upsert in batches
        entity_ids = list(raw.keys())
        created = 0
        updated = 0

        for i in range(0, len(entity_ids), batch_size):
            batch_ids = entity_ids[i : i + batch_size]
            with transaction.atomic():
                for eid in batch_ids:
                    m = raw[eid]
                    _, was_created = AFMEntityStats.objects.update_or_create(
                        entity_id=eid,
                        defaults={
                            "total_decisions": m["total_decisions"],
                            "distinct_roles": m["distinct_roles"],
                            "total_amount": m["total_amount"],
                            "average_amount_per_decision": m["avg_amount"],
                            "max_single_amount": m["max_amount"],
                            "distinct_organizations": m["distinct_organizations"],
                            "distinct_counterpart_entities": m["distinct_counterpart_entities"],
                            "direct_assignment_count": m["direct_assignment_count"],
                            "direct_assignment_percentage": m["direct_assignment_percentage"],
                        },
                    )
                    if was_created:
                        created += 1
                    else:
                        updated += 1

        result = {
            "created": created,
            "updated": updated,
            "total": created + updated,
        }
        logger.info(f"AFMEntityStats computation complete: {result}")
        return result

    # ------------------------------------------------------------------
    # Bulk metric gathering
    # ------------------------------------------------------------------

    def _gather_all_metrics(self) -> Dict[int, dict]:
        """
        Gather every raw metric in a single pass using bulk queries.

        Returns: {entity_id: {metric_name: value}}
        """
        metrics: Dict[int, dict] = defaultdict(
            lambda: {
                "total_decisions": 0,
                "distinct_roles": 0,
                "total_amount": Decimal("0.00"),
                "avg_amount": Decimal("0.00"),
                "max_amount": Decimal("0.00"),
                "distinct_organizations": 0,
                "distinct_counterpart_entities": 0,
                "direct_assignment_count": 0,
                "direct_assignment_percentage": 0.0,
            }
        )

        # ---- (A) decision count + distinct_roles + distinct_organizations ----
        # One query groups by entity, counting decisions (distinct) and roles.
        rel_qs = (
            DecisionEntityRelationship.objects.values("entity_id")
            .annotate(
                total_decisions=Count("decision_id", distinct=True),
                distinct_roles=Count("role", distinct=True),
                distinct_organizations=Count("decision__organization_id", distinct=True),
            )
        )
        for row in rel_qs:
            eid = row["entity_id"]
            metrics[eid]["total_decisions"] = row["total_decisions"]
            metrics[eid]["distinct_roles"] = row["distinct_roles"]
            metrics[eid]["distinct_organizations"] = row["distinct_organizations"]

        # ---- (B) amounts: sum, avg, max ----
        amount_qs = (
            DecisionAmountField.objects
            .filter(amount__isnull=False, associated_relationship__isnull=False)
            .values("associated_relationship__entity_id")
            .annotate(
                total=Sum("amount"),
                avg=Sum("amount") / Count("id"),  # rough avg per amount-row (fine)
                amax=Max("amount"),
            )
        )
        for row in amount_qs:
            eid = row["associated_relationship__entity_id"]
            metrics[eid]["total_amount"] = row["total"] or Decimal("0")
            metrics[eid]["max_amount"] = row["amax"] or Decimal("0")
            # Average: total / number_of_decisions_with_amounts
            # We'll compute a proper avg in step (C) below.

        # ---- (C) proper per-decision amounts for avg ----
        # Sum amounts per (entity, decision), then average across decisions
        per_decision_amounts = (
            DecisionAmountField.objects
            .filter(amount__isnull=False, associated_relationship__isnull=False)
            .values("associated_relationship__entity_id", "decision_id")
            .annotate(decision_total=Sum("amount"))
        )

        entity_amounts_by_decision: Dict[int, list] = defaultdict(list)
        for row in per_decision_amounts:
            eid = row["associated_relationship__entity_id"]
            entity_amounts_by_decision[eid].append(row["decision_total"])

        for eid, amounts in entity_amounts_by_decision.items():
            if amounts:
                metrics[eid]["avg_amount"] = (
                    Decimal(sum(amounts)) / len(amounts)
                ).quantize(Decimal("0.01"))

        # ---- (D) direct-assignment count ----
        direct_qs = (
            DecisionEntityRelationship.objects
            .filter(decision__classification__is_direct_assignment=True)
            .values("entity_id")
            .annotate(count=Count("decision_id", distinct=True))
        )
        for row in direct_qs:
            eid = row["entity_id"]
            metrics[eid]["direct_assignment_count"] = row["count"]

        # ---- (E) distinct counterpart entities ----
        # For each entity, find other entities that appear in the same decisions.
        # We do this in two steps:
        #   Step 1: per entity, collect the set of decision_ids
        #   Step 2: for each decision_id, count distinct entity_ids → subtract self
        #
        # Since we're optimizing for bulk, we use a self-join approach.
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH entity_decisions AS (
                    SELECT entity_id, decision_id
                    FROM core_decisionentityrelationship
                    GROUP BY entity_id, decision_id
                )
                SELECT ed1.entity_id,
                       COUNT(DISTINCT ed2.entity_id) FILTER (WHERE ed2.entity_id != ed1.entity_id) AS counterpart_count
                FROM entity_decisions ed1
                JOIN entity_decisions ed2 ON ed2.decision_id = ed1.decision_id
                GROUP BY ed1.entity_id
                """
            )
            for entity_id, cc in cursor.fetchall():
                metrics[entity_id]["distinct_counterpart_entities"] = cc

        # ---- (F) percentages ----
        for eid, m in metrics.items():
            if m["total_decisions"] > 0:
                m["direct_assignment_percentage"] = round(
                    m["direct_assignment_count"] / m["total_decisions"] * 100, 1
                )

        return dict(metrics)

    # ------------------------------------------------------------------
    # Convenience: compute a single entity
    # ------------------------------------------------------------------

    def compute_single(self, entity_id: int) -> AFMEntityStats:
        """Refresh stats for a single entity and return the saved object."""
        raw = self._gather_all_metrics()
        m = raw.get(entity_id)
        if m is None:
            # Entity has no relationships → fill with zeros
            m = {
                "total_decisions": 0,
                "distinct_roles": 0,
                "total_amount": Decimal("0.00"),
                "avg_amount": Decimal("0.00"),
                "max_amount": Decimal("0.00"),
                "distinct_organizations": 0,
                "distinct_counterpart_entities": 0,
                "direct_assignment_count": 0,
                "direct_assignment_percentage": 0.0,
            }

        stats, _created = AFMEntityStats.objects.update_or_create(
            entity_id=entity_id,
            defaults={
                "total_decisions": m["total_decisions"],
                "distinct_roles": m["distinct_roles"],
                "total_amount": m["total_amount"],
                "average_amount_per_decision": m["avg_amount"],
                "max_single_amount": m["max_amount"],
                "distinct_organizations": m["distinct_organizations"],
                "distinct_counterpart_entities": m["distinct_counterpart_entities"],
                "direct_assignment_count": m["direct_assignment_count"],
                "direct_assignment_percentage": m["direct_assignment_percentage"],
            },
        )
        return stats
