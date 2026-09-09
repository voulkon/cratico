"""Phases for e2e/clerk.spec.js.

The Clerk spec registers its user inside the test body (a real
E2E_CLERK_EMAIL, not run-scoped) and needs no backend seeding — the Clerk
side lives on the pk_test_ instance. Teardown therefore deletes:
  - any run-scoped e2e_ users (defensive sweep), and
  - the user registered for E2E_CLERK_EMAIL, if present.
"""

import os

from api.e2e_fixtures import shared
from users.models import CustomUser


def teardown(run_id: str) -> dict:
    summary = shared.teardown_run_data(run_id)

    clerk_email = os.environ.get("E2E_CLERK_EMAIL")
    deleted_clerk_users = 0
    if clerk_email:
        deleted_clerk_users, _ = CustomUser.objects.filter(email=clerk_email).delete()

    return {**summary, "clerk_users": deleted_clerk_users}
