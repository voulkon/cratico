from decouple import config  # python-decouple for better env var parsing

# Provider API keys from environment variables
OPENAI_API_KEY = config("OPENAI_API_KEY", default=None)
ANTHROPIC_API_KEY = config("ANTHROPIC_API_KEY", default=None)
GOOGLE_VISION_CREDENTIALS = config("GOOGLE_VISION_CREDENTIALS", default=None)

# Provider-specific settings
PROVIDER_SETTINGS = {
    "OPENAI": {
        "api_key": OPENAI_API_KEY,
        "default_model": config("OPENAI_MODEL", default="gpt-4"),
        "timeout": config("OPENAI_TIMEOUT", cast=int, default=60),
    },
    "ANTHROPIC": {
        "api_key": ANTHROPIC_API_KEY,
        "default_model": config("ANTHROPIC_MODEL", default="claude-3-opus-20240229"),
    },
    # ...other providers
}


# If you need to validate settings at startup
def validate_settings():
    required_providers = config(
        "REQUIRED_PROVIDERS",
        cast=lambda v: [s.strip() for s in v.split(",")],
        default="PYPDF",
    )

    missing_keys = []

    if "OPENAI" in required_providers and not OPENAI_API_KEY:
        missing_keys.append("OPENAI_API_KEY")

    if "ANTHROPIC" in required_providers and not ANTHROPIC_API_KEY:
        missing_keys.append("ANTHROPIC_API_KEY")

    if missing_keys:
        import warnings

        warnings.warn(
            f"Missing required environment variables: {', '.join(missing_keys)}"
        )
