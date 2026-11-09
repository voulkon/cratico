"""
``manage.py recover_counterparts`` argument plumbing.

The service behavior is covered elsewhere; this test ensures the command
resolves a single ADA, forwards the OCR/AI/dry-run options, and reports an
unknown ADA cleanly.
"""

from io import StringIO

import pytest
from conftest import DecisionFactory
from django.core.management import call_command
from django.core.management.base import CommandError

pytestmark = pytest.mark.django_db


class _FakeService:
    calls = []

    def get_candidates(self, **kwargs):
        return []

    def recover_decision(self, decision, **kwargs):
        type(self).calls.append((decision.ada, kwargs))
        return {
            "status": "would_apply",
            "chosen_afm": "899972873",
            "confidence": 0.9,
        }


def test_forwards_single_ada_options(monkeypatch):
    decision = DecisionFactory(ada="6ΧΩΜ469ΗΣΥ-ΒΗ4")
    _FakeService.calls = []
    monkeypatch.setattr(
        "core.management.commands.recover_counterparts.CounterpartRecoveryService",
        _FakeService,
    )

    out = StringIO()
    call_command(
        "recover_counterparts",
        "--ada",
        decision.ada,
        "--dry-run",
        "--no-ocr",
        "--no-ai",
        "--force",
        stdout=out,
    )

    assert _FakeService.calls == [
        (
            decision.ada,
            {
                "apply": None,
                "allow_ocr": False,
                "allow_ai": False,
                "dry_run": True,
                "force": True,
            },
        )
    ]
    assert "would_apply" in out.getvalue()


def test_unknown_ada_raises(monkeypatch):
    monkeypatch.setattr(
        "core.management.commands.recover_counterparts.CounterpartRecoveryService",
        _FakeService,
    )

    with pytest.raises(CommandError):
        call_command(
            "recover_counterparts", "--ada", "DOES-NOT-EXIST", "--dry-run"
        )
