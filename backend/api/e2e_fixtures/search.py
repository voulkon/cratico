"""
Phases for the search E2E work (issue #137): seed a small, fully run-scoped
graph (org → unit/signer → decision + extraction) so search endpoints have
deterministic data underneath, then remove exactly that data.

The DocumentExtraction post_save signal indexes the document into OpenSearch
(feature flag INDEX_THE_OPENSEARCH); teardown deletes the OpenSearch docs
explicitly (shared.delete_os_document) before removing the rows.
"""

from api.e2e_fixtures import shared
from core.models.document_analysis import DocumentExtraction


def setup(run_id: str) -> dict:
    org = shared.make_organization(run_id)
    unit = shared.make_unit(run_id, org)
    signer = shared.make_signer(run_id, org)
    decision = shared.make_decision(run_id, org, signers=[signer])

    # Give search something textual to rank (auto-indexed to OpenSearch).
    DocumentExtraction.objects.get_or_create(
        decision=decision,
        defaults={
            "raw_text": (
                f"Ε2Ε δοκιμαστικό κείμενο αναζήτησης {run_id}. "
                "Marker content for deterministic e2e search ranking."
            ),
            "extraction_status": "COMPLETED",
        },
    )

    return {
        "organization_uid": org.uid,
        "decision_ada": decision.ada,
        "marker": run_id,
    }


def teardown(run_id: str) -> dict:
    return shared.teardown_run_data(run_id)
