from core.models.organizations import SignerUnit, Unit


def build_unit_tree(unit):
    """Helper function to build hierarchical unit tree"""
    # Create unit node
    unit_data = {"id": unit.uid, "name": unit.label, "title": "Unit", "children": []}

    # Add signers as children
    for signer_unit in SignerUnit.objects.filter(unit=unit).select_related(
        "signer", "position"
    ):
        unit_data["children"].append(
            {
                "id": signer_unit.signer.uid,
                "name": f"{signer_unit.signer.first_name} {signer_unit.signer.last_name}",
                "title": signer_unit.position.label,
                "className": "signer-node",
            }
        )

    # Recursively add child units
    for child_unit in Unit.objects.filter(parent=unit):
        unit_data["children"].append(build_unit_tree(child_unit))

    return unit_data
