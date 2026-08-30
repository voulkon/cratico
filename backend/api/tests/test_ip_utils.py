"""
Unit tests for api/utils/ip.py — the canonical client-IP resolver.

Covers every resolution branch:
    1. CF-Connecting-IP (present + public → return; present but private → fall through)
    2. True-Client-IP (present + public → return; present but private → fall through)
    3. X-Forwarded-For (first public IP; skips private/loopback; empty chain)
    4. X-Real-IP (present → return)
    5. REMOTE_ADDR (final fallback)
    6. _is_infrastructure_ip (private, loopback, link-local, public, invalid)

All tests use plain dict-based mock requests — no Django test client needed.
"""

from unittest.mock import MagicMock

import pytest

from api.utils.ip import _is_infrastructure_ip, get_client_ip


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(**meta):
    """Create a minimal mock request with the given META keys."""
    req = MagicMock()
    req.META = meta
    return req


# ---------------------------------------------------------------------------
# _is_infrastructure_ip
# ---------------------------------------------------------------------------


class TestIsInfrastructureIP:
    """Unit tests for the private helper that classifies IPs."""

    # -- Private ranges (RFC 1918) ----------------------------------------

    @pytest.mark.parametrize(
        "ip",
        [
            "10.0.0.1",
            "10.255.255.255",
            "172.16.0.1",
            "172.31.255.255",
            "192.168.0.1",
            "192.168.255.255",
        ],
    )
    def test_private_ipv4(self, ip):
        assert _is_infrastructure_ip(ip) is True

    # -- Loopback ----------------------------------------------------------

    def test_loopback_ipv4(self):
        assert _is_infrastructure_ip("127.0.0.1") is True

    def test_loopback_ipv6(self):
        assert _is_infrastructure_ip("::1") is True

    # -- Link-local --------------------------------------------------------

    def test_link_local_ipv4(self):
        assert _is_infrastructure_ip("169.254.1.1") is True

    def test_link_local_ipv6(self):
        assert _is_infrastructure_ip("fe80::1") is True

    # -- Public IPs --------------------------------------------------------

    def test_public_ipv4(self):
        assert _is_infrastructure_ip("8.8.8.8") is False
        assert _is_infrastructure_ip("9.9.9.9") is False

    def test_public_ipv6(self):
        assert _is_infrastructure_ip("2a00:1450:4001:830::200e") is False

    # -- Edge cases --------------------------------------------------------

    def test_empty_string(self):
        assert _is_infrastructure_ip("") is False

    def test_invalid_string(self):
        assert _is_infrastructure_ip("not-an-ip") is False

    def test_none(self):
        # ipaddress.ip_address(None) → str(None)='None' → ValueError → caught → False.
        # This is the safe default: None is not a proxy IP we'd skip.
        assert _is_infrastructure_ip(None) is False


# ---------------------------------------------------------------------------
# get_client_ip — resolution branches
# ---------------------------------------------------------------------------


class TestGetClientIP:
    """Tests for the main entry point covering all resolution branches."""

    # Truly public IPs that _is_infrastructure_ip returns False for.
    # Avoid 203.0.113.0/24 (RFC 5737 TEST-NET) and 2001:db8::/32
    # (IPv6 documentation) — both are is_private=True in ipaddress.
    PUBLIC = "8.8.8.8"
    ALT = "1.1.1.1"

    # ── 1. CF-Connecting-IP (Cloudflare) ──────────────────────────────

    def test_cf_connecting_ip_public(self):
        """Cloudflare's header with a public IP wins over everything else."""
        req = _make_request(
            HTTP_CF_CONNECTING_IP="8.8.8.8",
            HTTP_X_FORWARDED_FOR="10.0.0.1, 1.2.3.4",
            HTTP_X_REAL_IP="172.16.0.1",
            REMOTE_ADDR="127.0.0.1",
        )
        assert get_client_ip(req) == "8.8.8.8"

    def test_cf_connecting_ip_private_falls_through(self):
        """CF-Connecting-IP with a private IP is not trusted — fall through
        to the next header."""
        req = _make_request(
            HTTP_CF_CONNECTING_IP="10.0.0.5",  # private → skip
            HTTP_X_FORWARDED_FOR="1.1.1.1",
            REMOTE_ADDR="127.0.0.1",
        )
        assert get_client_ip(req) == "1.1.1.1"

    def test_cf_connecting_ip_loopback_falls_through(self):
        req = _make_request(
            HTTP_CF_CONNECTING_IP="127.0.0.1",  # loopback → skip
            HTTP_X_REAL_IP="8.8.8.8",
            REMOTE_ADDR="127.0.0.1",
        )
        assert get_client_ip(req) == "8.8.8.8"

    def test_cf_connecting_ip_stripped(self):
        """Extra whitespace around the header value is stripped."""
        req = _make_request(
            HTTP_CF_CONNECTING_IP="  8.8.8.8  ",
            REMOTE_ADDR="127.0.0.1",
        )
        assert get_client_ip(req) == "8.8.8.8"

    def test_cf_connecting_ip_empty_string(self):
        """Empty CF-Connecting-IP should fall through."""
        req = _make_request(
            HTTP_CF_CONNECTING_IP="",
            HTTP_X_FORWARDED_FOR="8.8.4.4",
            REMOTE_ADDR="127.0.0.1",
        )
        assert get_client_ip(req) == "8.8.4.4"

    # ── 2. True-Client-IP ─────────────────────────────────────────────

    def test_true_client_ip_public(self):
        """True-Client-IP with a public IP wins when CF-Connecting-IP is absent."""
        req = _make_request(
            HTTP_TRUE_CLIENT_IP="9.9.9.9",
            HTTP_X_FORWARDED_FOR="10.0.0.1",
            REMOTE_ADDR="127.0.0.1",
        )
        assert get_client_ip(req) == "9.9.9.9"

    def test_true_client_ip_private_falls_through(self):
        req = _make_request(
            HTTP_TRUE_CLIENT_IP="192.168.1.1",  # private → skip
            HTTP_X_FORWARDED_FOR="1.0.0.1",
            REMOTE_ADDR="127.0.0.1",
        )
        assert get_client_ip(req) == "1.0.0.1"

    def test_true_client_ip_empty_string_falls_through(self):
        req = _make_request(
            HTTP_TRUE_CLIENT_IP="",
            HTTP_X_FORWARDED_FOR="208.67.222.222",
            REMOTE_ADDR="127.0.0.1",
        )
        assert get_client_ip(req) == "208.67.222.222"

    # ── 3. X-Forwarded-For ────────────────────────────────────────────

    def test_xff_single_public_ip(self):
        req = _make_request(
            HTTP_X_FORWARDED_FOR="151.101.1.140",
            REMOTE_ADDR="127.0.0.1",
        )
        assert get_client_ip(req) == "151.101.1.140"

    def test_xff_skips_leading_private_ips(self):
        """The leftmost public IP is returned, private/loopback entries are skipped."""
        req = _make_request(
            HTTP_X_FORWARDED_FOR="10.0.0.1, 172.16.0.1, 8.8.8.8, 192.168.1.1",
            REMOTE_ADDR="127.0.0.1",
        )
        assert get_client_ip(req) == self.PUBLIC

    def test_xff_all_private_falls_through(self):
        """When all XFF entries are private, fall through to next header."""
        req = _make_request(
            HTTP_X_FORWARDED_FOR="10.0.0.1, 192.168.1.1",
            HTTP_X_REAL_IP="8.8.8.8",
            REMOTE_ADDR="127.0.0.1",
        )
        assert get_client_ip(req) == self.PUBLIC

    def test_xff_with_ipv6(self):
        """IPv6 addresses are handled correctly."""
        req = _make_request(
            HTTP_X_FORWARDED_FOR="2a00:1450:4001:830::200e",
            REMOTE_ADDR="::1",
        )
        assert get_client_ip(req) == "2a00:1450:4001:830::200e"

    def test_xff_skips_ipv6_loopback(self):
        req = _make_request(
            HTTP_X_FORWARDED_FOR="::1, 2a00:1450:4001:830::200e",
            REMOTE_ADDR="127.0.0.1",
        )
        assert get_client_ip(req) == "2a00:1450:4001:830::200e"

    def test_xff_empty_string(self):
        req = _make_request(
            HTTP_X_FORWARDED_FOR="",
            HTTP_X_REAL_IP="8.8.8.8",
            REMOTE_ADDR="127.0.0.1",
        )
        assert get_client_ip(req) == self.PUBLIC

    def test_xff_with_whitespace(self):
        """Whitespace around entries is stripped."""
        req = _make_request(
            HTTP_X_FORWARDED_FOR="  8.8.8.8  ,  10.0.0.1  ",
            REMOTE_ADDR="127.0.0.1",
        )
        assert get_client_ip(req) == self.PUBLIC

    # ── 4. X-Real-IP ──────────────────────────────────────────────────

    def test_x_real_ip(self):
        req = _make_request(
            HTTP_X_REAL_IP="8.8.8.8",
            REMOTE_ADDR="127.0.0.1",
        )
        assert get_client_ip(req) == self.PUBLIC

    def test_x_real_ip_private_accepted(self):
        """X-Real-IP is accepted even if private — it's the last non-fallback
        header, and in local dev it's often a private IP from nginx."""
        req = _make_request(
            HTTP_X_REAL_IP="172.16.0.1",
            REMOTE_ADDR="127.0.0.1",
        )
        assert get_client_ip(req) == "172.16.0.1"

    def test_x_real_ip_empty_falls_through(self):
        req = _make_request(
            HTTP_X_REAL_IP="",
            REMOTE_ADDR="8.8.8.8",
        )
        assert get_client_ip(req) == self.PUBLIC

    # ── 5. REMOTE_ADDR (fallback) ─────────────────────────────────────

    def test_remote_addr_only(self):
        req = _make_request(REMOTE_ADDR="8.8.8.8")
        assert get_client_ip(req) == self.PUBLIC

    def test_all_headers_empty(self):
        req = _make_request(
            HTTP_CF_CONNECTING_IP="",
            HTTP_TRUE_CLIENT_IP="",
            HTTP_X_FORWARDED_FOR="",
            HTTP_X_REAL_IP="",
            REMOTE_ADDR="8.8.8.8",
        )
        assert get_client_ip(req) == self.PUBLIC

    # ── Priority smoke tests ─────────────────────────────────────────

    def test_cf_wins_over_true_client_ip(self):
        """CF-Connecting-IP is checked before True-Client-IP."""
        req = _make_request(
            HTTP_CF_CONNECTING_IP="8.8.8.8",
            HTTP_TRUE_CLIENT_IP="1.1.1.1",
            REMOTE_ADDR="127.0.0.1",
        )
        assert get_client_ip(req) == self.PUBLIC

    def test_true_client_ip_wins_over_xff(self):
        """True-Client-IP is checked before X-Forwarded-For."""
        req = _make_request(
            HTTP_TRUE_CLIENT_IP="8.8.8.8",
            HTTP_X_FORWARDED_FOR="1.1.1.1",
            REMOTE_ADDR="127.0.0.1",
        )
        assert get_client_ip(req) == self.PUBLIC

    def test_xff_wins_over_x_real_ip(self):
        """X-Forwarded-For is checked before X-Real-IP."""
        req = _make_request(
            HTTP_X_FORWARDED_FOR="8.8.8.8",
            HTTP_X_REAL_IP="1.1.1.1",
            REMOTE_ADDR="127.0.0.1",
        )
        assert get_client_ip(req) == self.PUBLIC

    def test_no_meta_at_all(self):
        """A request with no META keys at all returns None."""
        req = _make_request()
        assert get_client_ip(req) is None
