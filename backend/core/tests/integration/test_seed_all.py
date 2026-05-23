import re

import pytest
import responses
from core.services.seed_service import SeedService

pytestmark = pytest.mark.django_db


@pytest.mark.super_slow
def test_seed_all_happy_path(mock_organizations_json):
    """Record all API responses for later replay using VCR"""

    # Pattern that ONLY matches the main organizations endpoint
    main_org_pattern = re.compile(
        r"^https://diavgeia\.gov\.gr/opendata/organizations(\?.*)?$"
    )

    # Explicitly allow passthrough for the diavgeia host
    with responses.RequestsMock(
        assert_all_requests_are_fired=False,
        passthru_prefixes=["https://diavgeia.gov.gr"],
    ) as rsps:  # Corrected pass_through
        # Only mock the main organizations endpoint
        rsps.add(
            responses.GET,
            main_org_pattern,
            json=mock_organizations_json,
            status=200,
        )

        service = SeedService()
        result = service.seed_all(force=True)

    # Basic assertions to ensure it worked
    assert result["status"] == "success"
    # Depending on what seed_all returns, you might need more specific assertions
    # assert "results" in result # Keep or adjust based on actual return value
