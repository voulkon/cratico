"""
Encryption utility for storing secrets at rest.

Uses Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256) from the
``cryptography`` library.  The encryption key is read from the
``AI_SECRETS_KEY`` Django setting, which must be a URL-safe base64-encoded
32-byte key (generate one with ``Fernet.generate_key()``).

Usage::

    from core.utils.encryption import encrypt, decrypt

    cipher = encrypt("sk-or-v1-...")
    # store `cipher` in a TextField

    plaintext = decrypt(cipher)
"""

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """Lazily build the Fernet instance, validating the key once."""
    global _fernet
    if _fernet is not None:
        return _fernet

    key = getattr(settings, "AI_SECRETS_KEY", "")
    if not key:
        raise ImproperlyConfigured(
            "AI_SECRETS_KEY is not set. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"` and add it to your "
            "environment / .env file."
        )
    _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt(plaintext: str) -> str:
    """
    Encrypt *plaintext* and return a URL-safe string suitable for DB storage.

    Returns an empty string when *plaintext* is empty or None so callers can
    store ``""`` rather than raising.
    """
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """
    Decrypt a value produced by :func:`encrypt`.

    Returns an empty string when *ciphertext* is empty or None.  Raises
    ``cryptography.fernet.InvalidToken`` if the value is tampered with or was
    encrypted with a different key.
    """
    if not ciphertext:
        return ""
    return _get_fernet().decrypt(ciphertext.encode()).decode()
