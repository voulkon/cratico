
import os


# ---------------------------------------------------------------------------
# AI Summarization Pipeline settings
# ---------------------------------------------------------------------------

# Fernet key for encrypting user API keys at rest.
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
AI_SECRETS_KEY = os.getenv("AI_SECRETS_KEY", "")

# System-level fallback OpenRouter key (operator pays, re-invoiceable).
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_API_BASE = os.getenv("OPENROUTER_API_BASE", "https://openrouter.ai/api/v1")

# Optional global cap on system-billed AI spend (USD/month).
SYSTEM_AI_MONTHLY_CAP = float(os.getenv("SYSTEM_AI_MONTHLY_CAP", "0") or "0")
