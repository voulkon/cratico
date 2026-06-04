from loguru import logger

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

# ---------------------------------------------------------------------------
# Date-type alignment for fetch ↔ coverage
# ---------------------------------------------------------------------------
# The Diavgeia API's `from_date` / `to_date` params filter on SUBMISSION date
# (i.e. when the decision was uploaded), not on issue date.
#
# Setting USE_SUBMISSION_DATE = True (the default) means:
#   - DecisionFetchReconcileService uses from_date / to_date  (submission)
#   - BackfillCoverageService counts decisions via submission_date_day
#
# If you ever need to switch the whole pipeline to issue-date semantics, flip
# this flag to False.  Both services read this constant so they always agree.
USE_SUBMISSION_DATE = True

# ORM field names on Decision used by BackfillCoverageService for counting
COVERAGE_DATE_FIELD = "publish_date_day" if USE_SUBMISSION_DATE else "issue_date_day"


# ---------------------------------------------------------------------------
# Runtime helpers — resolve date mode from the COVERAGE_DATE_MODE feature flag
# ---------------------------------------------------------------------------
# These are the preferred way to determine the date mode at runtime.
# The module-level USE_SUBMISSION_DATE / COVERAGE_DATE_FIELD constants above
# act as fallback defaults and are still used at import-time where necessary.


def _resolve_use_submission_date() -> bool:
    """
    Resolve whether to use submission date (True) or issue date (False).

    Reads the COVERAGE_DATE_MODE feature flag at call time.
    Falls back to the module-level USE_SUBMISSION_DATE constant if the
    feature flag service is unavailable (e.g. during migrations).
    """
    try:
        from core.services.feature_flag_service import feature_flags

        mode = feature_flags.get_value("COVERAGE_DATE_MODE")
        # Defensive: if the flag is somehow unset or corrupted, fall back
        if mode == "issue":
            return False
        # Treat anything else (including "submission", None, unexpected values)
        # as submission-date — that"s the safe default.
        return True
    except Exception:
        logger.opt(exception=True).warning(
            "Could not resolve COVERAGE_DATE_MODE from feature flag — "
            "falling back to USE_SUBMISSION_DATE={}",
            USE_SUBMISSION_DATE,
        )
        return USE_SUBMISSION_DATE


def get_api_date_fields() -> tuple:
    """
    Return (from_field, to_field) for Diavgeia API search params,
    resolved from the COVERAGE_DATE_MODE feature flag.
    """
    if _resolve_use_submission_date():
        return DiavgeiaSearchFields.FROM_DATE, DiavgeiaSearchFields.TO_DATE
    return DiavgeiaSearchFields.FROM_ISSUE_DATE, DiavgeiaSearchFields.TO_ISSUE_DATE


def get_coverage_date_field() -> str:
    """
    Return the ORM field name on Decision for counting coverage,
    resolved from the COVERAGE_DATE_MODE feature flag.
    """
    if _resolve_use_submission_date():
        return "publish_date_day"
    return "issue_date_day"
