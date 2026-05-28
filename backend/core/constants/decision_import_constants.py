PICKLE_DIR = "/code/logs/pickles"

# Diavgeia API Search Parameter Field Names
# These constants centralize the field names used when searching the Diavgeia API.
# This ensures consistency across all fetch operations and makes it easier to switch
# between different date field types (e.g., issue_date vs submission_date).


class DiavgeiaSearchFields:
    """
    Constants for Diavgeia API search parameter field names.
    
    Usage:
        search_params = {
            DiavgeiaSearchFields.FROM_DATE: "2026-05-01",
            DiavgeiaSearchFields.TO_DATE: "2026-05-02",
        }
    """

    # Date range fields - SUBMISSION/UPLOAD date (when decision was uploaded to Diavgeia)
    # This is what the official API uses for daily counts
    FROM_DATE = "from_date"
    TO_DATE = "to_date"

    # Date range fields - ISSUE date (when decision was officially issued)
    # This may differ from submission date by days or weeks
    FROM_ISSUE_DATE = "from_issue_date"
    TO_ISSUE_DATE = "to_issue_date"

    # Pagination fields
    PAGE = "page"
    SIZE = "size"

    # Entity filter fields
    ORG = "org"  # Organization UID
    UNIT = "unit"  # Unit UID
    SIGNER = "signer"  # Signer UID
    TYPE = "type"  # Decision type UID (supports multiple types with semicolon separator)

    # Common pagination defaults
    DEFAULT_PAGE = 0
    DEFAULT_PAGE_SIZE = 500  # Maximum allowed by Diavgeia API


# Official Diavgeia API endpoints for reconciliation
DIAVGEIA_OFFICIAL_COUNTS_URL = (
    "https://diavgeia.gov.gr/static/api/search/countPerDayLastMonth"
)
