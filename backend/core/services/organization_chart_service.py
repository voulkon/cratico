from typing import Any, Dict, List, Optional

from core.models.organizations import Organization, Signer, SignerUnit, Unit
from core.utils.performance import query_debugger
from django.core.cache import cache


class OrganizationChartService:
    """Service for generating organization chart data"""

    @query_debugger
    def get_organization_chart_data(self, org_uid: Optional[str]) -> Dict[str, Any]:
        """Get hierarchical organization chart data for a specific organization"""
        if not org_uid:
            return {}

        # Check cache first
        cache_key = f"org_chart_{org_uid}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return cached_data

        try:
            org = Organization.objects.get(pk=org_uid)

            # Create root node
            org_chart_data = {
                "id": org.uid,
                "name": org.label,
                "title": "Organization",
                "children": [],
                "relationships": [],  # Will collect ALL relationships
            }

            # Add direct organization signers (not associated with any unit)
            signers_with_units = (
                SignerUnit.objects.filter(unit__organization=org)
                .values_list("signer_id", flat=True)
                .distinct()
            )

            direct_signers = Signer.objects.filter(organization=org).exclude(
                pk__in=signers_with_units
            )

            for signer in direct_signers:
                org_chart_data["children"].append(
                    {
                        "id": signer.uid,
                        "name": f"{signer.first_name} {signer.last_name}",
                        "title": "Signer",
                        "className": "signer-node",
                    }
                )

                # This relationship is correct - direct connection to organization
                org_chart_data["relationships"].append(
                    {"from": org.uid, "to": signer.uid, "label": "Direct Signer"}
                )

            # Get top-level units (no parent)
            top_units = Unit.objects.filter(organization=org, parent__isnull=True)

            # Build unit tree recursively - now with all relationships collected
            all_relationships = []  # Collect all meaningful relationships
            for unit in top_units:
                unit_data, unit_relationships = self._build_unit_tree(unit)
                org_chart_data["children"].append(unit_data)
                all_relationships.extend(unit_relationships)

            # Add all unit-level relationships to org_chart_data
            org_chart_data["relationships"].extend(all_relationships)

            # Cache the result for 1 hour (adjust as needed)
            cache.set(cache_key, org_chart_data, 3600)
            return org_chart_data
        except Organization.DoesNotExist:
            return {}

    def _build_unit_tree(
        self, unit: Unit
    ) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Helper function to build hierarchical unit tree
        Returns: (unit_data, relationships_list)
        """
        # Create unit node
        unit_data = {
            "id": unit.uid,
            "name": unit.label,
            "title": "Unit",
            "children": [],
        }

        # Track relationships separately
        relationships = []

        # Add signers as children
        for signer_unit in SignerUnit.objects.filter(unit=unit).select_related(
            "signer", "position"
        ):
            signer = signer_unit.signer
            position = signer_unit.position

            signer_node = {
                "id": signer.uid,
                "name": f"{signer.first_name} {signer.last_name}",
                "title": position.label,
                "className": "signer-node",
                "positionId": position.uid,  # Add position data
                "positionLabel": position.label,
            }

            unit_data["children"].append(signer_node)

            # Add meaningful relationship information between unit and signer
            relationships.append(
                {"from": unit.uid, "to": signer.uid, "label": position.label}
            )

        # Recursively add child units
        for child_unit in Unit.objects.filter(parent=unit):
            child_unit_data, child_relationships = self._build_unit_tree(child_unit)
            unit_data["children"].append(child_unit_data)

            # Add relationship between parent and child unit
            relationships.append(
                {"from": unit.uid, "to": child_unit.uid, "label": "Child Unit"}
            )

            # Add all relationships from child units
            relationships.extend(child_relationships)

        return unit_data, relationships
