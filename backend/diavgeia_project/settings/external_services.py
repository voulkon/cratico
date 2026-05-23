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
