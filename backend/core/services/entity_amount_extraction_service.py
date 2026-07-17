"""
Unified Entity and Amount Extraction Service

This is the SINGLE SOURCE OF TRUTH for extracting:
- AFM entities (sponsors, grantees, contractors, etc.)
- Amounts (with VAT, without VAT, budgets, etc.)

Both are extracted together because amounts often need to be linked
to the entity relationships they belong to.

Replaces:
- AFMExtractionService (afm_extractor.py) - DEPRECATED
- EntityExtractionService (entity_extraction_service.py) - DEPRECATED
- DecisionImporter.extract_and_save_amounts() - MOVED HERE
"""

import decimal
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from core.models.decisions import Decision
from core.models.entities import (
    AFMEntity,
    DecisionAmountField,
    DecisionEntityRelationship,
    EntityRole,
    EntityType,
)
from django.db import transaction
from django.utils import timezone
from loguru import logger


class ExtractionApproach(Enum):
    """How to find AFMs in the data."""

    KNOWN_FIELDS = "known_fields"  # Only extract from known field names
    HEURISTIC = "heuristic"  # Search for AFM-like patterns anywhere
    HYBRID = "hybrid"  # Known fields first, then heuristic for remainder


@dataclass
class ExtractionResult:
    """Result of extraction for a single decision."""

    decision_ada: str
    entities_found: int
    entities_created: int
    amounts_found: int
    amounts_created: int
    extraction_attempted_at: timezone.datetime
    had_extractable_content: bool
    errors: List[str]


class EntityAmountExtractionService:
    """
    Unified service for extracting AFM entities and amounts from decisions.

    This is the single source of truth - all other extraction code should
    delegate to this service.
    """

    # Known field names that contain AFM data
    KNOWN_AFM_FIELDS = {
        # Sponsor fields
        "sponsorAFMName": EntityRole.SPONSOR,
        "sponsor": EntityRole.SPONSOR,
        # Grantee/recipient fields
        "grantee": EntityRole.GRANTEE,
        "granteeName": EntityRole.GRANTEE,
        # Grantor fields
        "grantor": EntityRole.GRANTOR,
        "grantorName": EntityRole.GRANTOR,
        # Contractor fields
        "awardedPerson": EntityRole.CONTRACTOR,
        "contractorAFM": EntityRole.CONTRACTOR,
        # Generic person fields
        "person": EntityRole.PERSON,
        "personAFM": EntityRole.PERSON,
        # Organization fields (usually skipped)
        "organizationAFM": EntityRole.ORGANIZATION,
    }

    # Known field names that contain amount data
    KNOWN_AMOUNT_FIELDS = {
        "amountWithVAT": "with_vat",
        "amountWithoutVAT": "without_vat",
        "amount": "generic",
        "budgetAmount": "budget",
        "contractAmount": "contract",
        "amountWithKae": "kae_breakdown",
        "awardAmount": "award",
        "expenseAmount": "expense",
    }

    # Heuristic keywords for AFM detection (used in HEURISTIC mode)
    AFM_KEYWORDS = ["afm", "αφμ", "tax", "vat", "tin", "taxid", "vatid"]

    def __init__(self, approach: ExtractionApproach = ExtractionApproach.KNOWN_FIELDS):
        """
        Initialize the extraction service.

        Args:
            approach: How to find AFMs - KNOWN_FIELDS is recommended for production
        """
        self.approach = approach
        self.afm_pattern = re.compile(r"^\d{9}$")

    def extract_from_decision(
        self,
        decision: Decision,
        save_to_db: bool = True,
        skip_if_existing: bool = False,
    ) -> ExtractionResult:
        """
        Extract both entities and amounts from a decision.

        Args:
            decision: The decision to extract from
            save_to_db: Whether to save results to database
            skip_if_existing: Skip if relationships/amounts already exist (idempotent mode)

        Returns:
            ExtractionResult with details of what was found/created
        """
        now = timezone.now()
        result = ExtractionResult(
            decision_ada=decision.ada,
            entities_found=0,
            entities_created=0,
            amounts_found=0,
            amounts_created=0,
            extraction_attempted_at=now,
            had_extractable_content=False,
            errors=[],
        )

        # Check if already has relationships (idempotent mode)
        if skip_if_existing:
            existing_entities = decision.entity_relationships.count()
            existing_amounts = decision.amount_fields.count()
            if existing_entities > 0 or existing_amounts > 0:
                logger.debug(
                    f"Decision {decision.ada} already has {existing_entities} entities "
                    f"and {existing_amounts} amounts, skipping"
                )
                result.entities_created = existing_entities
                result.amounts_created = existing_amounts
                return result

        # Check if there's any data to extract from
        if not decision.extra_field_values_json:
            logger.debug(f"Decision {decision.ada} has no extra field values")
            return result

        result.had_extractable_content = True
        efv = decision.extra_field_values_json

        try:
            with transaction.atomic():
                # Step 1: Extract entities
                entity_extractions = self._extract_entities(efv)
                result.entities_found = len(entity_extractions)

                entity_relationships = []
                if save_to_db and entity_extractions:
                    entity_relationships = self._save_entities(
                        decision, entity_extractions
                    )
                    result.entities_created = len(entity_relationships)

                # Step 2: Extract amounts
                amount_extractions = self._extract_amounts(efv, decision.ada)
                result.amounts_found = len(amount_extractions)

                if save_to_db and amount_extractions:
                    amounts_created = self._save_amounts(
                        decision, amount_extractions, entity_relationships
                    )
                    result.amounts_created = amounts_created

                logger.debug(
                    f"Decision {decision.ada}: extracted {result.entities_created} entities, "
                    f"{result.amounts_created} amounts"
                )

        except Exception as e:
            result.errors.append(str(e))
            logger.error(f"Error extracting from decision {decision.ada}: {e}")

        return result

    def _extract_entities(self, efv: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract AFM entities from extra field values.

        Returns list of dicts with: afm, role, parent_key_path, raw_context
        """
        if self.approach == ExtractionApproach.KNOWN_FIELDS:
            return self._extract_entities_known_fields(efv)
        elif self.approach == ExtractionApproach.HEURISTIC:
            return self._extract_entities_heuristic(efv)
        else:  # HYBRID
            known = self._extract_entities_known_fields(efv)
            # Could add heuristic here for fields not covered
            return known

    def _extract_entities_known_fields(
        self, efv: Dict[str, Any], parent_path: str = ""
    ) -> List[Dict[str, Any]]:
        """Extract entities from known field names."""
        extractions = []

        if isinstance(efv, dict):
            for key, value in efv.items():
                current_path = f"{parent_path}.{key}" if parent_path else key

                # Check if this is a known AFM field
                if key in self.KNOWN_AFM_FIELDS:
                    role = self.KNOWN_AFM_FIELDS[key]
                    afms = self._extract_afms_from_value(value)

                    for afm_data in afms:
                        extractions.append(
                            {
                                "afm": afm_data["afm"],
                                "name": afm_data.get("name"),
                                "role": role,
                                "parent_key_path": current_path,
                                "raw_context": (
                                    value if isinstance(value, dict) else {key: value}
                                ),
                            }
                        )

                # Recurse into nested structures
                if isinstance(value, (dict, list)):
                    extractions.extend(
                        self._extract_entities_known_fields(value, current_path)
                    )

        elif isinstance(efv, list):
            for i, item in enumerate(efv):
                current_path = f"{parent_path}[{i}]"
                extractions.extend(
                    self._extract_entities_known_fields(item, current_path)
                )

        return extractions

    def _extract_entities_heuristic(
        self, efv: Dict[str, Any], parent_path: str = ""
    ) -> List[Dict[str, Any]]:
        """Extract entities using keyword heuristics (more aggressive)."""
        extractions = []

        if isinstance(efv, dict):
            for key, value in efv.items():
                current_path = f"{parent_path}.{key}" if parent_path else key
                key_lower = key.lower()

                # Check if key contains AFM-like keywords
                if any(kw in key_lower for kw in self.AFM_KEYWORDS):
                    afms = self._extract_afms_from_value(value)
                    role = self._infer_role_from_path(current_path)

                    for afm_data in afms:
                        extractions.append(
                            {
                                "afm": afm_data["afm"],
                                "name": afm_data.get("name"),
                                "role": role,
                                "parent_key_path": current_path,
                                "raw_context": (
                                    value if isinstance(value, dict) else {key: value}
                                ),
                            }
                        )

                # Recurse
                if isinstance(value, (dict, list)):
                    extractions.extend(
                        self._extract_entities_heuristic(value, current_path)
                    )

        elif isinstance(efv, list):
            for i, item in enumerate(efv):
                current_path = f"{parent_path}[{i}]"
                extractions.extend(self._extract_entities_heuristic(item, current_path))

        return extractions

    def _extract_afms_from_value(self, value: Any) -> List[Dict[str, Any]]:
        """Extract AFM(s) from a value, handling various formats."""
        results = []

        if isinstance(value, str) and self._is_valid_afm(value):
            results.append({"afm": value, "name": None})

        elif isinstance(value, dict):
            # Look for afm field in dict
            afm = value.get("afm") or value.get("AFM") or value.get("afmNumber")
            name = (
                value.get("name") or value.get("afmName") or value.get("sponsorAFMName")
            )

            if afm and self._is_valid_afm(str(afm)):
                results.append({"afm": str(afm), "name": name})

        elif isinstance(value, list):
            for item in value:
                results.extend(self._extract_afms_from_value(item))

        return results

    def _extract_amounts(
        self, efv: Dict[str, Any], decision_ada: str, parent_path: str = ""
    ) -> List[Dict[str, Any]]:
        """Extract amount fields from extra field values."""
        extractions = []

        if isinstance(efv, dict):
            # Check for amount fields at this level
            amount_info = self._detect_amounts_in_dict(efv, parent_path)
            extracted_fields = set()

            if amount_info and parent_path:  # Skip root-level containers
                extractions.append(
                    {
                        "parent_path": parent_path,
                        "amount_info": amount_info,
                        "raw_data": efv,
                    }
                )
                # Track which fields had amounts extracted to avoid recursing into them
                extracted_fields = set(amount_info["fields_found"])

            # Recurse into nested structures (but skip fields we already extracted amounts from)
            for key, value in efv.items():
                # Skip recursion into amount fields we've already processed
                if key in extracted_fields:
                    continue

                new_path = f"{parent_path}.{key}" if parent_path else key
                if isinstance(value, (dict, list)):
                    extractions.extend(
                        self._extract_amounts(value, decision_ada, new_path)
                    )

        elif isinstance(efv, list):
            for i, item in enumerate(efv):
                new_path = f"{parent_path}[{i}]"
                extractions.extend(self._extract_amounts(item, decision_ada, new_path))

        return extractions

    def _detect_amounts_in_dict(self, data: Dict, parent_path: str) -> Optional[Dict]:
        """Detect amount fields in a dictionary."""
        amounts = []
        currencies = []
        fields_found = []
        structure_types = []

        for key, value in data.items():
            if key in self.KNOWN_AMOUNT_FIELDS:
                amount_type = self.KNOWN_AMOUNT_FIELDS[key]

                if isinstance(value, dict):
                    # Nested amount like {"amount": 1000, "currency": "EUR"}
                    amount = value.get("amount")
                    currency = value.get("currency", "EUR")
                    if amount is not None:
                        amounts.append(amount)
                        currencies.append(currency)
                        fields_found.append(key)
                        structure_types.append(amount_type)

                elif isinstance(value, (int, float)):
                    amounts.append(value)
                    currencies.append("EUR")
                    fields_found.append(key)
                    structure_types.append(amount_type)

                elif isinstance(value, list):
                    # List of amounts (e.g., amountWithKae)
                    for i, item in enumerate(value):
                        if isinstance(item, dict):
                            amount = item.get("amount") or item.get("amountWithVAT")
                            currency = item.get("currency", "EUR")
                            if amount is not None:
                                amounts.append(amount)
                                currencies.append(currency)
                                fields_found.append(f"{key}[{i}]")
                                structure_types.append(f"{amount_type}_item")

        if amounts:
            return {
                "amounts": amounts,
                "currencies": currencies,
                "fields_found": fields_found,
                "structure_types": structure_types,
            }
        return None

    def _save_entities(
        self, decision: Decision, extractions: List[Dict[str, Any]]
    ) -> List[DecisionEntityRelationship]:
        """Save extracted entities to database."""
        relationships = []

        # Sort by AFM to ensure all workers lock AFMEntity rows in the same
        # order, preventing deadlocks when concurrent decisions reference the
        # same entities in different JSON orderings.
        sorted_extractions = sorted(extractions, key=lambda e: e["afm"])

        for extraction in sorted_extractions:
            afm = extraction["afm"]
            role = extraction["role"]

            # Skip organization AFMs
            if role == EntityRole.ORGANIZATION:
                logger.debug(f"Skipping organization AFM {afm}")
                continue

            # Skip based on afmType if present
            if not self._should_process_afm(extraction.get("raw_context", {})):
                continue

            # Get or create AFM entity
            entity_type = self._determine_entity_type(extraction.get("raw_context", {}))
            afm_entity, created = AFMEntity.objects.get_or_create(
                afm=afm,
                defaults={
                    "name": extraction.get("name"),
                    "entity_type": entity_type,
                    "first_seen": timezone.now(),
                    "last_seen": timezone.now(),
                    "total_appearances": 1,
                },
            )

            if not created:
                # Update existing entity
                afm_entity.last_seen = timezone.now()
                afm_entity.total_appearances += 1
                if extraction.get("name") and not afm_entity.name:
                    afm_entity.name = extraction["name"]
                afm_entity.save(
                    update_fields=["last_seen", "total_appearances", "name"]
                )

            # Create relationship
            relationship, rel_created = (
                DecisionEntityRelationship.objects.get_or_create(
                    decision=decision,
                    entity=afm_entity,
                    parent_key_path=extraction["parent_key_path"],
                    defaults={
                        "role": role,
                        "raw_context": extraction.get("raw_context"),
                    },
                )
            )

            # Always include in relationships list (for linking), not just newly created
            relationships.append(relationship)

        return relationships

    def _save_amounts(
        self,
        decision: Decision,
        extractions: List[Dict[str, Any]],
        entity_relationships: List[DecisionEntityRelationship],
    ) -> int:
        """Save extracted amounts to database and link to entities."""
        created_count = 0

        for extraction in extractions:
            parent_path = extraction["parent_path"]
            amount_info = extraction["amount_info"]

            for i, amount in enumerate(amount_info["amounts"]):
                amount_field, created = DecisionAmountField.objects.get_or_create(
                    decision=decision,
                    parent_key_path=parent_path,
                    source_field_name=amount_info["fields_found"][i],
                    defaults={
                        "amount": (
                            decimal.Decimal(str(amount)) if amount is not None else None
                        ),
                        "currency": (
                            amount_info["currencies"][i]
                            if i < len(amount_info["currencies"])
                            else "EUR"
                        ),
                        "structure_type": amount_info["structure_types"][i],
                        "raw_context": extraction["raw_data"],
                    },
                )

                if created:
                    created_count += 1

                # Try to link to entity relationship (check both new and existing amounts)
                if not amount_field.associated_relationship and entity_relationships:
                    matching_rel = self._find_matching_relationship(
                        parent_path, entity_relationships
                    )
                    if matching_rel:
                        amount_field.associated_relationship = matching_rel
                        amount_field.save(update_fields=["associated_relationship"])
                        logger.debug(
                            f"Linked amount {amount_field.source_field_name} to entity {matching_rel.entity.afm}"
                        )

        return created_count

    def _find_matching_relationship(
        self, amount_path: str, relationships: List[DecisionEntityRelationship]
    ) -> Optional[DecisionEntityRelationship]:
        """
        Find the entity relationship that matches this amount's path.

        Matching strategies (in order of preference):
        1. Exact container match (e.g., sponsor[0].expenseAmount → sponsor[0])
        2. Direct assignment (single entity + root-level amount like awardAmount)
        """
        # Strategy 1: Exact container match
        # Extract container from amount path (e.g., "sponsor[0].amountWithVAT" → "sponsor[0]")
        amount_container = (
            amount_path.rsplit(".", 1)[0] if "." in amount_path else amount_path
        )

        for rel in relationships:
            # Extract container from relationship path
            rel_container = (
                rel.parent_key_path.rsplit(".", 1)[0]
                if "." in rel.parent_key_path
                else rel.parent_key_path
            )

            if amount_container == rel_container:
                return rel

        # Strategy 2: Direct assignment pattern
        # If amount is at root level (like "awardAmount", "contractAmount")
        # and there's exactly ONE entity, link them together
        if self._is_direct_assignment_amount(amount_path) and len(relationships) == 1:
            logger.debug(
                f"Direct assignment linking: {amount_path} → {relationships[0].parent_key_path}"
            )
            return relationships[0]

        return None

    def _is_direct_assignment_amount(self, amount_path: str) -> bool:
        """
        Check if this is a root-level "direct assignment" amount field.

        These are amounts that typically apply to the entire decision/contract
        and should be linked to a single entity if present.

        Examples: awardAmount, contractAmount, budgetAmount
        """
        # Root-level amounts (no array index, no nested path)
        if "[" in amount_path or "." in amount_path:
            return False

        # Check if it's one of the known direct assignment amount types
        direct_assignment_fields = {
            "awardAmount",
            "contractAmount",
            "budgetAmount",
            "amountWithVAT",  # When at root level
            "amountWithoutVAT",  # When at root level
        }

        return amount_path in direct_assignment_fields

    def _is_valid_afm(self, value: Any) -> bool:
        """Check if value is a valid 9-digit AFM."""
        if not value:
            return False
        afm_str = str(value).strip()
        return bool(self.afm_pattern.match(afm_str))

    def _should_process_afm(self, raw_context: Dict) -> bool:
        """Check if AFM should be processed based on afmType."""
        if not isinstance(raw_context, dict):
            return True

        afm_type = raw_context.get("afmType")
        if afm_type is None:
            return True

        # Skip organization types
        skip_types = ["PublicOrganization", "Organization"]
        return afm_type not in skip_types

    def _determine_entity_type(self, raw_context: Dict) -> EntityType:
        """Determine entity type from context."""
        if not isinstance(raw_context, dict):
            return EntityType.UNKNOWN

        afm_type = raw_context.get("afmType", "").lower()

        if "person" in afm_type or "physical" in afm_type:
            return EntityType.PERSON
        elif "company" in afm_type or "legal" in afm_type:
            return EntityType.COMPANY
        elif "org" in afm_type:
            return EntityType.ORGANIZATION

        return EntityType.UNKNOWN

    def _infer_role_from_path(self, path: str) -> EntityRole:
        """Infer entity role from field path (for heuristic mode)."""
        path_lower = path.lower()

        if "sponsor" in path_lower:
            return EntityRole.SPONSOR
        elif "grantee" in path_lower or "recipient" in path_lower:
            return EntityRole.GRANTEE
        elif "grantor" in path_lower:
            return EntityRole.GRANTOR
        elif "contractor" in path_lower or "awarded" in path_lower:
            return EntityRole.CONTRACTOR
        elif "person" in path_lower:
            return EntityRole.PERSON

        return EntityRole.OTHER


# Convenience function for backward compatibility
def extract_entities_and_amounts(
    decision: Decision,
    save_to_db: bool = True,
    skip_if_existing: bool = False,
    approach: ExtractionApproach = ExtractionApproach.KNOWN_FIELDS,
) -> ExtractionResult:
    """
    Extract entities and amounts from a decision.

    Args:
        decision: The decision to extract from
        save_to_db: Whether to save results to database
        skip_if_existing: Skip if relationships/amounts already exist (idempotent mode)
        approach: How to find AFMs - KNOWN_FIELDS (default), HEURISTIC, or HYBRID

    Returns:
        ExtractionResult with details of what was found/created
    """
    service = EntityAmountExtractionService(approach=approach)
    return service.extract_from_decision(
        decision, save_to_db=save_to_db, skip_if_existing=skip_if_existing
    )
