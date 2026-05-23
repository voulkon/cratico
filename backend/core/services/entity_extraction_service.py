import re
from typing import Any, Dict, List

from core.models.decisions import Decision
from core.models.entities import (
    AFMEntity,
    DecisionEntityRelationship,
    EntityRole,
    EntityType,
)
from core.services.gemi_service import GemiService
from django.utils import timezone
from loguru import logger


class EntityExtractionService:
    """Service for extracting and managing AFM entities from decisions."""

    def __init__(self):
        self.afm_pattern = re.compile(r"^\d{9}$")

    def extract_afm_entities_from_decision(
        self,
        decision: Decision,
        save_relationships: bool = True,
        skip_existing: bool = False,
    ) -> List[AFMEntity]:
        """
        Extract AFM entities from a single decision's extra field values.

        Args:
            decision: The decision to extract entities from
            save_relationships: Whether to save decision-entity relationships

        Returns:
            List of AFMEntity objects created or found
        """

        if skip_existing:
            # Check if we've already processed this decision
            existing_count = DecisionEntityRelationship.objects.filter(
                decision=decision
            ).count()
            if existing_count > 0:
                logger.debug(
                    f"Decision {decision.ada} already processed, found {existing_count} relationships"
                )
                return []

        if not decision.extra_field_values_json:
            logger.debug(f"Decision {decision.ada} has no extra field values")
            return []

        afm_entities = []
        efv = decision.extra_field_values_json

        # Extract AFM entities from various fields
        afm_extractions = self._extract_afms_from_efv(efv)

        for extraction in afm_extractions:
            afm = extraction["afm"]
            role = extraction["role"]
            parent_key_path = extraction["parent_key_path"]
            raw_context = extraction["raw_context"]

            # Skip if this is an organization role
            if role == EntityRole.ORGANIZATION:
                logger.debug(f"Skipping AFM {afm} with organization role")
                continue

            # Check afmType filtering
            if not self._should_process_afm(raw_context):
                logger.debug(f"Skipping AFM {afm} due to afmType filtering")
                continue

            # Create or get AFM entity
            afm_entity = self._get_or_create_afm_entity(afm)
            afm_entities.append(afm_entity)

            # Save relationship if requested
            if save_relationships:
                self._create_decision_entity_relationship(
                    decision, afm_entity, role, parent_key_path, raw_context
                )

        logger.info(
            f"Extracted {len(afm_entities)} AFM entities from decision {decision.ada}"
        )
        return afm_entities

    def _extract_afms_from_efv(self, efv: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract AFM values from extra field values with context."""
        extractions = []

        # Define AFM extraction patterns
        afm_patterns = [
            # Sponsor AFM
            {"field": "sponsorAFMName", "role": EntityRole.SPONSOR, "nested": False},
            # Grantor/Grantee in contracts
            {
                "field": "grantor",
                "role": EntityRole.GRANTOR,
                "nested": True,
                "afm_field": "afm",
            },
            {
                "field": "grantee",
                "role": EntityRole.GRANTEE,
                "nested": True,
                "afm_field": "afm",
            },
            # Donations
            {
                "field": "donationGiver",
                "role": EntityRole.DONATION_GIVER,
                "nested": True,
                "afm_field": "afm",
            },
            {
                "field": "donationReceiver",
                "role": EntityRole.DONATION_RECEIVER,
                "nested": True,
                "afm_field": "afm",
            },
            # Person arrays
            {
                "field": "person",
                "role": EntityRole.PERSON,
                "nested": True,
                "is_array": True,
                "afm_field": "afm",
            },
        ]

        for pattern in afm_patterns:
            field_name = pattern["field"]

            if field_name not in efv:
                continue

            field_value = efv[field_name]

            if pattern.get("is_array", False):
                # Handle array fields like person[]
                if isinstance(field_value, list):
                    for i, item in enumerate(field_value):
                        if isinstance(item, dict):
                            afm = item.get(pattern.get("afm_field", "afm"))
                            if self._is_valid_afm(afm):
                                extractions.append(
                                    {
                                        "afm": afm,
                                        "role": pattern["role"],
                                        "parent_key_path": f"{field_name}[{i}]",
                                        "raw_context": item,
                                    }
                                )
            elif pattern.get("nested", False):
                # Handle nested objects
                if isinstance(field_value, dict):
                    afm = field_value.get(pattern.get("afm_field", "afm"))
                    if self._is_valid_afm(afm):
                        extractions.append(
                            {
                                "afm": afm,
                                "role": pattern["role"],
                                "parent_key_path": field_name,
                                "raw_context": field_value,
                            }
                        )
            else:
                # Handle direct AFM fields
                if self._is_valid_afm(field_value):
                    extractions.append(
                        {
                            "afm": field_value,
                            "role": pattern["role"],
                            "parent_key_path": field_name,
                            "raw_context": {field_name: field_value},
                        }
                    )

        return extractions

    def _is_valid_afm(self, afm: Any) -> bool:
        """Check if a value is a valid AFM."""
        if not afm:
            return False

        afm_str = str(afm).strip()
        return bool(self.afm_pattern.match(afm_str))

    def _should_process_afm(self, raw_context: Dict[str, Any]) -> bool:
        """
        Check if we should process this AFM based on afmType filtering.

        Rules:
        - If afmType doesn't exist -> process
        - If afmType exists and is "EL" -> process
        - If afmType exists and is not "EL" -> skip
        """
        afm_type = raw_context.get("afmType")

        if afm_type is None:
            return True  # No afmType field, proceed

        return afm_type == "EL"  # Only process if it's "EL"

    def _get_or_create_afm_entity(self, afm: str) -> AFMEntity:
        """Get or create an AFMEntity."""
        afm_entity, created = AFMEntity.objects.get_or_create(
            afm=afm,
            defaults={"entity_type": EntityType.UNKNOWN, "total_appearances": 0},
        )

        # Update appearance count
        afm_entity.total_appearances += 1
        afm_entity.save(update_fields=["total_appearances", "last_seen"])

        if created:
            logger.debug(f"Created new AFMEntity for {afm}")
        else:
            logger.debug(f"Found existing AFMEntity for {afm}")

        return afm_entity

    def _create_decision_entity_relationship(
        self,
        decision: Decision,
        entity: AFMEntity,
        role: str,
        parent_key_path: str,
        raw_context: Dict[str, Any],
    ) -> DecisionEntityRelationship:
        """Create a decision-entity relationship."""
        relationship, created = DecisionEntityRelationship.objects.get_or_create(
            decision=decision,
            entity=entity,
            role=role,
            parent_key_path=parent_key_path,
            defaults={"raw_context": raw_context, "confidence_score": 1.0},
        )

        if created:
            logger.debug(
                f"Created relationship: {decision.ada} -> {entity.afm} ({role})"
            )

        return relationship

    def get_entities_needing_company_data(self, limit: int = 100) -> List[AFMEntity]:
        """
        Get AFM entities that need company data fetching.

        Filters:
        - Not attempted GEMI lookup yet OR failed lookup more than 7 days ago
        - Not organization role in any relationship
        - Has valid AFM format
        - Doesn't already have company data
        """
        from datetime import timedelta

        from core.models.companies import Company
        from django.db.models import Exists, OuterRef, Q

        # Subquery to check if entity has organization role
        has_org_role = DecisionEntityRelationship.objects.filter(
            entity=OuterRef("pk"), role=EntityRole.ORGANIZATION
        )

        # Subquery to check if company already exists
        has_company = Company.objects.filter(afm=OuterRef("afm"))

        # Calculate cutoff date for retry attempts (7 days ago)
        retry_cutoff = timezone.now() - timedelta(days=7)

        entities = (
            AFMEntity.objects.filter(
                # Valid AFM format (should be enforced by validator but double-check)
                afm__regex=r"^\d{9}$"
            )
            .exclude(
                # Exclude entities with organization role
                Exists(has_org_role)
            )
            .exclude(
                # Exclude entities that already have company data
                Exists(has_company)
            )
            .filter(
                Q(
                    # Never attempted GEMI lookup
                    Q(gemi_lookup_attempted__isnull=True)
                    |
                    # Failed lookup and enough time has passed for retry
                    Q(gemi_lookup_success=False, gemi_lookup_attempted__lt=retry_cutoff)
                )
            )
            .order_by("first_seen")[:limit]
        )

        return list(entities)

    def fetch_company_data_for_entities(
        self,
        entities: List[AFMEntity],
        max_requests_per_minute: int = 6,
        retry_failed_after_days: int = 7,
    ) -> Dict[str, Any]:
        """
        Fetch company data for a list of AFM entities.

        Args:
            entities: List of AFMEntity objects to fetch
            max_requests_per_minute: Rate limit for API calls
            retry_failed_after_days: Days before retrying a failed lookup (default: 7)

        Returns:
            Statistics about the operation
        """
        stats = {
            "processed": 0,
            "successful": 0,
            "failed": 0,
            "companies_found": 0,
            "skipped_cached": 0,  # New: track cached failures
            "errors": [],
        }

        for entity in entities:
            try:
                logger.info(f"Fetching company data for AFM: {entity.afm}")

                companies = GemiService.fetch_companies_by_afm(
                    entity.afm,
                    update_entity=True,
                    max_requests_per_minute=max_requests_per_minute,
                    retry_failed_after_days=retry_failed_after_days,
                )

                stats["processed"] += 1

                # Check if this was a cached skip (no companies + already attempted)
                if (
                    not companies
                    and entity.gemi_lookup_attempted
                    and not entity.gemi_lookup_success
                ):
                    from django.utils import timezone

                    time_since = timezone.now() - entity.gemi_lookup_attempted
                    days_since = time_since.total_seconds() / (60 * 60 * 24)
                    if days_since < retry_failed_after_days:
                        stats["skipped_cached"] += 1
                        logger.debug(
                            f"Skipped cached failure for AFM {entity.afm} ({days_since:.1f} days old)"
                        )
                        continue

                stats["companies_found"] += len(companies)

                if companies:
                    stats["successful"] += 1
                    # Update entity type if we found companies
                    entity.entity_type = EntityType.COMPANY
                    entity.save(update_fields=["entity_type"])

                    logger.success(
                        f"Found {len(companies)} companies for AFM {entity.afm}"
                    )
                else:
                    stats["failed"] += 1
                    logger.info(f"No companies found for AFM {entity.afm}")

            except Exception as e:
                stats["processed"] += 1
                stats["failed"] += 1
                stats["errors"].append(f"AFM {entity.afm}: {str(e)}")
                logger.error(f"Error fetching company data for AFM {entity.afm}: {e}")

        logger.info(f"Company data fetch completed: {stats}")
        return stats
