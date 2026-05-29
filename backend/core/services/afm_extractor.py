import json
from collections import defaultdict
from typing import Any, Dict, List

from core.models.decisions import Decision
from core.models.entities import (
    AFMEntity,
    DecisionEntityRelationship,
    EntityRole,
    EntityType,
)
from django.db import transaction
from loguru import logger


class AFMExtractionService:
    """
    Reusable service for extracting AFM entities from decision data.
    Can be used in import pipelines or standalone analysis.
    """

    def __init__(self, batch_size: int = 100):
        self.batch_size = batch_size
        self.extraction_stats = {
            "decisions_processed": 0,
            "entities_found": 0,
            "entities_created": 0,
            "relationships_created": 0,
            "validation_failures": 0,
        }

        # Role mapping for parent keys to EntityRole
        self.role_mapping = {
            "sponsorAFMName": EntityRole.SPONSOR,
            "org": EntityRole.ORGANIZATION,
            "grantor": EntityRole.GRANTOR,
            "grantee": EntityRole.GRANTEE,
            "donationGiver": EntityRole.DONATION_GIVER,
            "donationReceiver": EntityRole.DONATION_RECEIVER,
        }

        # Priority weights for confidence calculation
        self.priority_weights = {
            "sponsorAFMName": 1.0,
            "org": 0.9,
            "grantor": 0.8,
            "grantee": 0.8,
            "donationGiver": 0.7,
            "donationReceiver": 0.7,
        }

    def extract_afms_from_decision(
        self, decision: Decision, save_to_db: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Extract AFM entities from a single decision.

        Args:
            decision: Decision instance
            save_to_db: Whether to save entities/relationships to database

        Returns:
            List of extracted entity information
        """
        if not decision.extra_field_values_json:
            return []

        self.extraction_stats["decisions_processed"] += 1

        # Find AFM patterns in the decision data
        afm_patterns = self._find_afm_patterns_in_data(
            decision.extra_field_values_json, ""
        )

        extracted_entities = []

        for pattern in afm_patterns:
            entities = self._extract_entities_from_pattern(pattern, decision)
            extracted_entities.extend(entities)

        self.extraction_stats["entities_found"] += len(extracted_entities)

        if save_to_db and extracted_entities:
            self._save_entities_to_database(decision, extracted_entities)

        return extracted_entities

    def extract_afms_from_decisions_batch(
        self, decisions: List[Decision], save_to_db: bool = True
    ) -> Dict[str, Any]:
        """
        Extract AFMs from a batch of decisions.

        Args:
            decisions: List of Decision instances
            save_to_db: Whether to save to database

        Returns:
            Extraction summary statistics
        """
        batch_entities = defaultdict(list)

        for decision in decisions:
            entities = self.extract_afms_from_decision(decision, save_to_db=False)
            if entities:
                batch_entities[decision.ada] = entities

        if save_to_db and batch_entities:
            with transaction.atomic():
                for ada, entities in batch_entities.items():
                    decision = next(d for d in decisions if d.ada == ada)
                    self._save_entities_to_database(decision, entities)

        return {
            "decisions_with_afms": len(batch_entities),
            "total_entities": sum(
                len(entities) for entities in batch_entities.values()
            ),
            "stats": self.extraction_stats.copy(),
        }

    def _find_afm_patterns_in_data(
        self, data: Any, parent_path: str = ""
    ) -> List[Dict]:
        """Find AFM patterns recursively in data structure."""
        patterns = []

        if isinstance(data, dict):
            afm_indicators = self._detect_afm_in_dict(data)

            if afm_indicators:
                parent_key = parent_path.split(".")[-1] if parent_path else "root"
                patterns.append(
                    {
                        "parent_key": parent_key,
                        "afm_fields": afm_indicators,
                        "data": data,
                        "path": parent_path,
                    }
                )

            for key, value in data.items():
                new_path = f"{parent_path}.{key}" if parent_path else key
                patterns.extend(self._find_afm_patterns_in_data(value, new_path))

        elif isinstance(data, list):
            for i, item in enumerate(data):
                new_path = f"{parent_path}[{i}]" if parent_path else f"[{i}]"
                patterns.extend(self._find_afm_patterns_in_data(item, new_path))

        return patterns

    def _detect_afm_in_dict(self, data: Dict[str, Any]) -> List[str]:
        """Detect AFM fields in a dictionary."""
        afm_indicators = []

        if not isinstance(data, dict):
            return afm_indicators

        for key, value in data.items():
            if not isinstance(key, str):
                continue

            key_lower = key.lower()
            afm_keywords = ["afm", "αφμ", "tax", "vat", "tin", "taxid", "vatid"]

            if any(afm_term in key_lower for afm_term in afm_keywords):
                if self._is_valid_afm_format(value):
                    afm_indicators.append(key)

        return afm_indicators

    def _is_valid_afm_format(self, value: Any) -> bool:
        """Check if value looks like a valid AFM."""
        if value is None:
            return False

        if isinstance(value, (int, float)):
            return 100000000 <= value <= 999999999

        if not isinstance(value, str):
            value = str(value)

        cleaned = self._clean_afm_value(value)

        if cleaned.isdigit():
            length = len(cleaned)
            return 8 <= length <= 12

        return False

    def _clean_afm_value(self, value: Any) -> str:
        """Clean AFM value for processing."""
        if value is None:
            return ""

        afm_str = str(value).strip()
        cleaned = (
            afm_str.replace("EL", "")
            .replace("GR", "")
            .replace("-", "")
            .replace(" ", "")
            .replace(".", "")
        )
        return cleaned

    def _extract_entities_from_pattern(
        self, pattern: Dict, decision: Decision
    ) -> List[Dict[str, Any]]:
        """Extract entity information from an AFM pattern."""
        entities = []
        parent_key = pattern["parent_key"]
        data = pattern["data"]

        for afm_field in pattern["afm_fields"]:
            afm_value = self._clean_afm_value(data[afm_field])

            if not self._is_valid_afm_format(afm_value):
                self.extraction_stats["validation_failures"] += 1
                continue

            entity_info = {
                "afm": afm_value,
                "role": self._map_parent_key_to_role(parent_key),
                "parent_key_path": pattern["path"] or parent_key,
                "source_field_name": afm_field,
                "raw_context": data,
                "entity_type": self._detect_entity_type(data),
                "name": self._extract_entity_name(data),
                "confidence": self._calculate_confidence(pattern),
                "decision_ada": decision.ada,
            }
            entities.append(entity_info)

        return entities

    def _map_parent_key_to_role(self, parent_key: str) -> str:
        """Map parent key to EntityRole."""
        # Strip array index suffix like [0], [1], etc. before lookup
        base_key = parent_key.split("[")[0]

        # Handle array patterns like person[0], person[1], etc.
        if base_key == "person":
            return EntityRole.PERSON

        return self.role_mapping.get(base_key, EntityRole.OTHER)

    def _detect_entity_type(self, data: Dict[str, Any]) -> str:
        """Detect if entity is person, company, or organization."""
        data_str = json.dumps(data, ensure_ascii=False).lower()

        # Company indicators
        company_terms = [
            "εταιρ",
            "company",
            "επων",
            "business",
            "corp",
            "ltd",
            "αε",
            "οε",
            "επε",
        ]
        if any(term in data_str for term in company_terms):
            return EntityType.COMPANY

        # Person indicators
        person_terms = ["φυσικ", "person", "individual", "όνομα", "name"]
        if any(term in data_str for term in person_terms):
            return EntityType.PERSON

        # Organization indicators
        org_terms = ["οργαν", "organization", "δήμος", "municipality", "ministry"]
        if any(term in data_str for term in org_terms):
            return EntityType.ORGANIZATION

        return EntityType.UNKNOWN

    def _extract_entity_name(self, data: Dict[str, Any]) -> str:
        """Try to extract entity name from context data."""
        name_fields = ["name", "όνομα", "επωνυμία", "title", "description"]

        for field in name_fields:
            for key, value in data.items():
                if field in key.lower() and isinstance(value, str) and value.strip():
                    return value.strip()[:200]  # Limit length

        return ""

    def _calculate_confidence(self, pattern: Dict) -> float:
        """Calculate confidence score for this extraction."""
        parent_key = pattern["parent_key"]

        # Base confidence
        confidence = 0.8

        # Boost for high-priority parent keys
        if parent_key in self.priority_weights:
            confidence *= self.priority_weights[parent_key]

        # Boost if we found a name
        if any(
            key
            for key in pattern["data"].keys()
            if "name" in key.lower() or "όνομα" in key.lower()
        ):
            confidence += 0.1

        return min(confidence, 1.0)

    @transaction.atomic
    def _save_entities_to_database(
        self, decision: Decision, entities: List[Dict[str, Any]]
    ):
        """Save extracted entities and relationships to database."""
        for entity_info in entities:
            # Get or create AFM entity
            entity, created = AFMEntity.objects.get_or_create(
                afm=entity_info["afm"],
                defaults={
                    "entity_type": entity_info["entity_type"],
                    "name": entity_info["name"],
                    "total_appearances": 0,
                },
            )

            if created:
                self.extraction_stats["entities_created"] += 1
                logger.debug(f"Created new AFM entity: {entity_info['afm']}")

            # Update entity info if we have better data
            if entity_info["name"] and not entity.name:
                entity.name = entity_info["name"]
                entity.save()

            # Update appearance count
            entity.total_appearances += 1
            entity.save()

            # Create relationship
            relationship, rel_created = (
                DecisionEntityRelationship.objects.get_or_create(
                    decision=decision,
                    entity=entity,
                    role=entity_info["role"],
                    parent_key_path=entity_info["parent_key_path"],
                    defaults={
                        "raw_context": entity_info["raw_context"],
                        "confidence_score": entity_info["confidence"],
                        "source_field_name": entity_info.get("source_field_name"),
                    },
                )
            )

            if rel_created:
                self.extraction_stats["relationships_created"] += 1
                logger.debug(
                    f"Created relationship: {decision.ada} -> {entity.afm} ({entity_info['role']})"
                )

    def get_extraction_stats(self) -> Dict[str, Any]:
        """Get current extraction statistics."""
        return self.extraction_stats.copy()

    def reset_stats(self):
        """Reset extraction statistics."""
        for key in self.extraction_stats:
            self.extraction_stats[key] = 0


# Convenience functions for external use
def extract_afms_from_decision(
    decision: Decision, save_to_db: bool = True
) -> List[Dict[str, Any]]:
    """Extract AFMs from a single decision."""
    service = AFMExtractionService()
    return service.extract_afms_from_decision(decision, save_to_db)


def extract_afms_from_decisions(
    decisions: List[Decision], save_to_db: bool = True
) -> Dict[str, Any]:
    """Extract AFMs from multiple decisions."""
    service = AFMExtractionService()
    return service.extract_afms_from_decisions_batch(decisions, save_to_db)
