"""The counterpart-recovery audit trail is browsable in the custom admin."""

from admin_custom.sites import admin_site
from core.models.counterpart_recovery import CounterpartRecoveryAttempt


def test_counterpart_recovery_attempt_registered():
    model_admin = admin_site._registry.get(CounterpartRecoveryAttempt)
    assert model_admin is not None
    assert model_admin.list_display[1] == "decision_link"
