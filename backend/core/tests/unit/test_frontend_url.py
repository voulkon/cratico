"""
Tests for core.services.frontend_url — centralized frontend URL helpers.

Covers the base-URL precedence order and the decision page URL builder:

    1. FRONTEND_DOMAINS[0]     (full origin with scheme, whitespace-trimmed)
    2. FRONTEND_HOSTNAMES[0]   (hostname only -> https:// prefixed)
    3. DEBUG on                -> FRONTEND_DEV_BASE (default localhost:3000)
    4. fallback                -> FRONTEND_PROD_BASE (default https://crati.co)
"""

from types import SimpleNamespace

from django.test import override_settings

from core.services.frontend_url import (
    _DEFAULT_DEV_BASE,
    _DEFAULT_PROD_BASE,
    decision_frontend_url,
    frontend_base_url,
)


class TestFrontendBaseUrl:
    """Precedence rules for frontend_base_url()."""

    def test_uses_frontend_domains_first(self):
        with override_settings(
            FRONTEND_DOMAINS=["https://app.crati.co"],
            FRONTEND_HOSTNAMES=["ignored.example.com"],
            DEBUG=False,
        ):
            assert frontend_base_url() == "https://app.crati.co"

    def test_trims_whitespace_from_domain(self):
        with override_settings(
            FRONTEND_DOMAINS=["  https://app.crati.co  "],
            FRONTEND_HOSTNAMES=[],
            DEBUG=False,
        ):
            assert frontend_base_url() == "https://app.crati.co"

    def test_strips_trailing_slash_from_domain(self):
        with override_settings(
            FRONTEND_DOMAINS=["https://app.crati.co/"],
            FRONTEND_HOSTNAMES=[],
            DEBUG=False,
        ):
            assert frontend_base_url() == "https://app.crati.co"

    def test_falls_back_to_hostnames_with_https(self):
        with override_settings(
            FRONTEND_DOMAINS=[],
            FRONTEND_HOSTNAMES=["crati.co"],
            DEBUG=False,
        ):
            assert frontend_base_url() == "https://crati.co"

    def test_debug_default_when_nothing_set(self):
        with override_settings(
            FRONTEND_DOMAINS=[],
            FRONTEND_HOSTNAMES=[],
            DEBUG=True,
        ):
            assert frontend_base_url() == _DEFAULT_DEV_BASE

    def test_debug_base_is_configurable(self):
        with override_settings(
            FRONTEND_DOMAINS=[],
            FRONTEND_HOSTNAMES=[],
            DEBUG=True,
            FRONTEND_DEV_BASE="http://localhost",
        ):
            assert frontend_base_url() == "http://localhost"

    def test_prod_default_when_nothing_set_and_not_debug(self):
        with override_settings(
            FRONTEND_DOMAINS=[],
            FRONTEND_HOSTNAMES=[],
            DEBUG=False,
        ):
            assert frontend_base_url() == _DEFAULT_PROD_BASE


class TestDecisionFrontendUrl:
    """decision_frontend_url() builds the decision page URL."""

    def test_builds_decision_url_from_base(self):
        decision = SimpleNamespace(id=123)
        with override_settings(
            FRONTEND_DOMAINS=["https://app.crati.co"],
            FRONTEND_HOSTNAMES=[],
            DEBUG=False,
        ):
            assert (
                decision_frontend_url(decision)
                == "https://app.crati.co/decision/123"
            )
