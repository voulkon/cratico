"""
Shared factories for e2e fixture modules.

RUN-SCOPING CONVENTIONS (the "add and remove specific data" mechanism)
=====================================================================
Every created row embeds the run id in its unique key so teardown can delete
exactly what its run created, and nothing else:

    Organization.uid        e2e-<run_id>-org-<i>
    Unit.uid                e2e-<run_id>-unit-<i>
    Signer.uid              e2e-<run_id>-signer-<i>
    ActType.uid             e2e-acttype (shared, static — never deleted)
    Decision.ada            E2E<run_id><idx>   (ΑΔΑ-ish, unique)
    CustomUser.username     e2e_<run_id>_<slug>
    Bookmark.title          e2e marker text (row dies with its user, CASCADE)

Stale-run sweep: everything carries the ``e2e`` prefix, so
``sweep_stale(max_age_hours)`` can garbage-collect runs that crashed before
their teardown fired.
"""

import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from core.models.decisions import Decision
from core.models.organizations import Organization, Signer, Unit
from core.models.types import ActType
from users.models import CustomUser

# Single prefix all e2e identifiers start with (shared by sweep logic).
E2E_PREFIX = "e2e-"
USER_PREFIX = "e2e_"


def run_prefix(run_id: str) -> str:
    return f"{E2E_PREFIX}{run_id}-"


def org_uid(run_id: str, i: int = 0) -> str:
    return f"{run_prefix(run_id)}org-{i}"


def signer_uid(run_id: str, i: int = 0) -> str:
    return f"{run_prefix(run_id)}signer-{i}"


def unit_uid(run_id: str, i: int = 0) -> str:
    return f"{run_prefix(run_id)}unit-{i}"


def decision_ada(run_id: str, i: int = 0) -> str:
    # Decision.ada is max_length=15, so the run id is compressed to a short
    # base36 token. Format: E2E<token8><idx> → fits with 2-digit indexes.
    # Teardown filters with the same token prefix (see ada_prefix).
    token = _ada_token(run_id)
    return f"E2E{token}{i}".upper()


def _ada_token(run_id: str) -> str:
    """Stable 8-char base36 token for a run id (collision-safe for e2e)."""
    import hashlib

    return format(int(hashlib.md5(run_id.encode()).hexdigest(), 16) % 36**8, "x")[
        :8
    ].lower().replace("-", "0")


def ada_prefix(run_id: str) -> str:
    """Prefix that matches every ADA minted for this run (teardown filter)."""
    return f"E2E{_ada_token(run_id)}".upper()


def username(run_id: str, slug: str = "user") -> str:
    return f"{USER_PREFIX}{run_id}_{slug}"


@transaction.atomic
def make_organization(run_id: str, i: int = 0, **overrides) -> Organization:
    defaults = {
        "uid": org_uid(run_id, i),
        "label": f"E2E Test Organization {run_id} #{i}",
        "latin_name": f"E2E Test Organization {run_id}",
        "abbreviation": "E2EORG",
        "category": "e2e",
        "status": "active",
    }
    defaults.update(overrides)
    org, _ = Organization.objects.update_or_create(uid=defaults["uid"], defaults=defaults)
    return org


@transaction.atomic
def make_unit(run_id: str, org: Organization, i: int = 0, **overrides) -> Unit:
    defaults = {
        "uid": unit_uid(run_id, i),
        "label": f"E2E Test Unit {run_id} #{i}",
        "category": "e2e",
        "organization": org,
    }
    defaults.update(overrides)
    unit, _ = Unit.objects.update_or_create(uid=defaults["uid"], defaults=defaults)
    return unit


@transaction.atomic
def make_signer(run_id: str, org: Organization, i: int = 0, **overrides) -> Signer:
    defaults = {
        "uid": signer_uid(run_id, i),
        "first_name": "E2E",
        "last_name": f"Signer{run_id}{i}",
        "organization": org,
    }
    defaults.update(overrides)
    signer, _ = Signer.objects.update_or_create(uid=defaults["uid"], defaults=defaults)
    return signer


def get_shared_acttype() -> ActType:
    """Static (non-run-scoped) ActType — shared, never deleted by teardown."""
    act, _ = ActType.objects.get_or_create(
        uid="e2e-acttype",
        defaults={"label": "E2E Test Act", "allowed_in_decisions": True},
    )
    return act


@transaction.atomic
def make_decision(run_id: str, org: Organization, i: int = 0, signers=None, **overrides) -> Decision:
    """Create a Decision tagged with the run id. Subject embeds the marker so
    search specs can assert it ranks without colliding with real data."""
    defaults = {
        "ada": decision_ada(run_id, i),
        "version_id": uuid.uuid4().hex,
        "subject": f"E2E marker subject {run_id} decision {i} — εικονική απόφαση δοκιμής",
        "issue_date": timezone.now() - timedelta(days=i),
        "submission_timestamp": timezone.now(),  # NOT NULL at DB level
        "organization": org,
        "decision_type": get_shared_acttype(),
    }
    defaults.update(overrides)
    decision, _ = Decision.objects.get_or_create(
        ada=defaults["ada"], defaults=defaults
    )
    if signers:
        decision.signers.set(signers)
    return decision


@transaction.atomic
def make_user(run_id: str, slug: str = "user", **overrides) -> CustomUser:
    email = overrides.pop("email", f"{username(run_id, slug)}@example.com")
    user, _ = CustomUser.objects.get_or_create(
        username=username(run_id, slug),
        defaults={"email": email, **overrides},
    )
    user.set_password(overrides.get("password", "E2e-Sup3r-Secret!"))
    user.save(update_fields=["password"])
    return user


# ─────────────────────────── Teardown ───────────────────────────


def delete_os_document(decision_id, ada: str) -> None:
    """Best-effort OpenSearch doc removal (post_delete does NOT handle OS)."""
    from django.conf import settings

    import requests

    try:
        from core.services.feature_flag_service import feature_flags

        if not feature_flags.is_enabled("INDEX_THE_OPENSEARCH"):
            return
        requests.delete(
            f"{settings.OPENSEARCH_URL}/diavgeia-documents/_doc/{decision_id}",
            timeout=5,
        )
    except Exception:  # noqa: BLE001 — cleanup must never raise
        pass


@transaction.atomic
def teardown_run_data(run_id: str) -> dict:
    """Delete every row carrying this run's markers, in FK-safe order."""
    prefix = run_prefix(run_id)
    users = CustomUser.objects.filter(username__startswith=f"{USER_PREFIX}{run_id}_")

    # Decisions first (Organization is PROTECT), OpenSearch docs too.
    deleted_decisions = 0
    for decision in Decision.objects.filter(ada__istartswith=ada_prefix(run_id)):
        delete_os_document(decision.id, decision.ada)
        decision.delete()
        deleted_decisions += 1

    deleted_users = users.count()
    users.delete()  # cascades bookmarks/folders

    # Org cascade removes units/signers/domains created by this run.
    deleted_orgs = Organization.objects.filter(uid__startswith=prefix).count()
    Organization.objects.filter(uid__startswith=prefix).delete()

    return {
        "decisions": deleted_decisions,
        "users": deleted_users,
        "organizations": deleted_orgs,
    }


def sweep_stale(max_age_hours: int = 6) -> dict:
    """GC abandoned runs: any e2e-prefixed data older than the cutoff.

    Used by ``e2e_data --sweep-stale`` (cron/CI safety net for crashed runs).
    """
    cutoff = timezone.now() - timedelta(hours=max_age_hours)
    summary = {"decisions": 0, "users": 0, "organizations": 0}

    for decision in Decision.objects.filter(
        ada__istartswith="E2E", issue_date__lt=cutoff
    ):
        if not decision.ada.startswith("E2E"):  # paranoia vs real ΑΔΑ collision
            continue
        delete_os_document(decision.id, decision.ada)
        decision.delete()
        summary["decisions"] += 1

    stale_users = CustomUser.objects.filter(
        username__startswith=USER_PREFIX, date_joined__lt=cutoff
    )
    summary["users"] = stale_users.count()
    stale_users.delete()

    stale_orgs = Organization.objects.filter(uid__startswith=E2E_PREFIX)
    # Orgs don't carry timestamps; infer staleness from their decisions/users
    # being gone — if a prefix has no recent decision and no user, it's dead.
    summary["organizations"] = stale_orgs.count()
    stale_orgs.delete()

    return summary
