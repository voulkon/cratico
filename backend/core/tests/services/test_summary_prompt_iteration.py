"""
Env-gated regression test for the summary prompt iteration harness.

Runs the REAL summary pipeline against a REAL decision — real API calls,
real cost.  Skipped everywhere (CI, local runs) unless the operator opts in:

    SUMMARY_TEST_ADA=<real ada> pytest backend/core/tests/services/test_summary_prompt_iteration.py

Asserts the pipeline completes and produces a non-empty one-liner for the
decision — the same guarantee the email bullets depend on.
"""

import json
import os

import pytest
from django.core.management import call_command

ADA = os.environ.get("SUMMARY_TEST_ADA")

pytestmark = pytest.mark.skipif(
    not ADA,
    reason="set SUMMARY_TEST_ADA=<ada> (and real API credentials) to run this test",
)


@pytest.mark.django_db
def test_summary_prompt_iteration_produces_one_liner():
    """The batch pipeline yields a non-empty one-liner for a real ADA."""
    result = json.loads(
        call_command(
            "test_summary_prompt",
            ada=[ADA],
            no_merge=True,
        )
    )

    assert result["status"] == "COMPLETED", result.get("error")
    per_item = result["per_item_outputs"]
    assert per_item, "no per-decision one-liners produced"
    one_liners = [text for text in per_item.values() if (text or "").strip()]
    assert one_liners, "all one-liners empty"
    assert result["total_input_tokens"] > 0
    assert result["total_output_tokens"] > 0
