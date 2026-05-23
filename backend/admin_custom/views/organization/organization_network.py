from core.models.organizations import (
    Organization,
    OrganizationStatus,
    Signer,
    SignerUnit,
    Unit,
)
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render


@staff_member_required
def organization_network(request):
    """View for visualizing organization networks"""
    org_uid = request.GET.get("org_uid")
    depth = int(request.GET.get("depth", 2))

    # Get initial organization
    org = None
    if org_uid:
        org = Organization.objects.get(pk=org_uid)

    # Get organizations for dropdown
    organizations = Organization.objects.filter(status=OrganizationStatus.ACTIVE)[:100]

    # Build network data
    nodes = []
    edges = []

    if org:
        # Add the main organization
        nodes.append(
            {
                "id": org.uid,
                "label": org.label,
                "group": "organization",
                "title": f"Organization: {org.label}",
                "level": 0,
            }
        )

        # Add units
        for unit in Unit.objects.filter(organization=org):
            nodes.append(
                {
                    "id": f"unit_{unit.uid}",
                    "label": unit.label,
                    "group": "unit",
                    "title": f"Unit: {unit.label}",
                    "level": 1,
                }
            )
            # Connect to organization
            edges.append(
                {
                    "from": org.uid,
                    "to": f"unit_{unit.uid}",
                    "title": "Has Unit",
                    "arrows": "to",
                }
            )

            # Add parent-child unit relationships
            if unit.parent:
                edges.append(
                    {
                        "from": f"unit_{unit.parent.uid}",
                        "to": f"unit_{unit.uid}",
                        "title": "Parent Unit",
                        "arrows": "to",
                        "dashes": True,
                    }
                )

        # Add signers
        for signer in Signer.objects.filter(organization=org):
            nodes.append(
                {
                    "id": f"signer_{signer.uid}",
                    "label": f"{signer.first_name} {signer.last_name}",
                    "group": "signer",
                    "title": f"Signer: {signer.first_name} {signer.last_name}",
                    "level": 2,
                }
            )
            # Connect to organization
            edges.append(
                {
                    "from": org.uid,
                    "to": f"signer_{signer.uid}",
                    "title": "Has Signer",
                    "arrows": "to",
                }
            )

            # Connect signers to units
            for signer_unit in SignerUnit.objects.filter(signer=signer):
                edges.append(
                    {
                        "from": f"signer_{signer.uid}",
                        "to": f"unit_{signer_unit.unit.uid}",
                        "title": f"Position: {signer_unit.position.label}",
                        "arrows": "to",
                    }
                )

        # Add supervisor relationship if depth > 1 and it exists
        if depth > 1 and org.supervisor_org_uid:
            try:
                supervisor = Organization.objects.get(uid=org.supervisor_org_uid)
                nodes.append(
                    {
                        "id": supervisor.uid,
                        "label": supervisor.label,
                        "group": "supervisor",
                        "title": f"Supervisor: {supervisor.label}",
                        "level": -1,
                    }
                )
                edges.append(
                    {
                        "from": supervisor.uid,
                        "to": org.uid,
                        "title": "Supervises",
                        "arrows": "to",
                        "width": 2,
                    }
                )
            except Organization.DoesNotExist:
                pass

    return render(
        request,
        "admin/organization_network.html",
        {
            "organization": org,
            "organizations": organizations,
            "nodes": nodes,
            "edges": edges,
        },
    )
