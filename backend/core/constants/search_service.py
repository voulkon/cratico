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


# Model configurations for PostgreSQL Full-Text Search
# Used for backfilling and validating search_vector fields
POSTGRES_FTS_MODELS = {
    "extraction": {
        "model_path": "core.models.document_analysis.DocumentExtraction",
        "table": "core_documentextraction",
        "text_fields": ["raw_text"],
        "search_config": "greek",
        "required_for_fts": False,  # Extraction is optional (large table)
    },
    "afmentity": {
        "model_path": "core.models.entities.AFMEntity",
        "table": "core_afmentity",
        "text_fields": ["name"],
        "search_config": "greek",
        "required_for_fts": True,  # Required for entity search
    },
    "organization": {
        "model_path": "core.models.organizations.Organization",
        "table": "core_organization",
        "text_fields": ["label"],
        "search_config": "greek",
        "required_for_fts": True,  # Required for entity search
    },
    "unit": {
        "model_path": "core.models.organizations.Unit",
        "table": "core_unit",
        "text_fields": ["label"],
        "search_config": "greek",
        "required_for_fts": True,  # Required for entity search
    },
    "signer": {
        "model_path": "core.models.organizations.Signer",
        "table": "core_signer",
        "text_fields": ["first_name", "last_name"],
        "search_config": "greek",
        "required_for_fts": True,  # Required for entity search
    },
    "company": {
        "model_path": "core.models.companies.Company",
        "table": "companies",
        "text_fields": ["co_name_el", "co_names_en", "co_titles_el", "co_titles_en"],
        "search_config": "greek",
        "required_for_fts": True,  # Required for entity search
    },
    "companyperson": {
        "model_path": "core.models.companies.CompanyPerson",
        "table": "company_persons",
        "text_fields": ["person_name"],
        "search_config": "greek",
        "required_for_fts": True,  # Required for entity search
    },
}

# Migration that adds search_vector triggers for all models
POSTGRES_FTS_MIGRATION = "0053_add_search_vector_triggers"
