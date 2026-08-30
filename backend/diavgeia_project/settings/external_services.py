"""
External services settings.

Contains configuration for OpenSearch, GEMI API, and AWS S3.
"""

import os

# OpenSearch Configuration
OPENSEARCH_URL = os.getenv("OPENSEARCH_URL", "http://opensearch:9200")
OPENSEARCH_ENABLED = os.getenv("OPENSEARCH_ENABLED", "true").lower() == "true"

# Search Configuration
SEARCH_BACKEND = os.getenv(
    "SEARCH_BACKEND", "opensearch"
)  # 'opensearch', 'postgresql', or 'hybrid'

# GEMI API Configuration
GEMI_API_KEY = os.getenv("GEMI_API_KEY", None)
GEMI_TIMEOUT = 30
GEMI_MAX_RETRIES = 3

# AWS Settings
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_STORAGE_BUCKET_NAME = os.getenv("AWS_STORAGE_BUCKET_NAME", "diavgeia-backups")
AWS_S3_REGION_NAME = os.getenv("AWS_S3_REGION_NAME", "eu-north-1")

# Diavgeia Feedback API (wrong-amount reporting)
# ---------------------------------------------------------------------------
# Used by DiavgeiaFeedbackService to report decisions whose metadata amounts
# were corrected (wrong amounts detected in the document text) back to the
# Diavgeia admins via the public feedback endpoint.
DIAVGEIA_FEEDBACK_URL = os.getenv(
    "DIAVGEIA_FEEDBACK_URL",
    "https://diavgeia.gov.gr/luminapi/api/feedback/new",
)
DIAVGEIA_FEEDBACK_REPORTER_EMAIL = os.getenv(
    "DIAVGEIA_FEEDBACK_REPORTER_EMAIL", "voulkon93@gmail.com"
)
# The `feedBackErrors` codes sent with each report. FE_1 = generic field
# error; adjust if Diavgeia exposes a more specific "wrong amount" code.
DIAVGEIA_FEEDBACK_ERRORS = ["FE_1"]
DIAVGEIA_FEEDBACK_TIMEOUT = 30
