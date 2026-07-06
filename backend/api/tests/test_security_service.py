"""
Unit tests for api/services/security_service.py

Covers:
  - is_banned / ban_ip / unban_ip
  - record_signals (velocity, scan, errors)
  - record_strike
  - evaluate_threats (velocity, strikes, scan, errors)
  - is_flagged_for_forensics / _flag_for_forensics
  - get_top_velocity_ips / get_top_strike_ips / get_banned_ips

All Redis calls are mocked — no broker needed.
Feature flags are overridden via patch so no env-var changes are needed.
"""

from unittest.mock import MagicMock, call, patch

import pytest
import time as _time


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flag_enabled(flag_name):
    """Return a side_effect for feature_flags.is_enabled that only enables one flag."""

    def _check(name):
        return name == flag_name

    return _check


def _flags_enabled(*flag_names):
    """Return a side_effect that enables multiple flags."""

    def _check(name):
        return name in flag_names

    return _check


# ---------------------------------------------------------------------------
# SecurityService — ban / unban / is_banned
# ---------------------------------------------------------------------------


class TestBanUnbanIsBanned:
    """Tests for ban/unban/is_banned lifecycle."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from api.services.security_service import SecurityService

        self.svc = SecurityService()
        self.svc._redis = MagicMock()
        yield

    def test_is_banned_returns_false_for_unknown_ip(self):
        self.svc._redis.zremrangebyscore.return_value = 0
        self.svc._redis.zscore.return_value = None

        assert self.svc.is_banned("10.0.0.1") is False

    def test_is_banned_returns_true_for_banned_ip(self):
        self.svc._redis.zremrangebyscore.return_value = 0
        self.svc._redis.zscore.return_value = 1234567890.0

        assert self.svc.is_banned("10.0.0.1") is True

    def test_is_banned_cleans_expired_entries(self):
        self.svc._redis.zremrangebyscore.return_value = 3
        self.svc._redis.zscore.return_value = None

        self.svc.is_banned("10.0.0.1")
        self.svc._redis.zremrangebyscore.assert_called_once()

    def test_is_banned_returns_false_for_empty_ip(self):
        assert self.svc.is_banned("") is False
        assert self.svc.is_banned(None) is False
        # Redis should not be called for empty IP
        self.svc._redis.zremrangebyscore.assert_not_called()

    @patch("core.services.feature_flag_service.feature_flags")
    @patch("api.models.FlaggedIP")
    def test_ban_ip_adds_to_redis_and_db(self, mock_model, mock_ff):
        mock_ff.get_value.return_value = 24  # SECURITY_BAN_DURATION_HOURS

        mock_model.objects.filter.return_value.first.return_value = None
        mock_model.objects.update_or_create.return_value = (MagicMock(), True)

        self.svc.ban_ip("10.0.0.1", "velocity", strike_count=3)

        # Redis: banned set
        ban_call = self.svc._redis.zadd.call_args_list[0]
        assert ban_call[0][0] == "security:banned"
        assert "10.0.0.1" in ban_call[0][1]

        # Redis: flagged set (forensics)
        flag_call = self.svc._redis.zadd.call_args_list[1]
        assert flag_call[0][0] == "security:flagged"
        assert "10.0.0.1" in flag_call[0][1]

        # DB record
        mock_model.objects.update_or_create.assert_called_once()
        _, kwargs = mock_model.objects.update_or_create.call_args
        assert kwargs["defaults"]["reason"] == "velocity"
        assert kwargs["defaults"]["strike_count"] == 3
        assert kwargs["defaults"]["is_active"] is True

    @patch("core.services.feature_flag_service.feature_flags")
    @patch("api.models.FlaggedIP")
    def test_ban_ip_permanent(self, mock_model, mock_ff):
        mock_ff.get_value.return_value = 24
        mock_model.objects.filter.return_value.first.return_value = None
        mock_model.objects.update_or_create.return_value = (MagicMock(), True)

        self.svc.ban_ip("10.0.0.2", "manual", duration_hours=0)

        # Score should be inf for permanent
        ban_call = self.svc._redis.zadd.call_args_list[0]
        score = list(ban_call[0][1].values())[0]
        assert score == float("inf")

        _, kwargs = mock_model.objects.update_or_create.call_args
        assert kwargs["defaults"]["ban_expires_at"] is None

    @patch("core.services.feature_flag_service.feature_flags")
    @patch("api.models.FlaggedIP")
    def test_ban_ip_recurring_preserves_notes(self, mock_model, mock_ff):
        mock_ff.get_value.return_value = 24
        existing = MagicMock()
        existing.notes = "Banned before by admin"
        mock_model.objects.filter.return_value.first.return_value = existing
        mock_model.objects.update_or_create.return_value = (MagicMock(), False)

        self.svc.ban_ip("10.0.0.3", "strikes", strike_count=7)

        _, kwargs = mock_model.objects.update_or_create.call_args
        assert "Recurring offender" in kwargs["defaults"]["notes"]
        assert "Banned before by admin" in kwargs["defaults"]["notes"]

    @patch("api.models.FlaggedIP")
    def test_unban_ip_removes_from_redis_and_db(self, mock_model):
        self.svc._redis.zrem.return_value = 1
        mock_model.objects.filter.return_value.update.return_value = 1

        result = self.svc.unban_ip("10.0.0.1")

        assert result is True
        self.svc._redis.zrem.assert_has_calls(
            [call("security:banned", "10.0.0.1"), call("security:flagged", "10.0.0.1")]
        )
        mock_model.objects.filter.assert_called_once()

    def test_unban_ip_returns_false_when_not_found(self):
        self.svc._redis.zrem.return_value = 0

        with patch("api.models.FlaggedIP") as mock_model:
            mock_model.objects.filter.return_value.update.return_value = 0
            result = self.svc.unban_ip("10.0.0.99")
            assert result is False

    def test_ban_ip_skips_empty_ip(self):
        self.svc.ban_ip("", "manual")
        self.svc._redis.zadd.assert_not_called()

    def test_unban_ip_handles_redis_zrem_error(self):
        self.svc._redis.zrem.side_effect = [1, Exception("Redis down")]

        with patch("api.models.FlaggedIP") as mock_model:
            mock_model.objects.filter.return_value.update.return_value = 1
            with pytest.raises(Exception, match="Redis down"):
                self.svc.unban_ip("10.0.0.1")


# ---------------------------------------------------------------------------
# SecurityService — record_signals
# ---------------------------------------------------------------------------


class TestRecordSignals:
    """Tests for velocity/scan/error signal recording."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from api.services.security_service import SecurityService

        self.svc = SecurityService()
        self.svc._redis = MagicMock()
        # Mock pipeline
        self.mock_pipe = MagicMock()
        self.svc._redis.pipeline.return_value = self.mock_pipe
        yield

    def test_record_signals_tracks_velocity_and_scan(self):
        self.svc.record_signals("10.0.0.5", "/api/search/", is_error=False)

        # Pipeline was created and executed
        self.svc._redis.pipeline.assert_called_once()
        self.mock_pipe.execute.assert_called_once()

        # Velocity: INCR + EXPIRE NX
        self.mock_pipe.incr.assert_any_call("security:velocity:10.0.0.5")
        self.mock_pipe.expire.assert_any_call("security:velocity:10.0.0.5", 60, nx=True)

        # Scan: SADD + EXPIRE NX
        self.mock_pipe.sadd.assert_any_call("security:scan:10.0.0.5", "/api/search/")
        self.mock_pipe.expire.assert_any_call("security:scan:10.0.0.5", 300, nx=True)

        # Error: NOT called for non-error
        error_calls = [
            c for c in self.mock_pipe.incr.call_args_list
            if "errors" in str(c)
        ]
        assert len(error_calls) == 0

    def test_record_signals_tracks_errors(self):
        self.svc.record_signals("10.0.0.6", "/api/bad/", is_error=True)

        # Error counter incremented
        self.mock_pipe.incr.assert_any_call("security:errors:10.0.0.6")
        self.mock_pipe.expire.assert_any_call("security:errors:10.0.0.6", 300, nx=True)

    def test_record_signals_skips_empty_ip(self):
        self.svc.record_signals("", "/api/x/")
        self.svc._redis.pipeline.assert_not_called()


# ---------------------------------------------------------------------------
# SecurityService — record_strike
# ---------------------------------------------------------------------------


class TestRecordStrike:
    """Tests for security-event strike recording."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from api.services.security_service import SecurityService

        self.svc = SecurityService()
        self.svc._redis = MagicMock()
        self.mock_pipe = MagicMock()
        self.svc._redis.pipeline.return_value = self.mock_pipe
        yield

    def test_record_strike_increments_and_returns_count(self):
        self.svc._redis.get.return_value = b"3"

        count = self.svc.record_strike("10.0.0.7", "pattern_0:sqli")

        assert count == 3
        self.mock_pipe.incr.assert_called_once_with("security:strikes:10.0.0.7")
        self.mock_pipe.expire.assert_called_once_with(
            "security:strikes:10.0.0.7", 3600, nx=True
        )

    def test_record_strike_first_strike(self):
        self.svc._redis.get.return_value = None  # key doesn't exist yet

        count = self.svc.record_strike("10.0.0.8")

        assert count == 0  # None → 0 via `int(None or 0)`

    def test_record_strike_skips_empty_ip(self):
        count = self.svc.record_strike("")
        assert count == 0
        self.svc._redis.pipeline.assert_not_called()


# ---------------------------------------------------------------------------
# SecurityService — evaluate_threats
# ---------------------------------------------------------------------------


class TestEvaluateThreats:
    """Tests for threat evaluation logic."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from api.services.security_service import SecurityService

        self.svc = SecurityService()
        self.svc._redis = MagicMock()
        yield

    @patch("core.services.feature_flag_service.feature_flags")
    def test_returns_none_when_clean(self, mock_ff):
        mock_ff.get_value.side_effect = lambda key, default: default
        self.svc._redis.get.return_value = b"1"  # low velocity
        self.svc._redis.scard.return_value = 2  # low scan

        result = self.svc.evaluate_threats("10.0.0.10")

        assert result is None

    @patch("core.services.feature_flag_service.feature_flags")
    def test_triggers_velocity(self, mock_ff):
        mock_ff.get_value.return_value = 120  # threshold

        # velocity=200 > threshold
        self.svc._redis.get.side_effect = lambda key: (
            b"200" if "velocity" in key else b"0"
        )

        result = self.svc.evaluate_threats("10.0.0.11")

        assert result == "velocity"

    @patch("core.services.feature_flag_service.feature_flags")
    def test_triggers_strikes(self, mock_ff):
        # velocity below threshold, strikes above
        def _get_value(key, default):
            if key == "SECURITY_STRIKE_THRESHOLD":
                return 5
            return default

        mock_ff.get_value.side_effect = _get_value

        # velocity=10, strikes=7
        self.svc._redis.get.side_effect = lambda key: (
            b"7" if "strikes" in key else b"10"
        )

        result = self.svc.evaluate_threats("10.0.0.12")

        assert result == "strikes"

    @patch("core.services.feature_flag_service.feature_flags")
    def test_triggers_scan(self, mock_ff):
        def _get_value(key, default):
            if key == "SECURITY_SCAN_THRESHOLD":
                return 50
            return default

        mock_ff.get_value.side_effect = _get_value

        # velocity=1, strikes=0, scan=60
        self.svc._redis.get.return_value = b"1"
        self.svc._redis.scard.return_value = 60

        result = self.svc.evaluate_threats("10.0.0.13")

        assert result == "scan"

    @patch("core.services.feature_flag_service.feature_flags")
    def test_triggers_errors(self, mock_ff):
        def _get_value(key, default):
            if key == "SECURITY_ERROR_THRESHOLD":
                return 40
            return default

        mock_ff.get_value.side_effect = _get_value

        self.svc._redis.get.side_effect = lambda key: (
            b"50" if "errors" in key else b"1"
        )
        self.svc._redis.scard.return_value = 1

        result = self.svc.evaluate_threats("10.0.0.14")

        assert result == "errors"

    def test_returns_none_for_empty_ip(self):
        assert self.svc.evaluate_threats("") is None

    @patch("core.services.feature_flag_service.feature_flags")
    def test_velocity_wins_over_strikes(self, mock_ff):
        """Velocity is checked first — should return 'velocity' even if
        strikes also exceed threshold."""
        mock_ff.get_value.return_value = 5  # low threshold for both

        self.svc._redis.get.side_effect = lambda key: (
            b"10"  # ALL keys return 10 (velocity=10, strikes=10, errors=10)
        )
        self.svc._redis.scard.return_value = 1

        result = self.svc.evaluate_threats("10.0.0.15")

        # Velocity is checked first, so even though strikes also triggers,
        # we only get "velocity"
        assert result == "velocity"


# ---------------------------------------------------------------------------
# SecurityService — forensics
# ---------------------------------------------------------------------------


class TestForensics:
    """Tests for forensic observation tracking."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from api.services.security_service import SecurityService

        self.svc = SecurityService()
        self.svc._redis = MagicMock()
        yield

    def test_flag_for_forensics_adds_to_zset(self):
        self.svc._flag_for_forensics("10.0.0.20")

        call_args = self.svc._redis.zadd.call_args
        assert call_args[0][0] == "security:flagged"
        assert "10.0.0.20" in call_args[0][1]
        # Score should be in the future (~now + 3600)
        score = list(call_args[0][1].values())[0]
        assert score > _time.time()

    def test_is_flagged_for_forensics_true(self):
        self.svc._redis.zremrangebyscore.return_value = 0
        self.svc._redis.zscore.return_value = _time.time() + 1800

        assert self.svc.is_flagged_for_forensics("10.0.0.20") is True

    def test_is_flagged_for_forensics_false(self):
        self.svc._redis.zremrangebyscore.return_value = 1
        self.svc._redis.zscore.return_value = None

        assert self.svc.is_flagged_for_forensics("10.0.0.20") is False

    def test_is_flagged_for_forensics_empty_ip(self):
        assert self.svc.is_flagged_for_forensics("") is False
        self.svc._redis.zremrangebyscore.assert_not_called()


# ---------------------------------------------------------------------------
# SecurityService — dashboard helpers
# ---------------------------------------------------------------------------


class TestDashboardHelpers:
    """Tests for admin dashboard query methods."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from api.services.security_service import SecurityService

        self.svc = SecurityService()
        self.svc._redis = MagicMock()
        yield

    def test_get_top_velocity_ips(self):
        self.svc._redis.scan_iter.return_value = [
            b"security:velocity:10.0.0.1",
            b"security:velocity:10.0.0.2",
        ]
        self.svc._redis.get.side_effect = [b"150", b"30"]

        results = self.svc.get_top_velocity_ips(limit=10)

        assert len(results) == 2
        assert results[0] == ("10.0.0.1", 150)  # highest first
        assert results[1] == ("10.0.0.2", 30)

    def test_get_top_velocity_ips_filters_zero(self):
        self.svc._redis.scan_iter.return_value = [
            b"security:velocity:10.0.0.1",
            b"security:velocity:10.0.0.2",
        ]
        self.svc._redis.get.side_effect = [b"0", b"50"]

        results = self.svc.get_top_velocity_ips()

        assert len(results) == 1
        assert results[0] == ("10.0.0.2", 50)

    def test_get_top_strike_ips(self):
        self.svc._redis.scan_iter.return_value = [
            b"security:strikes:10.0.0.5",
        ]
        self.svc._redis.get.return_value = b"12"

        results = self.svc.get_top_strike_ips()

        assert results == [("10.0.0.5", 12)]

    def test_get_banned_ips(self):
        self.svc._redis.zremrangebyscore.return_value = 0
        self.svc._redis.zrange.return_value = [
            (b"10.0.0.99", float("inf")),
            (b"10.0.0.100", 1750000000.0),
        ]

        results = self.svc.get_banned_ips()

        assert len(results) == 2
        assert results[0] == ("10.0.0.99", "permanent")
        assert results[1][0] == "10.0.0.100"
        # Second entry has a human-readable date
        assert "2025" in results[1][1] or "20" in results[1][1]
