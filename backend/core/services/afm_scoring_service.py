"""
AFM Entity Scoring Service

Calculates importance scores for AFM entities based on:
- Appearance frequency across decisions
- Total transaction amounts
- Number of unique organizations worked with
- Direct assignment count and percentage
- Recency of appearances (optional)

Supports two scoring modes:
1. SIMPLE: Percentage-based scoring (value / max_value) * 100
2. SOPHISTICATED: Configurable normalization strategies (min-max, z-score, robust, log)

The scoring algorithm is configurable via AFMScoringConfig model.
"""

import math
from datetime import timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from core.models.afm_scoring import (
    AFMEntityScore,
    AFMScoringConfig,
    FeatureImpact,
    NormalizationStrategy,
)
from core.models.entities import (
    AFMEntity,
    DecisionAmountField,
    DecisionEntityRelationship,
)
from django.db import transaction
from django.db.models import Avg, Count, Max, Min, Q, StdDev, Sum
from django.utils import timezone
from loguru import logger


class FeatureNormalizer:
    """
    Utility class for normalizing features using different strategies.

    Used when sophisticated normalization is enabled.
    """

    @staticmethod
    def normalize(
        value: float,
        strategy: str,
        stats: Dict[str, float],
        impact: str = FeatureImpact.POSITIVE,
    ) -> float:
        """
        Normalize a value to 0-1 range using the specified strategy.

        Args:
            value: Raw value to normalize
            strategy: Normalization strategy (from NormalizationStrategy)
            stats: Statistics needed for normalization (min, max, mean, std, median, iqr)
            impact: Whether higher is better (POSITIVE) or worse (NEGATIVE)

        Returns:
            Normalized value in 0-1 range
        """
        if strategy == NormalizationStrategy.MIN_MAX:
            normalized = FeatureNormalizer._min_max(value, stats)
        elif strategy == NormalizationStrategy.Z_SCORE:
            normalized = FeatureNormalizer._z_score(value, stats)
        elif strategy == NormalizationStrategy.ROBUST:
            normalized = FeatureNormalizer._robust(value, stats)
        elif strategy == NormalizationStrategy.LOG:
            normalized = FeatureNormalizer._log_transform(value, stats)
        else:
            normalized = FeatureNormalizer._min_max(value, stats)

        # Apply impact direction
        if impact == FeatureImpact.NEGATIVE:
            normalized = 1.0 - normalized

        # Clip to 0-1 range
        return max(0.0, min(1.0, normalized))

    @staticmethod
    def _min_max(value: float, stats: Dict[str, float]) -> float:
        """Min-max normalization: (value - min) / (max - min)"""
        min_val = stats.get("min", 0.0)
        max_val = stats.get("max", 1.0)

        if max_val == min_val:
            return 0.0 if value == min_val else 1.0

        return (value - min_val) / (max_val - min_val)

    @staticmethod
    def _z_score(value: float, stats: Dict[str, float]) -> float:
        """
        Z-score normalization: (value - mean) / std
        Then map to 0-1 using sigmoid-like transformation
        """
        mean = stats.get("mean", 0.0)
        std = stats.get("std", 1.0)

        if std == 0:
            return 0.5

        z = (value - mean) / std
        # Map z-score to 0-1 using sigmoid: 1 / (1 + exp(-z))
        # This gives ~0 for z < -3, ~0.5 for z = 0, ~1 for z > 3
        try:
            return 1.0 / (1.0 + math.exp(-z))
        except OverflowError:
            return 0.0 if z < 0 else 1.0

    @staticmethod
    def _robust(value: float, stats: Dict[str, float]) -> float:
        """
        Robust scaling: (value - median) / IQR
        Uses median and IQR (interquartile range) instead of mean/std
        More resistant to outliers
        """
        median = stats.get("median", 0.0)
        iqr = stats.get("iqr", 1.0)

        if iqr == 0:
            return 0.5

        # Scale by IQR
        scaled = (value - median) / iqr

        # Map to 0-1 using sigmoid
        try:
            return 1.0 / (1.0 + math.exp(-scaled))
        except OverflowError:
            return 0.0 if scaled < 0 else 1.0

    @staticmethod
    def _log_transform(value: float, stats: Dict[str, float]) -> float:
        """
        Log transform + min-max normalization.
        Good for highly skewed data (like amounts).
        """
        # Add 1 to handle zero values
        log_value = math.log1p(max(0, value))

        min_log = stats.get("min_log", 0.0)
        max_log = stats.get("max_log", 1.0)

        if max_log == min_log:
            return 0.0 if log_value == min_log else 1.0

        return (log_value - min_log) / (max_log - min_log)


class AFMEntityScoringService:
    """
    Service for scoring and ranking AFM entities.

    Usage:
        service = AFMEntityScoringService()
        stats = service.score_all_entities()

        # Or score specific entities
        service.score_entities([entity1, entity2, ...])
    """

    def __init__(self, config: Optional[AFMScoringConfig] = None):
        """
        Initialize scoring service.

        Args:
            config: Optional scoring config (uses active config if not provided)
        """
        self.config = config or AFMScoringConfig.get_active()
        if not self.config:
            logger.warning("No active AFMScoringConfig found, creating default")
            self.config = self._create_default_config()

    def _create_default_config(self) -> AFMScoringConfig:
        """Create a default scoring configuration."""
        config, created = AFMScoringConfig.objects.get_or_create(
            name="Default",
            defaults={
                "is_active": True,
                "frequency_weight": 0.20,
                "amount_weight": 0.25,
                "organization_weight": 0.15,
                "direct_assignment_count_weight": 0.20,
                "direct_assignment_percentage_weight": 0.20,
                "normalization_strategy": NormalizationStrategy.ROBUST,
                "use_simple_scoring": True,  # Default to simple mode for performance
                "min_appearances": 3,
                "min_total_amount": Decimal("5000.00"),
                "min_unique_organizations": 2,
                "min_direct_assignments": 0,
                "retry_failed_after_days": 90,
                "never_retry_after_failures": 5,
            },
        )
        if created:
            logger.info("Created default AFMScoringConfig")
        return config

    def score_all_entities(
        self, batch_size: int = 1000, exclude_already_fetched: bool = False
    ) -> Dict[str, Any]:
        """
        Score all AFM entities in the database.

        Args:
            batch_size: Number of entities to process per batch
            exclude_already_fetched: Skip entities that already have successful GEMI data

        Returns:
            Statistics about the scoring operation
        """
        logger.info(f"Starting AFM entity scoring with config: {self.config.name}")

        # Validate config
        try:
            self.config.validate_weights()
        except ValueError as e:
            logger.error(f"Invalid scoring config: {e}")
            raise

        # Build queryset
        queryset = AFMEntity.objects.all()

        if exclude_already_fetched:
            queryset = queryset.filter(
                Q(gemi_lookup_success=False) | Q(gemi_lookup_attempted__isnull=True)
            )

        total_entities = queryset.count()
        logger.info(f"Scoring {total_entities} entities")

        # Compute global statistics for normalization
        logger.info("Computing global statistics...")
        global_stats = self._compute_global_statistics()

        # Pre-compute ALL entity metrics in bulk (this is the key optimization)
        logger.info("Pre-computing entity metrics in bulk...")
        all_metrics = self._compute_all_metrics_bulk()
        logger.info(f"Pre-computed metrics for {len(all_metrics)} entities")

        scored_count = 0
        eligible_count = 0

        # Process in batches
        entity_ids = list(queryset.values_list("id", flat=True))

        for i in range(0, len(entity_ids), batch_size):
            batch_ids = entity_ids[i : i + batch_size]
            batch_entities = {
                e.id: e for e in AFMEntity.objects.filter(id__in=batch_ids)
            }

            with transaction.atomic():
                for entity_id in batch_ids:
                    entity = batch_entities[entity_id]
                    metrics = all_metrics.get(entity_id, self._get_empty_metrics())
                    score_data = self.score_entity(entity, global_stats, metrics)
                    if score_data["is_eligible"]:
                        eligible_count += 1
                    scored_count += 1

            if scored_count % 10000 == 0:
                logger.info(f"Scored {scored_count}/{total_entities} entities")

        # Assign priority ranks (1 = highest priority)
        logger.info("Assigning priority ranks...")
        self._assign_priority_ranks()

        stats = {
            "total_scored": scored_count,
            "eligible_for_fetch": eligible_count,
            "ineligible": scored_count - eligible_count,
            "config_used": self.config.name,
            "global_stats": global_stats,
        }

        logger.info(f"Scoring completed", extra=stats)
        return stats

    def score_entity(
        self,
        entity: AFMEntity,
        global_stats: Optional[Dict[str, Any]] = None,
        metrics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Calculate score for a single AFM entity.

        Uses simple percentage-based scoring if config.use_simple_scoring=True,
        otherwise uses sophisticated normalization strategies.

        Args:
            entity: AFMEntity to score
            global_stats: Pre-computed global statistics
            metrics: Pre-computed entity metrics (avoids database query)

        Returns:
            Dictionary with score components and metadata
        """
        if global_stats is None:
            global_stats = self._compute_global_statistics()

        # Gather raw metrics for this entity
        if metrics is None:
            metrics = self._gather_entity_metrics(entity)

        # Check eligibility (minimum thresholds)
        is_eligible = self._check_eligibility(entity, metrics)

        # Choose scoring method based on config
        if getattr(self.config, "use_simple_scoring", True):
            return self._score_entity_simple(entity, metrics, global_stats, is_eligible)
        else:
            return self._score_entity_sophisticated(
                entity, metrics, global_stats, is_eligible
            )

    def _score_entity_simple(
        self,
        entity: AFMEntity,
        metrics: Dict[str, Any],
        global_stats: Dict[str, Any],
        is_eligible: bool,
    ) -> Dict[str, Any]:
        """
        Simple percentage-based scoring (0-100 scale).

        Formula: (value / max_value) * 100 for each feature.
        """
        max_stats = global_stats["max_values"]

        # Frequency score (0-100)
        frequency_score = 0.0
        if max_stats["max_appearances"] > 0:
            frequency_score = (
                metrics["appearances"] / max_stats["max_appearances"]
            ) * 100

        # Amount score (0-100)
        amount_score = 0.0
        if max_stats["max_amount"] > 0:
            amount_score = (
                float(metrics["total_amount"]) / max_stats["max_amount"]
            ) * 100

        # Organization score (0-100)
        org_score = 0.0
        if max_stats["max_orgs"] > 0:
            org_score = (metrics["unique_orgs"] / max_stats["max_orgs"]) * 100

        # Direct assignment count score (0-100)
        direct_count_score = 0.0
        if max_stats["max_direct_count"] > 0:
            direct_count_score = (
                metrics["direct_assignment_count"] / max_stats["max_direct_count"]
            ) * 100

        # Direct assignment percentage is already 0-100
        direct_pct_score = metrics["direct_assignment_percentage"]

        # Compute weighted total score (0-100 scale)
        total_score = (
            frequency_score * self.config.frequency_weight
            + amount_score * self.config.amount_weight
            + org_score * self.config.organization_weight
            + direct_count_score * self.config.direct_assignment_count_weight
            + direct_pct_score * self.config.direct_assignment_percentage_weight
        )

        # Apply recency boost if enabled
        if self.config.enable_recency_boost:
            if self._is_recent(entity):
                total_score *= self.config.recency_boost_multiplier
                logger.debug(f"Applied recency boost to {entity.afm}")

        # Save to database
        score_obj, created = AFMEntityScore.objects.update_or_create(
            entity=entity,
            defaults={
                "total_score": total_score,
                "frequency_score": frequency_score
                / 100,  # Store as 0-1 for consistency
                "amount_score": amount_score / 100,
                "organization_score": org_score / 100,
                "direct_assignment_count_score": direct_count_score / 100,
                "direct_assignment_percentage_score": direct_pct_score / 100,
                "total_appearances": metrics["appearances"],
                "total_amount": metrics["total_amount"],
                "unique_organizations": metrics["unique_orgs"],
                "direct_assignment_count": metrics["direct_assignment_count"],
                "direct_assignment_percentage": metrics["direct_assignment_percentage"],
                "is_eligible": is_eligible,
                "config_used": self.config,
                "normalization_stats": {
                    "method": "simple_percentage",
                    "max_values": max_stats,
                },
            },
        )

        return {
            "entity_afm": entity.afm,
            "total_score": total_score,
            "is_eligible": is_eligible,
            "metrics": metrics,
            "created": created,
        }

    def _score_entity_sophisticated(
        self,
        entity: AFMEntity,
        metrics: Dict[str, Any],
        global_stats: Dict[str, Any],
        is_eligible: bool,
    ) -> Dict[str, Any]:
        """
        Sophisticated scoring using configurable normalization strategies.
        """
        # Get normalization strategy and feature config
        strategy = self.config.normalization_strategy
        feature_config = self.config.get_feature_config()

        # Compute normalized scores (0-1 range) for each feature
        frequency_score = FeatureNormalizer.normalize(
            value=float(metrics["appearances"]),
            strategy=strategy,
            stats=global_stats["features"]["frequency"],
            impact=feature_config["frequency"]["impact"],
        )

        amount_score = FeatureNormalizer.normalize(
            value=float(metrics["total_amount"]),
            strategy=strategy,
            stats=global_stats["features"]["amount"],
            impact=feature_config["amount"]["impact"],
        )

        org_score = FeatureNormalizer.normalize(
            value=float(metrics["unique_orgs"]),
            strategy=strategy,
            stats=global_stats["features"]["organization"],
            impact=feature_config["organization"]["impact"],
        )

        direct_count_score = FeatureNormalizer.normalize(
            value=float(metrics["direct_assignment_count"]),
            strategy=strategy,
            stats=global_stats["features"]["direct_assignment_count"],
            impact=feature_config["direct_assignment_count"]["impact"],
        )

        direct_pct_score = FeatureNormalizer.normalize(
            value=metrics["direct_assignment_percentage"],
            strategy=strategy,
            stats=global_stats["features"]["direct_assignment_percentage"],
            impact=feature_config["direct_assignment_percentage"]["impact"],
        )

        # Compute weighted total score (0-100 scale)
        total_score = (
            frequency_score * self.config.frequency_weight
            + amount_score * self.config.amount_weight
            + org_score * self.config.organization_weight
            + direct_count_score * self.config.direct_assignment_count_weight
            + direct_pct_score * self.config.direct_assignment_percentage_weight
        ) * 100

        # Apply recency boost if enabled
        if self.config.enable_recency_boost:
            if self._is_recent(entity):
                total_score *= self.config.recency_boost_multiplier
                logger.debug(f"Applied recency boost to {entity.afm}")

        # Save to database
        score_obj, created = AFMEntityScore.objects.update_or_create(
            entity=entity,
            defaults={
                "total_score": total_score,
                "frequency_score": frequency_score,
                "amount_score": amount_score,
                "organization_score": org_score,
                "direct_assignment_count_score": direct_count_score,
                "direct_assignment_percentage_score": direct_pct_score,
                "total_appearances": metrics["appearances"],
                "total_amount": metrics["total_amount"],
                "unique_organizations": metrics["unique_orgs"],
                "direct_assignment_count": metrics["direct_assignment_count"],
                "direct_assignment_percentage": metrics["direct_assignment_percentage"],
                "is_eligible": is_eligible,
                "config_used": self.config,
                "normalization_stats": {
                    "strategy": strategy,
                    "feature_impacts": {
                        k: v["impact"] for k, v in feature_config.items()
                    },
                },
            },
        )

        return {
            "entity_afm": entity.afm,
            "total_score": total_score,
            "is_eligible": is_eligible,
            "metrics": metrics,
            "created": created,
        }

    def _get_empty_metrics(self) -> Dict[str, Any]:
        """Return empty metrics dict for entities with no data."""
        return {
            "appearances": 0,
            "unique_orgs": 0,
            "total_amount": Decimal("0.00"),
            "direct_assignment_count": 0,
            "direct_assignment_percentage": 0.0,
        }

    def _compute_all_metrics_bulk(self) -> Dict[int, Dict[str, Any]]:
        """
        Compute metrics for ALL entities in bulk using efficient aggregation queries.

        This is the KEY PERFORMANCE OPTIMIZATION - instead of making 3 queries per entity
        (1.5M queries for 500K entities), we make ~5 queries total.

        Returns:
            Dict mapping entity_id -> metrics dict
        """
        from collections import defaultdict

        metrics_by_entity = defaultdict(
            lambda: {
                "appearances": 0,
                "unique_orgs": 0,
                "total_amount": Decimal("0.00"),
                "direct_assignment_count": 0,
                "direct_assignment_percentage": 0.0,
            }
        )

        # 1. Get appearances from AFMEntity.total_appearances (already cached)
        entities_data = AFMEntity.objects.values_list("id", "total_appearances")
        for entity_id, appearances in entities_data:
            metrics_by_entity[entity_id]["appearances"] = appearances or 0

        # 2. Get unique organizations per entity (single query with aggregation)
        org_counts = (
            DecisionEntityRelationship.objects.values("entity_id")
            .annotate(org_count=Count("decision__organization", distinct=True))
            .values_list("entity_id", "org_count")
        )

        for entity_id, org_count in org_counts:
            metrics_by_entity[entity_id]["unique_orgs"] = org_count

        # 3. Get total amounts per entity (single query with aggregation)
        amount_sums = (
            DecisionAmountField.objects.filter(amount__isnull=False)
            .values("associated_relationship__entity_id")
            .annotate(total=Sum("amount"))
            .values_list("associated_relationship__entity_id", "total")
        )

        for entity_id, total in amount_sums:
            metrics_by_entity[entity_id]["total_amount"] = total or Decimal("0.00")

        # 4. Get direct assignment counts per entity (single query with aggregation)
        direct_counts = (
            DecisionEntityRelationship.objects.filter(
                decision__classification__is_direct_assignment=True
            )
            .values("entity_id")
            .annotate(count=Count("decision", distinct=True))
            .values_list("entity_id", "count")
        )

        for entity_id, count in direct_counts:
            metrics_by_entity[entity_id]["direct_assignment_count"] = count

        # 5. Calculate percentages
        for entity_id, metrics in metrics_by_entity.items():
            if metrics["appearances"] > 0:
                metrics["direct_assignment_percentage"] = (
                    metrics["direct_assignment_count"] / metrics["appearances"]
                ) * 100.0

        return dict(metrics_by_entity)

    def _gather_entity_metrics(self, entity: AFMEntity) -> Dict[str, Any]:
        """
        Gather raw metrics for an entity.

        DEPRECATED: Use _compute_all_metrics_bulk() for bulk operations.
        This method is kept for single-entity scoring only.
        """

        # Total appearances (use cached value from AFMEntity if available)
        appearances = entity.total_appearances or 0

        # Unique organizations (count via relationships)
        unique_orgs = (
            DecisionEntityRelationship.objects.filter(entity=entity)
            .values("decision__organization")
            .distinct()
            .count()
        )

        # Total amounts (sum via linked amounts)
        total_amount = DecisionAmountField.objects.filter(
            associated_relationship__entity=entity, amount__isnull=False
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        # Direct assignment count and percentage
        # Count decisions where entity appears that are classified as direct assignments
        direct_assignment_count = (
            DecisionEntityRelationship.objects.filter(
                entity=entity, decision__classification__is_direct_assignment=True
            )
            .values("decision")
            .distinct()
            .count()
        )

        # Calculate percentage
        direct_assignment_percentage = 0.0
        if appearances > 0:
            direct_assignment_percentage = (
                direct_assignment_count / appearances
            ) * 100.0

        return {
            "appearances": appearances,
            "unique_orgs": unique_orgs,
            "total_amount": total_amount,
            "direct_assignment_count": direct_assignment_count,
            "direct_assignment_percentage": direct_assignment_percentage,
        }

    def _compute_global_statistics(self) -> Dict[str, Any]:
        """
        Compute global statistics for scoring.

        Returns both simple max values and sophisticated statistics.
        The scoring method will use whichever is appropriate based on config.
        """
        use_simple = getattr(self.config, "use_simple_scoring", True)

        if use_simple:
            logger.info("Computing global statistics (simple mode - max values)")
        else:
            logger.info(
                f"Computing global statistics (sophisticated mode - {self.config.normalization_strategy} normalization)"
            )

        stats = {}

        # === SIMPLE MODE: Just need max values ===
        # Get max appearances
        max_appearances = (
            AFMEntity.objects.aggregate(max_val=Max("total_appearances"))["max_val"]
            or 1
        )

        # Get max amount per entity
        max_amount_result = (
            DecisionAmountField.objects.filter(amount__isnull=False)
            .values("associated_relationship__entity_id")
            .annotate(total=Sum("amount"))
            .aggregate(max_amount=Max("total"))
        )

        max_amount = float(max_amount_result["max_amount"] or 1)

        # Get max organizations per entity
        max_orgs_result = (
            DecisionEntityRelationship.objects.values("entity_id")
            .annotate(org_count=Count("decision__organization", distinct=True))
            .aggregate(max_orgs=Max("org_count"))
        )

        max_orgs = max_orgs_result["max_orgs"] or 1

        # Get max direct assignment count per entity
        max_direct_result = (
            DecisionEntityRelationship.objects.filter(
                decision__classification__is_direct_assignment=True
            )
            .values("entity_id")
            .annotate(count=Count("decision", distinct=True))
            .aggregate(max_count=Max("count"))
        )

        max_direct_count = max_direct_result["max_count"] or 1

        stats["max_values"] = {
            "max_appearances": max_appearances,
            "max_amount": max_amount,
            "max_orgs": max_orgs,
            "max_direct_count": max_direct_count,
        }

        logger.info(
            f"Max values - appearances: {max_appearances}, amount: {max_amount}, "
            f"orgs: {max_orgs}, direct_count: {max_direct_count}"
        )

        # === SOPHISTICATED MODE: Need full statistics ===
        if not use_simple:
            strategy = self.config.normalization_strategy
            stats["strategy"] = strategy
            stats["features"] = {}

            # Frequency statistics
            freq_agg = AFMEntity.objects.aggregate(
                min_val=Min("total_appearances"),
                max_val=Max("total_appearances"),
                avg_val=Avg("total_appearances"),
                std_val=StdDev("total_appearances"),
            )
            stats["features"]["frequency"] = self._build_feature_stats(
                "frequency", freq_agg, strategy
            )

            # Amount statistics
            amount_per_entity = list(
                DecisionAmountField.objects.filter(amount__isnull=False)
                .values("associated_relationship__entity_id")
                .annotate(total=Sum("amount"))
                .values_list("total", flat=True)
            )

            if amount_per_entity:
                amount_values = [float(a) for a in amount_per_entity]
                amount_agg = {
                    "min_val": min(amount_values),
                    "max_val": max(amount_values),
                    "avg_val": sum(amount_values) / len(amount_values),
                    "std_val": (
                        float(np.std(amount_values)) if len(amount_values) > 1 else 0.0
                    ),
                }
            else:
                amount_agg = {"min_val": 0, "max_val": 1, "avg_val": 0, "std_val": 1}

            stats["features"]["amount"] = self._build_feature_stats(
                "amount", amount_agg, strategy
            )

            # Organization statistics
            org_counts_per_entity = list(
                DecisionEntityRelationship.objects.values("entity_id")
                .annotate(org_count=Count("decision__organization", distinct=True))
                .values_list("org_count", flat=True)
            )

            if org_counts_per_entity:
                org_agg = {
                    "min_val": min(org_counts_per_entity),
                    "max_val": max(org_counts_per_entity),
                    "avg_val": sum(org_counts_per_entity) / len(org_counts_per_entity),
                    "std_val": (
                        float(np.std(org_counts_per_entity))
                        if len(org_counts_per_entity) > 1
                        else 0.0
                    ),
                }
            else:
                org_agg = {"min_val": 0, "max_val": 1, "avg_val": 0, "std_val": 1}

            stats["features"]["organization"] = self._build_feature_stats(
                "organization", org_agg, strategy
            )

            # Direct assignment count statistics
            direct_counts_per_entity = list(
                DecisionEntityRelationship.objects.filter(
                    decision__classification__is_direct_assignment=True
                )
                .values("entity_id")
                .annotate(count=Count("decision", distinct=True))
                .values_list("count", flat=True)
            )

            if direct_counts_per_entity:
                direct_agg = {
                    "min_val": min(direct_counts_per_entity),
                    "max_val": max(direct_counts_per_entity),
                    "avg_val": sum(direct_counts_per_entity)
                    / len(direct_counts_per_entity),
                    "std_val": (
                        float(np.std(direct_counts_per_entity))
                        if len(direct_counts_per_entity) > 1
                        else 0.0
                    ),
                }
            else:
                direct_agg = {"min_val": 0, "max_val": 1, "avg_val": 0, "std_val": 1}

            stats["features"]["direct_assignment_count"] = self._build_feature_stats(
                "direct_assignment_count", direct_agg, strategy
            )

            # Direct assignment percentage (fixed range 0-100)
            stats["features"]["direct_assignment_percentage"] = {
                "min": 0,
                "max": 100,
                "mean": 50,
                "std": 25,
                "median": 50,
                "iqr": 50,
                "min_log": 0,
                "max_log": math.log1p(100),
            }

        return stats

    def _build_feature_stats(
        self, feature_name: str, aggregation: Dict[str, Any], strategy: str
    ) -> Dict[str, float]:
        """
        Build feature statistics dictionary from aggregation results.

        Args:
            feature_name: Name of the feature
            aggregation: Dict with min_val, max_val, avg_val, std_val
            strategy: Normalization strategy

        Returns:
            Dict with statistics needed for the strategy
        """
        min_val = float(aggregation.get("min_val") or 0)
        max_val = float(aggregation.get("max_val") or 1)
        mean_val = float(aggregation.get("avg_val") or 0)
        std_val = float(aggregation.get("std_val") or 1)

        # Ensure max > min
        if max_val == min_val:
            max_val = min_val + 1

        # Ensure std > 0
        if std_val == 0:
            std_val = 1.0

        stats = {
            "min": min_val,
            "max": max_val,
            "mean": mean_val,
            "std": std_val,
        }

        # Add median and IQR if using robust normalization
        # (These would require more complex queries, so we'll estimate)
        if strategy == NormalizationStrategy.ROBUST:
            # Estimate median as mean (not perfect but avoids expensive query)
            # Estimate IQR as ~1.35 * std (relationship for normal distribution)
            stats["median"] = mean_val
            stats["iqr"] = 1.35 * std_val if std_val > 0 else 1.0
        else:
            stats["median"] = mean_val
            stats["iqr"] = max_val - min_val

        # Add log-transformed stats if using log normalization
        if strategy == NormalizationStrategy.LOG:
            stats["min_log"] = math.log1p(max(0, min_val))
            stats["max_log"] = math.log1p(max(0, max_val))
        else:
            stats["min_log"] = 0
            stats["max_log"] = 1

        return stats

    def _check_eligibility(self, entity: AFMEntity, metrics: Dict[str, Any]) -> bool:
        """
        Check if entity meets minimum thresholds.

        Also filters out entities that should never be retried.
        """
        # Check if already successfully fetched
        if entity.gemi_lookup_success and entity.gemi_companies_count > 0:
            return False  # Already have data, no need to fetch

        # Check if too many failures
        if entity.error_count >= self.config.never_retry_after_failures:
            return False

        # Check if recent failure (respect retry delay)
        if entity.gemi_lookup_attempted and not entity.gemi_lookup_success:
            days_since_attempt = (timezone.now() - entity.gemi_lookup_attempted).days
            if days_since_attempt < self.config.retry_failed_after_days:
                return False  # Too soon to retry

        # Check minimum thresholds
        if metrics["appearances"] < self.config.min_appearances:
            return False

        if metrics["total_amount"] < self.config.min_total_amount:
            return False

        if metrics["unique_orgs"] < self.config.min_unique_organizations:
            return False

        if metrics["direct_assignment_count"] < self.config.min_direct_assignments:
            return False

        return True

    def _is_recent(self, entity: AFMEntity) -> bool:
        """Check if entity has been seen recently."""
        if not entity.last_seen:
            return False

        threshold_date = timezone.now() - timedelta(
            days=self.config.recency_days_threshold
        )
        return entity.last_seen >= threshold_date

    def _assign_priority_ranks(self):
        """
        Assign priority ranks to eligible entities.

        Rank 1 = highest priority (highest score), 2 = second highest, etc.
        """
        eligible_scores = AFMEntityScore.objects.filter(is_eligible=True).order_by(
            "-total_score"
        )

        rank = 1
        for score in eligible_scores:
            score.fetch_priority = rank
            score.save(update_fields=["fetch_priority"])
            rank += 1

        logger.info(f"Assigned priority ranks to {rank - 1} eligible entities")

    def get_top_entities(
        self, limit: int = 100, only_eligible: bool = True, exclude_fetched: bool = True
    ) -> List[Tuple[AFMEntity, AFMEntityScore]]:
        """
        Get top-scored entities.

        Args:
            limit: Maximum number of entities to return
            only_eligible: Only return eligible entities
            exclude_fetched: Exclude entities with successful GEMI data

        Returns:
            List of (entity, score) tuples ordered by score descending
        """
        queryset = AFMEntityScore.objects.select_related("entity")

        if only_eligible:
            queryset = queryset.filter(is_eligible=True)

        if exclude_fetched:
            queryset = queryset.filter(
                Q(entity__gemi_lookup_success=False)
                | Q(entity__gemi_lookup_attempted__isnull=True)
            )

        queryset = queryset.order_by("-total_score")[:limit]

        return [(score.entity, score) for score in queryset]
