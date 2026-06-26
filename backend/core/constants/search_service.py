from dataclasses import dataclass
from typing import List


class SearchMethod:
    """Constants for entity search methods"""

    POSTGRES_SIMPLE = "postgres_simple"  # Basic ILIKE search (always available)
    POSTGRES_FTS = (
        "postgres_fts"  # PostgreSQL Full-Text Search (requires search_vector)
    )
    OPENSEARCH = "opensearch"  # OpenSearch (requires OpenSearch indexing)

    # All valid methods
    ALL = [POSTGRES_SIMPLE, POSTGRES_FTS, OPENSEARCH]

    # Default fallback method (always available, no prerequisites)
    DEFAULT = POSTGRES_SIMPLE


# ==================== ENTITY TYPE CONSTANTS ====================
# Single source of truth for entity type string identifiers.
# These keys are used by POSTGRES_FTS_MODELS, BROWSABLE_ENTITIES,
# and throughout the search/browse codebase.

ENTITY_EXTRACTION = "extraction"
ENTITY_DECISION = "decision"
ENTITY_AFM_ENTITY = "afmentity"
ENTITY_ORGANIZATION = "organization"
ENTITY_UNIT = "unit"
ENTITY_SIGNER = "signer"
ENTITY_COMPANY = "company"
ENTITY_COMPANY_PERSON = "companyperson"

# Model configurations for PostgreSQL Full-Text Search
# Used for backfilling and validating search_vector fields
POSTGRES_FTS_MODELS = {
    ENTITY_EXTRACTION: {
        "model_path": "core.models.document_analysis.DocumentExtraction",
        "table": "core_documentextraction",
        "text_fields": ["raw_text"],
        "search_config": "greek",
        "required_for_fts": True,  # GIN index added in migration 0061
    },
    ENTITY_DECISION: {
        "model_path": "core.models.decisions.Decision",
        "table": "core_decision",
        "text_fields": ["subject"],
        "search_config": "greek",
        "required_for_fts": True,  # Required for decision search
    },
    ENTITY_AFM_ENTITY: {
        "model_path": "core.models.entities.AFMEntity",
        "table": "core_afmentity",
        "text_fields": ["name"],
        "search_config": "greek",
        "required_for_fts": True,  # Required for entity search
    },
    ENTITY_ORGANIZATION: {
        "model_path": "core.models.organizations.Organization",
        "table": "core_organization",
        "text_fields": ["label"],
        "search_config": "greek",
        "required_for_fts": True,  # Required for entity search
    },
    ENTITY_UNIT: {
        "model_path": "core.models.organizations.Unit",
        "table": "core_unit",
        "text_fields": ["label"],
        "search_config": "greek",
        "required_for_fts": True,  # Required for entity search
    },
    ENTITY_SIGNER: {
        "model_path": "core.models.organizations.Signer",
        "table": "core_signer",
        "text_fields": ["first_name", "last_name"],
        "search_config": "greek",
        "required_for_fts": True,  # Required for entity search
    },
    ENTITY_COMPANY: {
        "model_path": "core.models.companies.Company",
        "table": "companies",
        "text_fields": ["co_name_el", "co_names_en", "co_titles_el", "co_titles_en"],
        "search_config": "greek",
        "required_for_fts": True,  # Required for entity search
    },
    ENTITY_COMPANY_PERSON: {
        "model_path": "core.models.companies.CompanyPerson",
        "table": "company_persons",
        "text_fields": ["person_name"],
        "search_config": "greek",
        "required_for_fts": True,  # Required for entity search
    },
}

# Migration that adds search_vector triggers for all models
POSTGRES_FTS_MIGRATION = "0053_add_search_vector_triggers"

# ==================== BROWSE CONFIGURATION ====================


@dataclass(frozen=True)
class BrowsableEntityConfig:
    """Configuration for a single browsable entity type.

    Maps POSTGRES_FTS_MODELS keys to browse-specific configuration.
    Only entities listed in BROWSABLE_ENTITIES are available for
    alphabetical browsing. Each entry MUST have a corresponding entry
    in POSTGRES_FTS_MODELS (the model path is read from there).

    Fields:
        sort_fields:     List of model fields to ORDER BY.
        letter_field:    Primary field for first-letter filtering
                         (LEFT(field, 1)). For companies this is the
                         Greek name; the service also checks co_names_en
                         for English-letter discoverability.
        display_fields:  Fields used to build the display text.
        id_field:        The field used as the entity's unique identifier.
                         For companies and afm_entities this is "afm" so
                         the frontend navigates to /entity/afm/<afm>.
        type_label:      String label returned as the "type" in API
                         responses.
    """

    sort_fields: List[str]
    letter_field: str
    display_fields: List[str]
    id_field: str
    type_label: str


BROWSABLE_ENTITIES = {
    ENTITY_ORGANIZATION: BrowsableEntityConfig(
        sort_fields=["label"],
        letter_field="label",
        display_fields=["label"],
        id_field="uid",
        type_label="organization",
    ),
    ENTITY_UNIT: BrowsableEntityConfig(
        sort_fields=["label"],
        letter_field="label",
        display_fields=["label"],
        id_field="uid",
        type_label="unit",
    ),
    ENTITY_SIGNER: BrowsableEntityConfig(
        sort_fields=["last_name", "first_name"],
        letter_field="last_name",
        display_fields=["last_name", "first_name"],
        id_field="uid",
        type_label="signer",
    ),
    ENTITY_COMPANY: BrowsableEntityConfig(
        sort_fields=["co_name_el"],
        letter_field="co_name_el",  # Greek name (primary); English checked separately
        display_fields=["co_name_el"],
        id_field="afm",  # Navigates to /entity/afm/<afm>
        type_label="company",
    ),
    ENTITY_COMPANY_PERSON: BrowsableEntityConfig(
        sort_fields=["person_name"],
        letter_field="person_name",
        display_fields=["person_name"],
        id_field="id",
        type_label="company_person",
    ),
    ENTITY_AFM_ENTITY: BrowsableEntityConfig(
        sort_fields=["name"],
        letter_field="name",
        display_fields=["name"],
        id_field="afm",
        type_label="afm_entity",
    ),
}

# Valid entity_type values for the browse API.
# Derived from BROWSABLE_ENTITIES keys + "all".
BROWSABLE_ENTITY_TYPES = ["all"] + list(BROWSABLE_ENTITIES.keys())
