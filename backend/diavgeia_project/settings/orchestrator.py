"""
Pipeline Orchestrator Settings.

Contains configuration for the DecisionPipelineOrchestrator and related settings.
"""

import os

from loguru import logger

# Import from base module for FRONTEND_HOSTNAMES and DEBUG
from .base import DEBUG, FRONTEND_HOSTNAMES
from .orchestrator_utils import validate_and_format_public_key

# ============================================================================
# Pipeline Orchestrator Settings
# ============================================================================

# Use DecisionPipelineOrchestrator as single source of truth
# When True: Disables legacy signals that auto-process documents/entities
# When False: Uses old signal-based approach (for backward compatibility)
USE_ORCHESTRATOR_MODE = (
    os.environ.get("USE_ORCHESTRATOR_MODE", "True").lower() == "true"
)

# Enable legacy signals for backward compatibility
# Only used when USE_ORCHESTRATOR_MODE=False
ENABLE_LEGACY_DOCUMENT_SIGNALS = not USE_ORCHESTRATOR_MODE

if USE_ORCHESTRATOR_MODE:

    # logger.debug("=" * 50,
    # "[TARGET] Orchestrator Mode ENABLED:",
    # "   - Legacy document processing signals DISABLED",
    # "   - Use run_decision_pipeline_task for processing",
    # "   - No automatic document/entity processing on save",
    # "=" * 50)
    ...

# ============================================================================
# Clerk Authentication Settings
# ============================================================================

# Note: Settings files load before Django apps are ready, so we cannot use
# the feature flag service here (it would try to access the database).
# Instead, we use environment variables directly. The feature flag service
# can still be used elsewhere in the application once Django is initialized.
USE_CLERK_AUTH = os.getenv("USE_CLERK_AUTH", "False").lower() == "true"

CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY")

# Only configure Clerk if the feature flag is enabled
if USE_CLERK_AUTH:
    # Check for required environment variables
    raw_clerk_key = os.getenv("CLERK_JWT_PUBLIC_KEY")

    if not raw_clerk_key:
        logger.error(
            "[WARN]️  USE_CLERK_AUTH is enabled but CLERK_JWT_PUBLIC_KEY environment variable is missing!"
        )
        logger.error(
            "Please set CLERK_JWT_PUBLIC_KEY or disable the USE_CLERK_AUTH feature flag."
        )
        CLERK_JWT_PUBLIC_KEY = None
    elif not CLERK_SECRET_KEY:
        logger.warning(
            "[WARN]️  USE_CLERK_AUTH is enabled but CLERK_SECRET_KEY environment variable is missing!"
        )
        logger.warning("Some Clerk features may not work without the secret key.")
        try:
            CLERK_JWT_PUBLIC_KEY = validate_and_format_public_key(raw_clerk_key)
            logger.debug("[OK] Clerk authentication configured (public key only)")
        except ValueError as e:
            logger.error(f"Failed to load CLERK_JWT_PUBLIC_KEY: {e}")
            logger.error(
                "Please check your environment variable configuration. "
                "The key should be pasted as-is with actual newlines, not escaped \\n. "
                "Alternatively, you can paste it as a single line (without the newlines in the middle)."
            )
            CLERK_JWT_PUBLIC_KEY = None
    else:
        # Both env vars present
        try:
            CLERK_JWT_PUBLIC_KEY = validate_and_format_public_key(raw_clerk_key)
            logger.debug("[OK] Clerk authentication fully configured")
        except ValueError as e:
            logger.error(f"Failed to load CLERK_JWT_PUBLIC_KEY: {e}")
            logger.error(
                "Please check your environment variable configuration. "
                "The key should be pasted as-is with actual newlines, not escaped \\n. "
                "Alternatively, you can paste it as a single line (without the newlines in the middle)."
            )
            CLERK_JWT_PUBLIC_KEY = None
else:
    # Feature flag disabled - use Django default authentication
    CLERK_JWT_PUBLIC_KEY = None
    logger.debug(
        "[AUTH] Clerk authentication disabled (USE_CLERK_AUTH feature flag is off). Using Django default authentication."
    )

# Use the first frontend hostname, or localhost:3000 in debug
# Auto-derive from frontend domains
if FRONTEND_HOSTNAMES:
    default_clerk_audience = FRONTEND_HOSTNAMES[0]
else:
    default_clerk_audience = "localhost:3000" if DEBUG else "your-domain.com"

CLERK_JWT_AUDIENCE = os.getenv("CLERK_JWT_AUDIENCE", default_clerk_audience)
