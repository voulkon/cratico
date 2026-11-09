"""
AI counterpart resolver: strict validation, SYSTEM cost logging, bounded
context windows, and graceful "no API key" behaviour.
"""

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from core.models.ai_interaction_log import AIInteractionLog
from core.services.ai_counterpart_resolver import AICounterpartResolver
from django.conf import settings

pytestmark = pytest.mark.django_db

REAL_AFM = "899972873"
ORG_AFM = "090064864"


def _decision():
    return SimpleNamespace(
        id=42,
        subject="Consulting services for ΙΦΕΤ",
        organization=SimpleNamespace(label="ΙΦΕΤ Μ.Α.Ε.", vat_number=ORG_AFM),
        extra_field_values_json={},
    )


class _FakeProvider:
    def __init__(self, payload, **meta):
        self.payload = payload
        self.meta = meta
        self.calls = 0

    def invoke(self, **kwargs):
        self.calls += 1
        return {
            "success": True,
            "text": self.payload,
            "input_tokens": self.meta.get("input_tokens", 100),
            "output_tokens": self.meta.get("output_tokens", 20),
            "actual_cost_usd": self.meta.get("cost", Decimal("0.0002")),
        }


class _FailingProvider:
    def invoke(self, **kwargs):
        return {
            "success": False,
            "text": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "error": "provider down",
        }


def _patch_provider(monkeypatch, provider):
    monkeypatch.setattr(
        "core.services.ai_counterpart_resolver.get_provider",
        lambda *a, **k: provider,
    )


def test_missing_api_key_skips_without_cost_log(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    result = AICounterpartResolver().resolve(
        decision=_decision(),
        text="ΑΦΜ 899972873",
        detected_afms={REAL_AFM},
        recorded_afm=ORG_AFM,
        candidates=[],
    )

    assert result["status"] == "not_configured"
    assert AIInteractionLog.objects.count() == 0


def test_valid_json_fenced_answer_is_accepted_and_logged(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "test-key")
    payload = "```json\n" + json.dumps(
        {
            "counterpart_afm": REAL_AFM,
            "role": "person",
            "confidence": 0.97,
            "evidence": "ΑΦΜ 899972873",
        }
    ) + "\n```"
    _patch_provider(monkeypatch, _FakeProvider(payload))

    result = AICounterpartResolver().resolve(
        decision=_decision(),
        text="Ο ανάδοχος με ΑΦΜ 899972873.",
        detected_afms={REAL_AFM},
        recorded_afm=ORG_AFM,
        candidates=[],
    )

    assert result["status"] == "ok"
    assert result["afm"] == REAL_AFM
    assert result["confidence"] == pytest.approx(0.90)  # capped
    log = AIInteractionLog.objects.get(trigger="counterpart_recovery")
    assert log.billed_to == "SYSTEM"
    assert log.input_tokens == 100
    assert log.output_tokens == 20
    assert log.cost_usd == Decimal("0.000200")


@pytest.mark.parametrize(
    "answer",
    [ORG_AFM, "123456789"],  # org AFM / not present in detected_afms
)
def test_org_or_unseen_afm_is_rejected(monkeypatch, answer):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "test-key")
    _patch_provider(
        monkeypatch,
        _FakeProvider(json.dumps({"counterpart_afm": answer, "confidence": 0.99})),
    )

    result = AICounterpartResolver().resolve(
        decision=_decision(),
        text=f"ΑΦΜ {REAL_AFM}",
        detected_afms={REAL_AFM},
        recorded_afm=ORG_AFM,
        candidates=[],
    )

    assert result["status"] == "invalid"
    assert result["afm"] is None


def test_provider_failure_is_logged_and_not_raised(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "test-key")
    _patch_provider(monkeypatch, _FailingProvider())

    result = AICounterpartResolver().resolve(
        decision=_decision(),
        text=f"ΑΦΜ {REAL_AFM}",
        detected_afms={REAL_AFM},
        recorded_afm=ORG_AFM,
        candidates=[],
    )

    assert result["status"] == "error"
    assert AIInteractionLog.objects.filter(status="FAILED").exists()


def test_context_windows_ignore_unrelated_pages():
    # 50 "pages": the only useful AFM is deep in the document, outside any
    # head truncation.  The resolver must send context around the span only.
    sentinel = "START-OF-DOCUMENT-UNIQUE"
    filler = "ΑΣΧΕΤΟ ΚΕΙΜΕΝΟ ΧΩΡΙΣ ΑΦΜ. " * 800
    text = (
        sentinel
        + filler
        + "Ο ανάδοχος έχει ΑΦΜ 899972873 και έδρα την Αθήνα."
        + filler
    )
    position = text.index("899972873")

    user_text = AICounterpartResolver._build_user_text(
        _decision(),
        text,
        ORG_AFM,
        ORG_AFM,
        [
            {
                "afm": REAL_AFM,
                "score": 0.9,
                "signals": ["near_afm_keyword"],
                "span_start": position,
                "span_end": position + len(REAL_AFM),
            }
        ],
    )

    assert REAL_AFM in user_text
    assert "ανάδοχος" in user_text
    # The unrelated start of the document is not shipped wholesale.
    assert len(user_text) < 5000
    assert sentinel not in user_text
