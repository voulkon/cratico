"""Phases for e2e/auth.spec.js."""

from api.e2e_fixtures import shared


def setup(run_id: str) -> dict:
    """Seed a Django user the spec logs in with via the API."""
    user = shared.make_user(run_id, slug="auth")
    return {"username": user.username, "email": user.email}


def teardown(run_id: str) -> dict:
    """Remove the seeded user AND any users the spec registered through the
    public /api/auth/register/ endpoint during the run."""
    return shared.teardown_run_data(run_id)
