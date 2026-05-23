"""
Pipeline Orchestrator Settings.

Contains configuration for the DecisionPipelineOrchestrator and related settings.
"""

# Import from base module for FRONTEND_HOSTNAMES and DEBUG
from loguru import logger

# ============================================================================
# Clerk Authentication Settings
# ============================================================================


def validate_and_format_public_key(raw_key: str | None) -> str | None:
    """
    Validate and format a PEM-encoded public key.

    This function ensures the public key has the correct structure:
    - Proper BEGIN/END markers
    - Valid base64 content between markers
    - Correct newline formatting

    Args:
        raw_key: Raw public key string from environment variable

    Returns:
        Properly formatted public key or None if invalid/missing

    Raises:
        ValueError: If the key is present but malformed beyond repair
    """
    if not raw_key:
        logger.warning(
            "CLERK_JWT_PUBLIC_KEY not found in environment. "
            "JWT authentication will not work."
        )
        return None

    # Clean up common encoding issues
    key = raw_key.strip()

    # Replace literal \n with actual newlines
    if "\\n" in key:
        logger.debug("Converting escaped newlines to actual newlines")
        key = key.replace("\\n", "\n")

    # Remove any surrounding quotes that might have been added
    key = key.strip('"').strip("'")

    # Validate structure
    BEGIN_MARKER = "-----BEGIN PUBLIC KEY-----"
    END_MARKER = "-----END PUBLIC KEY-----"

    if BEGIN_MARKER not in key:
        raise ValueError(
            f"CLERK_JWT_PUBLIC_KEY is missing '{BEGIN_MARKER}' marker. "
            f"Got: {key[:100]}..."
        )

    if END_MARKER not in key:
        raise ValueError(
            f"CLERK_JWT_PUBLIC_KEY is missing '{END_MARKER}' marker. "
            f"The key appears truncated. Got: {key[:200]}..."
        )

    # Extract the content between markers
    try:
        start_idx = key.index(BEGIN_MARKER) + len(BEGIN_MARKER)
        end_idx = key.index(END_MARKER)
        content = key[start_idx:end_idx].strip()
    except ValueError as e:
        raise ValueError(f"Failed to parse public key structure: {e}")

    # Remove all whitespace from content to get raw base64
    content_clean = "".join(content.split())

    # Validate base64 content (basic check)
    if not content_clean:
        raise ValueError(
            "CLERK_JWT_PUBLIC_KEY has no content between BEGIN/END markers"
        )

    # Check if content looks like valid base64
    import re

    if not re.match(r"^[A-Za-z0-9+/=]+$", content_clean):
        raise ValueError(
            f"CLERK_JWT_PUBLIC_KEY content doesn't appear to be valid base64. "
            f"Got: {content_clean[:50]}..."
        )

    # Reconstruct the key with proper formatting
    # Modern libraries can handle keys without line breaks in the content,
    # but we'll format it properly for maximum compatibility
    lines = [BEGIN_MARKER]

    # Split content into 64-character lines (standard PEM formatting)
    for i in range(0, len(content_clean), 64):
        lines.append(content_clean[i : i + 64])

    lines.append(END_MARKER)

    formatted_key = "\n".join(lines)

    # logger.debug(
    #     f"[OK] CLERK_JWT_PUBLIC_KEY validated successfully "
    #     f"({len(content_clean)} base64 chars)"
    # )

    return formatted_key
