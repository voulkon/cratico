"""
Tests for core.utils.encryption — encrypt / decrypt with Fernet.

Covers the lazy-singleton _get_fernet(), encrypt(), and decrypt()
with happy paths, edge cases, and error conditions.
"""

import pytest
from cryptography.fernet import Fernet, InvalidToken
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings


# ═══════════════════════════════════════════════════════════════════════════
# Valid key for most tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def fernet_key() -> str:
    return Fernet.generate_key().decode()


# ═══════════════════════════════════════════════════════════════════════════
# _get_fernet() / ImproperlyConfigured
# ═══════════════════════════════════════════════════════════════════════════


class TestGetFernet:
    """Tests for lazy Fernet instance creation and key validation."""

    def test_raises_improperly_configured_when_key_empty(self):
        """AI_SECRETS_KEY="" → ImproperlyConfigured."""
        from core.utils.encryption import _get_fernet

        with override_settings(AI_SECRETS_KEY=""):
            with pytest.raises(ImproperlyConfigured, match="AI_SECRETS_KEY"):
                _get_fernet()

    def test_raises_improperly_configured_when_key_none(self):
        """AI_SECRETS_KEY=None → ImproperlyConfigured."""
        from core.utils.encryption import _get_fernet

        with override_settings(AI_SECRETS_KEY=None):
            with pytest.raises(ImproperlyConfigured):
                _get_fernet()

    def test_accepts_valid_key(self, fernet_key):
        """A valid Fernet key string builds a Fernet instance."""
        from core.utils.encryption import _get_fernet

        with override_settings(AI_SECRETS_KEY=fernet_key):
            f = _get_fernet()
            assert isinstance(f, Fernet)

    def test_caches_fernet_instance(self, fernet_key):
        """Subsequent calls return the *same* Fernet object."""
        from core.utils.encryption import _get_fernet, _fernet as mod_fernet

        # Reset module-level cache
        import core.utils.encryption as mod
        mod._fernet = None

        with override_settings(AI_SECRETS_KEY=fernet_key):
            f1 = _get_fernet()
            f2 = _get_fernet()
            assert f1 is f2


# ═══════════════════════════════════════════════════════════════════════════
# encrypt() / decrypt() — happy path
# ═══════════════════════════════════════════════════════════════════════════


class TestEncryptDecrypt:
    """Round-trip and property tests for encrypt/decrypt."""

    def test_roundtrip_simple_string(self, fernet_key):
        """encrypt → decrypt returns original."""
        from core.utils.encryption import encrypt, decrypt

        with override_settings(AI_SECRETS_KEY=fernet_key):
            plain = "sk-or-v1-abc123secret"
            assert decrypt(encrypt(plain)) == plain

    def test_roundtrip_unicode(self, fernet_key):
        """Handles Greek / Unicode text."""
        from core.utils.encryption import encrypt, decrypt

        with override_settings(AI_SECRETS_KEY=fernet_key):
            plain = "κλειδί-API-δοκιμή-🚀"
            assert decrypt(encrypt(plain)) == plain

    def test_roundtrip_long_string(self, fernet_key):
        """Handles a long string (e.g., a JWT or multi-KB payload)."""
        from core.utils.encryption import encrypt, decrypt

        with override_settings(AI_SECRETS_KEY=fernet_key):
            plain = "x" * 10_000
            assert decrypt(encrypt(plain)) == plain

    def test_ciphertext_is_different_from_plaintext(self, fernet_key):
        """Encrypting produces a transformed (non-equal) result."""
        from core.utils.encryption import encrypt

        with override_settings(AI_SECRETS_KEY=fernet_key):
            plain = "my-secret"
            cipher = encrypt(plain)
            assert cipher != plain
            assert len(cipher) > 0

    def test_same_plaintext_produces_different_ciphertext(self, fernet_key):
        """Fernet is non-deterministic (includes timestamp + IV)."""
        from core.utils.encryption import encrypt

        with override_settings(AI_SECRETS_KEY=fernet_key):
            c1 = encrypt("same")
            c2 = encrypt("same")
            # Fernet ciphertexts with different timestamps → different output
            assert c1 != c2


# ═══════════════════════════════════════════════════════════════════════════
# encrypt() / decrypt() — edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestEncryptDecryptEdgeCases:

    def test_encrypt_empty_string_returns_empty(self, fernet_key):
        from core.utils.encryption import encrypt

        with override_settings(AI_SECRETS_KEY=fernet_key):
            assert encrypt("") == ""

    def test_decrypt_empty_string_returns_empty(self, fernet_key):
        from core.utils.encryption import decrypt

        with override_settings(AI_SECRETS_KEY=fernet_key):
            assert decrypt("") == ""

    def test_decrypt_invalid_token_raises(self, fernet_key):
        """Tampered ciphertext → InvalidToken."""
        from core.utils.encryption import decrypt

        with override_settings(AI_SECRETS_KEY=fernet_key):
            with pytest.raises(InvalidToken):
                decrypt("not-a-valid-fernet-token!!")

    def test_decrypt_with_different_key_fails(self, fernet_key):
        """Ciphertext from key-A cannot be decrypted with key-B."""
        from core.utils.encryption import encrypt, decrypt
        import core.utils.encryption as enc_mod

        key_a = Fernet.generate_key().decode()
        key_b = Fernet.generate_key().decode()

        with override_settings(AI_SECRETS_KEY=key_a):
            cipher = encrypt("secret")

        # Reset the module-level _fernet singleton so the next
        # override_settings block picks up key_b instead of
        # returning the cached Fernet(key_a).
        enc_mod._fernet = None

        with override_settings(AI_SECRETS_KEY=key_b):
            with pytest.raises(InvalidToken):
                decrypt(cipher)

    def test_encrypt_whitespace_only(self, fernet_key):
        """Whitespace-only strings are truthy → encrypted normally."""
        from core.utils.encryption import encrypt, decrypt

        with override_settings(AI_SECRETS_KEY=fernet_key):
            plain = "   "
            assert decrypt(encrypt(plain)) == plain


# ═══════════════════════════════════════════════════════════════════════════
# Module-level singleton reset
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def reset_fernet_singleton():
    """Reset the module-level _fernet cache between tests."""
    import core.utils.encryption as mod
    mod._fernet = None
    yield
    mod._fernet = None