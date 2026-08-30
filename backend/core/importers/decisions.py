import decimal
from typing import Any, Dict, Iterable, List, Tuple

from core.constants.decision_import_constants import PICKLE_DIR
from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.importers.base import BaseImporter
from core.importers.signer import SignerImporter
from core.importers.unit import UnitImporter
from core.models import Organization, Signer, Unit
from core.models.decisions import Attachment, Decision, DecisionAmountKAE
from core.models.entities import DecisionAmountField, DecisionEntityRelationship
from core.models.types import ActType
from core.services.entity_extraction_service import EntityExtractionService
from diavgeia_api.models.decisions import Decision as DecisionDTO
from django.core.exceptions import FieldDoesNotExist, ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone
from loguru import logger


class DecisionImporter(BaseImporter):
    """
    Imports Decision objects from Diavgeia API DTOs to the database.

    ARCHITECTURAL NOTE (2026-01-03):
    This importer now focuses ONLY on importing decision data (basic fields, relations, attachments).
    Entity extraction, company enrichment, document processing, and indexing are handled by
    DecisionPipelineOrchestrator to prevent task bursts and provide better control.

    For full processing pipeline, use:
        orchestrator = DecisionPipelineOrchestrator()
        orchestrator.run_pipeline(decision_ada, skip_opensearch=True)

    Legacy methods like extract_and_save_amounts() and _trigger_company_data_fetching()
    are kept for backward compatibility with management commands but are NOT called
    from import_many() anymore.
    """

    model = Decision
    uid_field = "ada"

    # --- Explicit Field Map ---
    # Define the mappings directly here for fields where
    # DTO name (camelCase) differs from Model name (snake_case)
    # OR for fields needing explicit mapping like privateData -> has_private_data
    field_map = {
        # DTO Field Name       : Model Field Name
        "protocolNumber": "protocol_number",
        "issueDate": "issue_date",
        "thematicCategoryIds": "thematic_category_ids",  # Stored as JSON list in model
        "privateData": "has_private_data",
        "submissionTimestamp": "submission_timestamp",
        "publishTimestamp": "publish_timestamp",
        "versionId": "version_id",
        "correctedVersionId": "corrected_version_id",
        "documentUrl": "document_url",
        "documentChecksum": "document_checksum",
        # 'url' has the same name in DTO and Model, so no mapping needed
        # 'subject' has the same name
        # 'status' has the same name
        # 'warnings' has the same name
        # 'ada' is the uid_field, handled separately
    }

    # Fields handled by specific logic (lookup, relations, extraction)
    # and should NOT be processed by the generic loop in _to_defaults
    special_handling_fields = [
        "organizationId",  # Needs lookup -> organization_id (FK)
        "signerIds",  # Needs lookup + M2M handling
        "unitIds",  # Needs lookup + M2M handling
        "attachments",  # Needs separate object creation (1-M)
        "extraFieldValues",  # Needs extraction for promoted fields + raw JSON
        "decisionTypeId",
    ]

    def __init__(self, import_job=None):
        # Initialize the organization cache as an instance attribute
        self.org_cache = {}
        # Initialize entity extraction service
        self.entity_extraction_service = EntityExtractionService()
        self.import_job = import_job

    # Fields automatically managed or never updated
    do_not_update_fields = ["created_at", "id"]  # Django auto fields

    def _to_defaults(self, dto) -> dict[str, Any]:
        """
        Convert dto -> {model_field: value} applying field_map.
        Focuses on direct mappings.
        Excludes UID field and fields marked for special handling.
        """
        model_fields = self._model_field_names()
        updateable_fields = model_fields - set(self.do_not_update_fields)
        defaults = {}

        # Use Pydantic's recommended way to get data dictionary
        # Try WITHOUT exclude_unset first to see if it captures protocolNumber etc.
        if hasattr(dto, "model_dump"):
            try:
                # Prioritize getting all fields first
                dto_data = dto.model_dump()
            except Exception:  # Fallback if needed
                dto_data = dto.model_dump(exclude_unset=True)  # Pydantic v2+

        elif hasattr(dto, "dict"):
            try:
                # Prioritize getting all fields first
                dto_data = dto.dict()
            except Exception:  # Fallback if needed
                dto_data = dto.dict(exclude_unset=True)  # Pydantic v1
        else:
            dto_data = {k: v for k, v in dto.__dict__.items() if not k.startswith("_")}

        fields_to_skip = {self.uid_field} | set(self.special_handling_fields)

        logger.trace(
            f"DTO Data Keys for ADA {getattr(dto, 'ada', 'N/A')}: {list(dto_data.keys())}"
        )  # Log input keys

        for dto_attr, value in dto_data.items():
            if dto_attr in fields_to_skip:
                # logger.debug(f"Skipping {dto_attr}: Marked for special handling or UID.")
                continue

            # Get the target model field name using the map, fall back to dto_attr name
            model_field = self.field_map.get(dto_attr, dto_attr)

            if model_field in updateable_fields:
                defaults[model_field] = value
                # logger.debug(f"Mapped {dto_attr} -> {model_field}")
            else:
                # Log why a field wasn't mapped if needed
                # This helps diagnose if a field exists in DTO but not Model,
                # or if it's in do_not_update_fields
                if model_field not in model_fields:
                    logger.debug(
                        f"Skipping {dto_attr} -> {model_field}: Target field not found in Model."
                    )
                elif model_field not in updateable_fields:
                    logger.debug(
                        f"Skipping {dto_attr} -> {model_field}: Field is not updateable (e.g., created_at)."
                    )
                else:  # Should not happen based on logic, but for completeness
                    logger.debug(
                        f"Skipping {dto_attr} -> {model_field}: Not in updateable fields for unknown reason."
                    )

        logger.trace(
            f"Defaults generated by _to_defaults for ADA {getattr(dto, 'ada', 'N/A')}: {list(defaults.keys())}"
        )  # Log output keys
        return defaults

    def _truncate_long_string_fields(self, defaults: dict[str, Any], ada: str) -> None:
        """
        Truncate any CharField value that exceeds its column limit.

        Some organizations stuff the full subject/description text into
        ``protocolNumber`` (a Diavgeia quirk), but this also guards any other
        varchar column from ``StringDataRightTruncation`` at the DB layer.
        """
        for field_name, value in list(defaults.items()):
            if not isinstance(value, str):
                continue
            try:
                model_field = self.model._meta.get_field(field_name)
            except FieldDoesNotExist:
                continue
            max_length = getattr(model_field, "max_length", None)
            if max_length is not None and len(value) > max_length:
                logger.warning(
                    f"Truncating {field_name} for ADA {ada} "
                    f"from {len(value)} to {max_length} chars"
                )
                defaults[field_name] = value[:max_length]

    def _extract_promoted_fields(self, dto: DecisionDTO) -> Dict[str, Any]:
        """Extracts specific fields from extraFieldValues for promotion."""
        promoted = {
            "financial_year": None,
            "amount": None,
            "currency": None,
            "extra_field_values_json": None,
        }
        if dto.extraFieldValues:
            efv = dto.extraFieldValues
            promoted["financial_year"] = efv.financialYear

            # Determine primary amount (example: prefer amountWithVAT)
            primary_amount_source = efv.amountWithVAT or efv.awardAmount
            if primary_amount_source:
                promoted["amount"] = (
                    decimal.Decimal(str(primary_amount_source.amount))
                    if primary_amount_source.amount is not None
                    else None
                )
                promoted["currency"] = primary_amount_source.currency

            # Store the raw JSON
            if hasattr(efv, "model_dump"):
                promoted["extra_field_values_json"] = efv.model_dump(exclude_unset=True)
            elif hasattr(efv, "dict"):
                promoted["extra_field_values_json"] = efv.dict(exclude_unset=True)

        return promoted

    def _fetch_missing_entities(self, entity_ids, entity_type):
        """
        Centralized method to fetch missing entities (signers, units, organizations)
        with proper dependency resolution - fetches organizations when needed.
        """
        fetched_uids = []
        fetcher = DiavgeiaFetcher()

        if entity_type == "signer":
            importer = SignerImporter()
            model_class = Signer
            fetch_method = fetcher.fetch_a_signer
        elif entity_type == "unit":
            importer = UnitImporter()
            model_class = Unit
            fetch_method = fetcher.fetch_a_unit
        elif entity_type == "organization":
            from core.importers.organization import OrganizationImporter

            importer = OrganizationImporter()
            model_class = Organization
            fetch_method = fetcher.fetch_an_organization
        else:
            logger.error(f"Unknown entity type: {entity_type}")
            return []

        for entity_id in entity_ids:
            try:
                # Fetch the entity from Diavgeia API
                entity_dto = fetch_method(entity_id)

                if not entity_dto:
                    logger.warning(
                        f"Could not fetch {entity_type} data for ID {entity_id}"
                    )
                    continue

                # Special handling for signers without organization IDs
                if entity_type == "signer" and (
                    not hasattr(entity_dto, "organizationId")
                    or not entity_dto.organizationId
                ):
                    logger.warning(
                        f"Signer {entity_id} has no organization ID - attempting to resolve through units"
                    )

                    # Try to resolve organization through signer's units
                    org_id, resolution_path = self._resolve_signer_organization(
                        entity_id, fetcher
                    )

                    if org_id:
                        # Assign the resolved organization ID to the signer DTO
                        entity_dto.organizationId = org_id
                        entity_dto.resolution_path = (
                            resolution_path  # Store for later use during import
                        )
                        logger.info(
                            f"Resolved organization {org_id} for signer {entity_id} through units"
                        )
                    else:
                        # Use default organization as last resort
                        default_org_uid = self._ensure_default_organization(
                            "signer", entity_id
                        )
                        logger.warning(
                            f"Using default organization for signer {entity_id} - couldn't resolve through units"
                        )

                        # Add resolution failure info to resolution path
                        if "resolution_path" not in locals():
                            resolution_path = {
                                "signer_id": entity_id,
                                "result": "direct_failure",
                                "timestamp": timezone.now().isoformat(),
                            }

                        resolution_path["default_org_used"] = True
                        resolution_path["default_org_id"] = default_org_uid
                        entity_dto.resolution_path = resolution_path

                        # Check if default org exists
                        if default_org_uid in self.org_cache:
                            default_org_exists = self.org_cache[default_org_uid]
                        else:
                            default_org_exists = Organization.objects.filter(
                                uid=default_org_uid
                            ).exists()
                            self.org_cache[default_org_uid] = default_org_exists

                        if not default_org_exists:
                            try:
                                # Create default organization
                                Organization.objects.create(
                                    uid=default_org_uid,
                                    label="Default Organization for Orphaned Signers",
                                    latin_name="default_signer_org",
                                    status="SYSTEM",
                                    category="SYSTEM",
                                )
                                self.org_cache[default_org_uid] = True
                                logger.info(
                                    f"Created default organization {default_org_uid}"
                                )
                            except Exception as org_err:
                                logger.error(
                                    f"Failed to create default organization: {org_err}"
                                )

                        entity_dto.organizationId = default_org_uid

                # Special handling for units without organization IDs
                if entity_type == "unit" and (
                    not hasattr(entity_dto, "organizationId")
                    or not entity_dto.organizationId
                ):
                    logger.warning(
                        f"Unit {entity_id} has no organization ID - attempting to resolve through parent chain"
                    )

                    # Try to resolve organization through parent units - NOW RETURNS RESOLUTION PATH TOO
                    org_id, resolution_path, units_to_import = (
                        self._resolve_unit_organization_through_parents(
                            entity_id, fetcher, max_depth=5
                        )
                    )

                    if org_id:
                        # FIX: Sort units so parents are imported before children
                        # Build a dependency graph and import in correct order
                        units_by_id = {
                            unit_id: unit_dto for unit_id, unit_dto in units_to_import
                        }
                        imported_units = set()

                        def import_unit_with_dependencies(
                            target_unit_id, target_unit_dto
                        ):
                            if target_unit_id in imported_units:
                                return

                            # If this unit has a parent that's in our import list, import parent first
                            if (
                                hasattr(target_unit_dto, "parentId")
                                and target_unit_dto.parentId
                            ):
                                parent_id = target_unit_dto.parentId
                                if (
                                    parent_id in units_by_id
                                    and parent_id not in imported_units
                                ):
                                    parent_dto = units_by_id[parent_id]
                                    import_unit_with_dependencies(parent_id, parent_dto)

                            # Now import this unit
                            target_unit_dto._resolved_organization_id = org_id
                            target_unit_dto._resolution_path = resolution_path

                            with transaction.atomic():
                                import_defaults = {
                                    "organization_id": org_id,
                                    "resolution_path": resolution_path,
                                }

                                # Only set parent if it exists (either imported by us or already in DB)
                                if (
                                    hasattr(target_unit_dto, "parentId")
                                    and target_unit_dto.parentId
                                ):
                                    parent_id = target_unit_dto.parentId
                                    if Unit.objects.filter(uid=parent_id).exists():
                                        import_defaults["parent_id"] = parent_id
                                    # If parent doesn't exist and isn't in our import list, skip setting parent
                                    # The unit will be imported without parent relationship

                                created_count = importer.import_many(
                                    [target_unit_dto], defaults=import_defaults
                                )
                                imported_units.add(target_unit_id)

                                if created_count > 0:
                                    logger.info(
                                        f"Imported unit {target_unit_id} with organization {org_id}"
                                    )

                        # Import all units in dependency order
                        for unit_id, unit_dto in units_to_import:
                            import_unit_with_dependencies(unit_id, unit_dto)

                        # Assign the resolved organization ID to the unit DTO
                        entity_dto._resolved_organization_id = org_id
                        entity_dto._resolution_path = (
                            resolution_path  # Store for later use during import
                        )
                        logger.info(
                            f"Resolved organization {org_id} for unit {entity_id} through parent chain"
                        )

                    else:
                        # Use default organization as last resort
                        default_org_uid = self._ensure_default_organization(
                            "unit", entity_id
                        )
                        logger.warning(
                            f"Using default organization for unit {entity_id} - couldn't find through parents"
                        )

                        # Add resolution failure info to resolution path
                        if "resolution_path" not in locals():
                            resolution_path = {
                                "unit_id": entity_id,
                                "result": "direct_failure",
                                "timestamp": timezone.now().isoformat(),
                            }

                        resolution_path["default_org_used"] = True
                        resolution_path["default_org_id"] = default_org_uid
                        entity_dto.resolution_path = resolution_path

                        # Check if default org exists
                        if default_org_uid in self.org_cache:
                            default_org_exists = self.org_cache[default_org_uid]
                        else:
                            default_org_exists = Organization.objects.filter(
                                uid=default_org_uid
                            ).exists()
                            self.org_cache[default_org_uid] = default_org_exists

                        if not default_org_exists:
                            try:
                                # Create default organization
                                Organization.objects.create(
                                    uid=default_org_uid,
                                    label="Default Organization for Orphaned Units",
                                    latin_name="default_org",
                                    status="SYSTEM",
                                    category="SYSTEM",
                                )
                                self.org_cache[default_org_uid] = True
                                logger.info(
                                    f"Created default organization {default_org_uid}"
                                )
                            except Exception as org_err:
                                logger.error(
                                    f"Failed to create default organization: {org_err}"
                                )

                        entity_dto.organizationId = default_org_uid

                # Regular organization dependency handling (for both signers and units)
                if entity_type in ["signer", "unit"] and hasattr(
                    entity_dto, "organizationId"
                ):
                    org_id = entity_dto.organizationId

                    # Skip entities without organization ID (they'll fail validation)
                    if not org_id:
                        logger.warning(
                            f"{entity_type.capitalize()} {entity_id} has no organization ID, skipping"
                        )
                        continue

                    # Check cache first, then database if not in cache
                    if org_id in self.org_cache:
                        org_exists = self.org_cache[org_id]
                    else:
                        org_exists = Organization.objects.filter(uid=org_id).exists()
                        self.org_cache[org_id] = org_exists

                    # Check if the organization exists
                    if not org_exists:
                        logger.info(
                            f"Organization {org_id} not found for {entity_type} {entity_id}. Fetching it now..."
                        )

                        # First try to fetch the organization from API
                        org_dto = fetcher.fetch_an_organization(org_id)

                        if org_dto:
                            # Import the organization
                            from core.importers.organization import OrganizationImporter

                            org_importer = OrganizationImporter()
                            org_created_count = org_importer.import_many([org_dto])

                            if org_created_count > 0:
                                self.org_cache[org_id] = True
                                logger.info(
                                    f"Successfully imported organization {org_id} for {entity_type} {entity_id}"
                                )
                            else:
                                # Organization might already exist and was updated
                                logger.info(
                                    f"Organization {org_id} already exists or was updated"
                                )
                        else:
                            # Create a placeholder only if the org can't be fetched
                            logger.warning(
                                f"Could not fetch organization {org_id} from API. Creating placeholder."
                            )
                            try:
                                # Create minimal placeholder to satisfy FK constraint
                                Organization.objects.create(
                                    uid=org_id,
                                    label=f"Unknown Organization {org_id}",
                                    status="UNKNOWN",
                                    category="UNKNOWN",
                                )
                                self.org_cache[org_id] = (
                                    True  # Mark as existing in cache
                                )
                                logger.info(
                                    f"Created placeholder for organization {org_id}"
                                )
                            except Exception as org_err:
                                logger.error(
                                    f"Failed to create placeholder for org {org_id}: {org_err}"
                                )
                                continue  # Skip this entity if we can't fulfill its org dependency

                # Now import the entity
                with transaction.atomic():
                    import_defaults = {}
                    if hasattr(entity_dto, "_resolved_organization_id"):
                        import_defaults["organization_id"] = (
                            entity_dto._resolved_organization_id
                        )
                    if hasattr(entity_dto, "_resolution_path"):
                        import_defaults["resolution_path"] = entity_dto._resolution_path

                    if import_defaults:
                        created_count = importer.import_many(
                            [entity_dto], defaults=import_defaults
                        )
                    else:
                        created_count = importer.import_many([entity_dto])

                    if created_count > 0:
                        # Add this entity to our list of available entities
                        fetched_entity = model_class.objects.get(uid=entity_dto.uid)
                        fetched_uids.append(fetched_entity.uid)
                        logger.info(
                            f"Successfully imported missing {entity_type}: "
                            f"{getattr(fetched_entity, 'first_name', '')} "
                            f"{getattr(fetched_entity, 'last_name', '')} "
                            f"{getattr(fetched_entity, 'name', '')} "
                            f"({entity_id})"
                        )
                    else:
                        try:
                            # Entity might already exist and was updated
                            fetched_entity = model_class.objects.get(uid=entity_dto.uid)
                            fetched_uids.append(fetched_entity.uid)
                            logger.info(
                                f"Successfully updated existing {entity_type}: "
                                f"{getattr(fetched_entity, 'first_name', '')} "
                                f"{getattr(fetched_entity, 'last_name', '')} "
                                f"{getattr(fetched_entity, 'name', '')} "
                                f"({entity_id})"
                            )
                        except model_class.DoesNotExist:
                            logger.warning(
                                f"Failed to import missing {entity_type} with ID {entity_id}"
                            )
            except Exception as e:
                logger.error(f"Error fetching/importing {entity_type} {entity_id}: {e}")

        return fetched_uids

    def _get_related_pks(
        self, dto: DecisionDTO
    ) -> Tuple[str | None, List[str], List[str], str | None]:
        """
        Looks up the primary keys for Organization, Signers, Units, and ActType.
        Returns UIDs as strings, with None for missing relations.
        """
        org_pk_uid = None
        signer_pk_uids = []
        unit_pk_uids = []
        decision_type_uid = None

        # Organization (using uid as PK)
        if dto.organizationId:
            # Check organization cache first
            if dto.organizationId in self.org_cache:
                org_exists = self.org_cache[dto.organizationId]
            else:
                # Not in cache, check database
                org_exists = Organization.objects.filter(
                    uid=dto.organizationId
                ).exists()
                self.org_cache[dto.organizationId] = org_exists

            if org_exists:
                org = Organization.objects.only("uid").get(uid=dto.organizationId)
                org_pk_uid = org.uid
            else:
                # Try to fetch missing org
                fetched_org_uids = self._fetch_missing_entities(
                    [dto.organizationId], "organization"
                )
                if fetched_org_uids:
                    org_pk_uid = fetched_org_uids[0]
                    self.org_cache[org_pk_uid] = True  # Update cache
                else:
                    logger.warning(
                        f"Organization with uid '{dto.organizationId}' not found and could not be fetched. "
                        f"Decision ADA '{dto.ada}' will be saved with null organization."
                    )
                    org_pk_uid = None

        # Signers (using uid as PK)
        if dto.signerIds:
            # Fetch signers' UIDs in one query
            signers_qs = Signer.objects.filter(uid__in=dto.signerIds).values_list(
                "uid", flat=True
            )
            signer_pk_uids = list(signers_qs)

            # Fetch missing signers on the spot
            if len(signer_pk_uids) != len(dto.signerIds):
                missing_signers = set(dto.signerIds) - set(signer_pk_uids)
                logger.info(
                    f"Fetching {len(missing_signers)} missing signers for ADA '{dto.ada}'"
                )

                # Use the centralized method to fetch missing signers
                fetched_signer_uids = self._fetch_missing_entities(
                    missing_signers, "signer"
                )
                signer_pk_uids.extend(fetched_signer_uids)

        # Units (assuming uid is PK)
        if dto.unitIds:
            # Fetch units' UIDs in one query
            units_qs = Unit.objects.filter(uid__in=dto.unitIds).values_list(
                "uid", flat=True
            )
            unit_pk_uids = list(units_qs)

            if len(unit_pk_uids) != len(dto.unitIds):
                missing_units = set(dto.unitIds) - set(unit_pk_uids)
                logger.warning(
                    f"Could not find all units for ADA '{dto.ada}'. Found {len(unit_pk_uids)} out of {len(dto.unitIds)}. "
                    f"Missing units: {missing_units}"
                )

                # Use the centralized method to fetch missing units
                fetched_unit_uids = self._fetch_missing_entities(missing_units, "unit")
                unit_pk_uids.extend(fetched_unit_uids)

        # Act Type (decision type)
        if dto.decisionTypeId:
            try:
                act_type = ActType.objects.only("uid").get(uid=dto.decisionTypeId)
                decision_type_uid = act_type.uid
            except ObjectDoesNotExist:
                logger.warning(
                    f"ActType with uid '{dto.decisionTypeId}' not found for Decision ADA '{dto.ada}'. "
                    f"Decision will be saved with null decision type."
                )
                # Don't raise - allow null decision type
        else:
            logger.warning(f"Decision {dto.ada} has no decisionTypeId")

        return org_pk_uid, signer_pk_uids, unit_pk_uids, decision_type_uid

    def _sync_attachments(self, decision_instance: Decision, dto: DecisionDTO):
        """Creates or updates attachments for a given decision."""
        if not dto.attachments:
            # Optional: Delete existing attachments if DTO has none?
            # decision_instance.attachments.all().delete()
            return

        # Keep track of attachment IDs from the DTO to potentially remove orphans
        dto_attachment_ids = {att.id for att in dto.attachments}
        current_db_attachments = {
            att.attachment_id: att for att in decision_instance.attachments.all()
        }

        for att_dto in dto.attachments:
            defaults = {
                "description": att_dto.description,
                "filename": att_dto.filename,
                "mime_type": att_dto.mimeType,
                "checksum": att_dto.checksum,
            }
            # Using attachment_id from DTO as the unique key *per decision*
            obj, created = Attachment.objects.update_or_create(
                decision=decision_instance,
                attachment_id=att_dto.id,  # Use the ID from Diavgeia
                defaults=defaults,
            )
            # logger.debug(f"Attachment {att_dto.id} {'created' if created else 'updated'}.")

        # Optional: Remove attachments present in DB but not in the latest DTO
        ids_to_delete = set(current_db_attachments.keys()) - dto_attachment_ids
        if ids_to_delete:
            Attachment.objects.filter(
                decision=decision_instance, attachment_id__in=ids_to_delete
            ).delete()
            logger.debug(
                f"Deleted {len(ids_to_delete)} orphan attachments for ADA {decision_instance.ada}."
            )

    def _sync_kae_amounts(self, decision_instance: Decision, dto: DecisionDTO):
        """Creates or updates KAE amounts for a given decision."""
        kae_list = (
            dto.extraFieldValues.amountWithKae
            if dto.extraFieldValues and dto.extraFieldValues.amountWithKae
            else []
        )

        if not kae_list:
            # Optional: Delete existing KAEs if DTO has none?
            # decision_instance.kae_amounts.all().delete()
            return

        # [OK] HANDLE BOTH OLD (objects) AND NEW (dicts) FORMATS - FIRST OCCURRENCE
        dto_kae_codes = set()
        for kae in kae_list:
            if isinstance(kae, dict):
                # New nuclear format - it's a dictionary
                kae_code = kae.get("kae")
            else:
                # Old format - it's an object with .kae attribute
                kae_code = getattr(kae, "kae", None)

            if kae_code:
                dto_kae_codes.add(kae_code)

        # dto_kae_codes = {kae.kae for kae in kae_list}  # ← DELETE THIS LINE!

        current_db_kaes = {kae.kae: kae for kae in decision_instance.kae_amounts.all()}

        for kae_dto in kae_list:
            # [OK] HANDLE BOTH FORMATS HERE TOO
            if isinstance(kae_dto, dict):
                kae_code = kae_dto.get("kae")
                amount_value = kae_dto.get("amountWithVAT")
            else:
                kae_code = getattr(kae_dto, "kae", None)
                amount_value = getattr(kae_dto, "amountWithVAT", None)

            try:
                amount_decimal = (
                    decimal.Decimal(str(amount_value))
                    if amount_value is not None
                    else decimal.Decimal("0.00")
                )
            except (TypeError, decimal.InvalidOperation):
                logger.warning(
                    f"Invalid KAE amount '{amount_value}' for KAE '{kae_code}' in ADA '{decision_instance.ada}'. Using 0.00."
                )
                amount_decimal = decimal.Decimal("0.00")

            defaults = {
                "amount": amount_decimal,
            }
            # Using KAE code as the unique key *per decision*
            obj, created = DecisionAmountKAE.objects.update_or_create(
                decision=decision_instance, kae=kae_code, defaults=defaults
            )

        # Optional: Remove KAE amounts present in DB but not in the latest DTO
        kaes_to_delete = set(current_db_kaes.keys()) - dto_kae_codes
        if kaes_to_delete:
            DecisionAmountKAE.objects.filter(
                decision=decision_instance, kae__in=kaes_to_delete
            ).delete()
            logger.debug(
                f"Deleted {len(kaes_to_delete)} orphan KAE amounts for ADA {decision_instance.ada}."
            )

    @transaction.atomic  # Ensure all operations for a batch succeed or fail together
    def import_many(
        self, dtos: Iterable[DecisionDTO], *, defaults: dict[str, Any] | None = None
    ) -> int:
        """
        Imports multiple Decision DTOs, handling relations and promoted fields.
        Now also extracts AFM entities and triggers company data fetching.

        Args:
            dtos: Decision DTOs to import.
            defaults: Optional extra values merged into each decision (e.g. import_job).

        Returns:
            int: The number of *new* Decision objects created.
        """
        # Reset org_cache for each batch to prevent extremely large caches across batches
        self.org_cache = {}
        external_defaults = defaults or {}

        created_count = 0
        processed_count = 0
        skipped_count = 0

        for dto in dtos:
            processed_count += 1
            if not dto.ada:
                logger.warning(
                    f"Skipping decision DTO with missing ADA. Subject: {dto.subject[:50]}..."
                )
                skipped_count += 1
                continue

            logger.trace(f"Processing ADA: {dto.ada}")

            try:
                # 1. Lookup related object PKs (Organization, Signers, Units, ActType)
                org_uid, signer_uids, unit_uids, decision_type_uid = (
                    self._get_related_pks(dto)
                )

                # 2. Prepare direct fields and promoted fields for the Decision model
                dto_defaults = self._to_defaults(dto)
                promoted_fields = self._extract_promoted_fields(dto)
                dto_defaults.update(promoted_fields)

                # Handle organization - this is required in the model, so we skip if missing
                if org_uid is None:
                    logger.error(
                        f"Cannot import Decision {dto.ada} without an organization"
                    )
                    skipped_count += 1
                    continue

                dto_defaults["organization_id"] = org_uid

                # Add the decision type FK - use the new field name
                if decision_type_uid:
                    dto_defaults["decision_type_id"] = decision_type_uid

                # Apply caller-supplied defaults (e.g. import_job)
                dto_defaults.update(external_defaults)

                # Truncate any varchar fields that exceed their column limits
                # (e.g. organizations stuffing the subject into protocolNumber).
                self._truncate_long_string_fields(dto_defaults, dto.ada)

                # 3. Create or Update the main Decision object
                decision_instance, created = self.model.objects.update_or_create(
                    ada=dto.ada, defaults=dto_defaults
                )
                if created:
                    created_count += 1
                    logger.trace(f"Created new Decision: {dto.ada}")
                # else:
                #     logger.debug(f"Updated existing Decision: {dto.ada}")

                # 4. Handle Many-to-Many relationships
                decision_instance.signers.set(signer_uids)
                decision_instance.units.set(unit_uids)
                # logger.debug(f"Set {len(signer_pks)} signers and {len(unit_pks)} units for {dto.ada}")

                # 5. Handle One-to-Many relationships (Attachments, KAE Amounts)
                self._sync_attachments(decision_instance, dto)
                self._sync_kae_amounts(decision_instance, dto)

                # NOTE: Entity extraction, amounts, and company data fetching
                # are now handled by DecisionPipelineOrchestrator for better control
                # and to prevent task bursts. See orchestrator.run_pipeline()

            except Exception as e:
                logger.exception(f"Failed to import decision ADA '{dto.ada}': {e}")
                skipped_count += 1
                continue

        logger.debug(
            f"Import finished. Processed: {processed_count}. Created: {created_count}. "
            f"Skipped: {skipped_count}."
        )

        return created_count

    def _link_amounts_to_relationships(self, decision: Decision):
        """Link DecisionAmountField records to their corresponding DecisionEntityRelationship records."""
        amount_fields = DecisionAmountField.objects.filter(
            decision=decision, associated_relationship__isnull=True
        )
        relationships = DecisionEntityRelationship.objects.filter(decision=decision)

        for amount_field in amount_fields:
            # Skip container-level amounts (those without a dot in parent_key_path)
            if "." not in amount_field.parent_key_path:
                logger.debug(
                    f"Skipping container-level amount {amount_field.parent_key_path} "
                    f"for decision {decision.ada}"
                )
                continue

            # Find matching relationship based on container path
            amount_container = (
                amount_field.parent_key_path.rsplit(".", 1)[0]
                if "." in amount_field.parent_key_path
                else amount_field.parent_key_path
            )

            for relationship in relationships:
                rel_container = (
                    relationship.parent_key_path.rsplit(".", 1)[0]
                    if "." in relationship.parent_key_path
                    else relationship.parent_key_path
                )

                if rel_container == amount_container:
                    # Found a match, link them
                    amount_field.associated_relationship = relationship
                    amount_field.save(update_fields=["associated_relationship"])
                    logger.debug(
                        f"Linked amount field {amount_field.id} to relationship {relationship.id} "
                        f"via container {amount_container}"
                    )
                    break

    def _trigger_company_data_fetching(self, entities: List["AFMEntity"]):  # type: ignore
        """Trigger company data fetching for extracted entities."""
        from core.tasks import fetch_company_data_for_single_afm

        # Get unique AFMs that need company data
        afms_needing_data = []
        for entity in entities:
            # Check if we already have company data for this AFM
            from core.models.companies import Company

            if not Company.objects.filter(afm=entity.afm).exists():
                if entity.afm not in afms_needing_data:
                    afms_needing_data.append(entity.afm)

        if afms_needing_data:
            logger.info(
                f"Triggering company data fetch for {len(afms_needing_data)} AFMs"
            )
            # Trigger async task
            for afm in afms_needing_data:
                fetch_company_data_for_single_afm.delay(afm)
                ...
                # fetch_company_data_for_entities.delay(afms_needing_data)
        else:
            logger.debug("No new AFMs need company data fetching")

    # Keep the specific method alias if used elsewhere
    def import_decisions(self, decisions: list[DecisionDTO]) -> int:
        return self.import_decisions_in_batches(decisions)

    def import_decisions_in_batches(
        self, decisions: list[DecisionDTO], batch_size: int = 50
    ) -> int:
        """
        Import decisions in smaller batches to prevent transaction rollback issues
        with remote databases. Each batch is processed in its own transaction.
        Includes recovery system to save/restore processed decisions.

        Args:
            decisions: List of DecisionDTO objects to import
            batch_size: Number of decisions to process per transaction

        Returns:
            Total number of decisions created across all batches
        """
        import os
        import pickle
        from datetime import datetime

        from django.db import connection

        total_created = 0
        total_decisions = len(decisions)

        # Create recovery directory
        recovery_dir = f"{PICKLE_DIR}/recovery"
        os.makedirs(recovery_dir, exist_ok=True)

        # Generate recovery file name based on current time
        recovery_file = f"{recovery_dir}/decisions_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pkl"

        logger.info(
            f"Starting batch import of {total_decisions} decisions in batches of {batch_size}"
        )
        logger.info(f"Recovery file: {recovery_file}")

        # Save original decisions to recovery file
        try:
            with open(recovery_file, "wb") as f:
                pickle.dump(
                    {
                        "decisions": decisions,
                        "batch_size": batch_size,
                        "timestamp": datetime.now().isoformat(),
                        "total_count": total_decisions,
                    },
                    f,
                )
            logger.info(
                f"Saved {total_decisions} decisions to recovery file for potential retry"
            )
        except Exception as e:
            logger.warning(f"Could not save recovery file: {e}")

        processed_batches = []

        for i in range(0, total_decisions, batch_size):
            batch = decisions[i : i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (total_decisions + batch_size - 1) // batch_size

            logger.info(
                f"Processing batch {batch_num}/{total_batches} ({len(batch)} decisions)"
            )

            try:
                # Close any stale connections before each batch
                connection.close()

                # Process this batch
                extra_defaults = {}
                if self.import_job is not None:
                    extra_defaults["import_job"] = self.import_job

                batch_created = self.import_many(batch, defaults=extra_defaults)
                total_created += batch_created

                # Track successfully processed batch
                batch_info = {
                    "batch_num": batch_num,
                    "start_idx": i,
                    "end_idx": i + len(batch),
                    "created_count": batch_created,
                    "decision_ids": [d.ada for d in batch],  # Save ADAs for reference
                }
                processed_batches.append(batch_info)

                logger.info(
                    f"Batch {batch_num}/{total_batches} completed: {batch_created} created, {total_created} total so far"
                )

                # Update recovery file with progress
                try:
                    progress_file = f"{recovery_dir}/progress_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pkl"
                    with open(progress_file, "wb") as f:
                        pickle.dump(
                            {
                                "processed_batches": processed_batches,
                                "total_created": total_created,
                                "last_batch": batch_num,
                                "remaining_decisions": (
                                    decisions[i + len(batch) :]
                                    if i + len(batch) < total_decisions
                                    else []
                                ),
                            },
                            f,
                        )
                except Exception as e:
                    logger.warning(f"Could not update progress file: {e}")

            except Exception as e:
                logger.error(f"Error in batch {batch_num}/{total_batches}: {str(e)}")

                # Save remaining decisions for manual retry
                remaining_decisions = decisions[i:]
                retry_file = f"{recovery_dir}/retry_from_batch_{batch_num}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pkl"
                try:
                    with open(retry_file, "wb") as f:
                        pickle.dump(
                            {
                                "remaining_decisions": remaining_decisions,
                                "failed_at_batch": batch_num,
                                "total_processed_so_far": total_created,
                                "error": str(e),
                            },
                            f,
                        )
                    logger.error(
                        f"Saved {len(remaining_decisions)} remaining decisions to {retry_file}"
                    )
                    logger.error(
                        f"You can retry with: python manage.py retry_decision_import --file {retry_file}"
                    )
                except Exception as save_error:
                    logger.error(f"Could not save retry file: {save_error}")

                logger.info(
                    f"Continuing with next batch. Total created so far: {total_created}"
                )
                # Continue with next batch instead of failing entirely
                continue

        # Clean up recovery file on success
        try:
            if total_created > 0:
                os.remove(recovery_file)
                logger.info("Removed recovery file after successful completion")
        except:
            pass

        logger.success(
            f"Batch import completed: {total_created} decisions created from {total_decisions} total"
        )
        return total_created

    def _resolve_unit_organization_through_parents(
        self, unit_id, fetcher, max_depth=5, visited=None
    ):
        """
        Resolves the organization ID for a unit by traversing up the parent chain.
        Checks DB first, then API. Handles cases where IDs might be orgs instead of units.
        Also returns the resolution path for auditing.
        """
        units_to_import = []

        if visited is None:
            visited = set()

        logger.info(f"[UNIT RESOLUTION] Starting resolution for unit {unit_id}")

        # Track the full resolution path
        resolution_path = {
            "unit_id": unit_id,
            "path": [],
            "result": "unknown",
            "timestamp": timezone.now().isoformat(),
        }

        if unit_id in visited:
            logger.warning(
                f"[UNIT RESOLUTION] [FAIL] Detected cycle in parent chain for unit {unit_id}"
            )
            resolution_path["result"] = "cycle_detected"
            return None, resolution_path

        visited.add(unit_id)
        current_id = unit_id
        depth = 0
        logger.debug(
            f"[UNIT RESOLUTION] Starting traversal at depth {depth}, max_depth={max_depth}"
        )

        while depth < max_depth:
            path_step = {
                "id": current_id,
                "depth": depth,
                "checked_db_unit": False,
                "checked_api_unit": False,
                "checked_db_org": False,
                "checked_api_org": False,
            }

            try:
                # 1. First check if it exists as a unit in our DB
                try:
                    existing_unit = Unit.objects.get(uid=current_id)
                    path_step["checked_db_unit"] = True
                    path_step["found_in_db_as_unit"] = True
                    logger.debug(f"[UNIT RESOLUTION] Found {current_id} as unit in DB")

                    if existing_unit.organization_id:
                        path_step["resolved_org_id"] = existing_unit.organization_id
                        resolution_path["path"].append(path_step)
                        resolution_path["result"] = "found_in_db"
                        resolution_path["organization_id"] = (
                            existing_unit.organization_id
                        )
                        resolution_path["resolved_through_unit"] = current_id

                        logger.info(
                            f"[UNIT RESOLUTION] [OK] Found unit {current_id} in DB with organization {existing_unit.organization_id}"
                        )
                        return (
                            existing_unit.organization_id,
                            resolution_path,
                            units_to_import,
                        )

                    # Unit exists in DB but has no organization - check parent
                    if existing_unit.parent_id:
                        if existing_unit.parent_id in visited:
                            path_step["cycle_detected"] = True
                            resolution_path["path"].append(path_step)
                            resolution_path["result"] = "cycle_detected"
                            logger.warning(
                                f"[UNIT RESOLUTION] [FAIL] Would create cycle with parent {existing_unit.parent_id}, stopping"
                            )
                            return None, resolution_path, units_to_import

                        path_step["parent_id"] = existing_unit.parent_id
                        path_step["has_parent"] = True
                        resolution_path["path"].append(path_step)

                        logger.debug(
                            f"[UNIT RESOLUTION] Unit {current_id} in DB has no organization, checking parent {existing_unit.parent_id}"
                        )
                        current_id = existing_unit.parent_id
                        visited.add(current_id)
                        depth += 1
                        continue
                    else:
                        # Unit in DB has no parent - dead end
                        path_step["has_parent"] = False
                        resolution_path["path"].append(path_step)
                        resolution_path["result"] = "no_parent_in_db"
                        logger.warning(
                            f"[UNIT RESOLUTION] [FAIL] Unit {current_id} in DB has no parent, cannot resolve further"
                        )
                        return None, resolution_path, units_to_import

                except Unit.DoesNotExist:
                    path_step["checked_db_unit"] = True
                    path_step["found_in_db_as_unit"] = False
                    logger.debug(
                        f"[UNIT RESOLUTION] {current_id} not found as unit in DB, trying API"
                    )

                    # 2. Not in DB as unit, try API as unit
                    try:
                        unit_dto = fetcher.fetch_a_unit(current_id)
                        path_step["checked_api_unit"] = True

                        if unit_dto:
                            units_to_import.append((current_id, unit_dto))
                            path_step["found_in_api_as_unit"] = True
                            path_step["has_org_id"] = hasattr(
                                unit_dto, "organizationId"
                            ) and bool(unit_dto.organizationId)
                            path_step["has_parent_id"] = hasattr(
                                unit_dto, "parentId"
                            ) and bool(unit_dto.parentId)
                            logger.debug(
                                f"[UNIT RESOLUTION] Found {current_id} as unit in API"
                            )

                            # If there's an organizationId, we found what we're looking for
                            if (
                                hasattr(unit_dto, "organizationId")
                                and unit_dto.organizationId
                            ):
                                path_step["resolved_org_id"] = unit_dto.organizationId
                                resolution_path["path"].append(path_step)
                                resolution_path["result"] = "found_in_api_as_unit"
                                resolution_path["resolved_through_unit"] = current_id
                                resolution_path["organization_id"] = (
                                    unit_dto.organizationId
                                )

                                logger.info(
                                    f"[UNIT RESOLUTION] [OK] Found unit {current_id} in API with organization {unit_dto.organizationId}"
                                )
                                return (
                                    unit_dto.organization_id,
                                    resolution_path,
                                    units_to_import,
                                )

                            # No organization ID - check if there's a parent
                            if hasattr(unit_dto, "parentId") and unit_dto.parentId:
                                if unit_dto.parentId in visited:
                                    path_step["cycle_detected"] = True
                                    resolution_path["path"].append(path_step)
                                    resolution_path["result"] = "cycle_detected"
                                    logger.warning(
                                        f"[UNIT RESOLUTION] [FAIL] Would create cycle with parent {unit_dto.parentId}, stopping"
                                    )
                                    return None, resolution_path, units_to_import

                                path_step["parent_id"] = unit_dto.parentId
                                resolution_path["path"].append(path_step)

                                logger.debug(
                                    f"[UNIT RESOLUTION] Unit {current_id} in API has no organization ID, checking parent {unit_dto.parentId}"
                                )
                                current_id = unit_dto.parentId
                                visited.add(current_id)
                                depth += 1
                                continue

                            # No parent either - dead end
                            path_step["has_parent_id"] = False
                            resolution_path["path"].append(path_step)
                            resolution_path["result"] = "no_parent_in_api"
                            logger.warning(
                                f"[UNIT RESOLUTION] [FAIL] Unit {current_id} in API has no parent ID, cannot resolve further"
                            )
                            return None, resolution_path, units_to_import
                        else:
                            path_step["found_in_api_as_unit"] = False
                            logger.debug(
                                f"[UNIT RESOLUTION] ID {current_id} not found as unit in API, trying as organization"
                            )

                    except Exception as unit_api_error:
                        path_step["checked_api_unit"] = True
                        path_step["api_unit_error"] = str(unit_api_error)
                        logger.warning(
                            f"[UNIT RESOLUTION] Error fetching {current_id} as unit from API: {unit_api_error}"
                        )

                    # 3. Not found as unit, check if it exists as organization in DB
                    try:
                        Organization.objects.get(uid=current_id)
                        path_step["checked_db_org"] = True
                        path_step["found_in_db_as_org"] = True
                        logger.debug(
                            f"[UNIT RESOLUTION] Found {current_id} as organization in DB"
                        )

                        resolution_path["path"].append(path_step)
                        resolution_path["result"] = "found_in_db_as_organization"
                        resolution_path["organization_id"] = current_id

                        logger.info(
                            f"[UNIT RESOLUTION] [OK] Found {current_id} as organization in DB"
                        )
                        return current_id, resolution_path, units_to_import

                    except Organization.DoesNotExist:
                        path_step["checked_db_org"] = True
                        path_step["found_in_db_as_org"] = False
                        logger.debug(
                            f"[UNIT RESOLUTION] {current_id} not found as organization in DB, trying API"
                        )

                        # 4. Not in DB as org, try API as organization
                        try:
                            org_dto = fetcher.fetch_an_organization(current_id)
                            path_step["checked_api_org"] = True

                            if org_dto:
                                path_step["found_in_api_as_org"] = True
                                resolution_path["path"].append(path_step)
                                resolution_path["result"] = (
                                    "found_in_api_as_organization"
                                )
                                resolution_path["organization_id"] = current_id

                                # Import the organization if found
                                self._ensure_organization_exists(current_id, org_dto)

                                logger.info(
                                    f"[UNIT RESOLUTION] [OK] Found {current_id} as organization in API"
                                )
                                return current_id, resolution_path, units_to_import
                            else:
                                path_step["found_in_api_as_org"] = False

                        except Exception as org_api_error:
                            path_step["checked_api_org"] = True
                            path_step["api_org_error"] = str(org_api_error)
                            logger.warning(
                                f"Error fetching {current_id} as organization from API: {org_api_error}"
                            )

                    # 5. Not found anywhere - probably bad data
                    resolution_path["path"].append(path_step)
                    resolution_path["result"] = "not_found_anywhere"
                    logger.warning(
                        f"[UNIT RESOLUTION] [FAIL] ID {current_id} not found as unit or organization in DB or API - probably bad data"
                    )
                    return None, resolution_path, units_to_import

            except Exception as e:
                path_step["unexpected_error"] = str(e)
                resolution_path["path"].append(path_step)
                resolution_path["result"] = "unexpected_error"
                resolution_path["error"] = str(e)
                logger.error(
                    f"[UNIT RESOLUTION] [FAIL] Unexpected error resolving ID {current_id}: {e}",
                    exc_info=True,
                )
                return None, resolution_path, units_to_import

        resolution_path["result"] = "max_depth_reached"
        logger.warning(
            f"[UNIT RESOLUTION] [FAIL] Reached max depth ({max_depth}) while resolving organization for unit {unit_id}"
        )
        return None, resolution_path, units_to_import

    def _ensure_organization_exists(self, org_id, org_dto):
        """
        Ensures the organization exists in the database, importing it if necessary.
        """
        # Check cache first
        if org_id in self.org_cache:
            org_exists = self.org_cache[org_id]
        else:
            org_exists = Organization.objects.filter(uid=org_id).exists()
            self.org_cache[org_id] = org_exists

        if not org_exists:
            logger.info(f"Organization {org_id} not found in DB. Importing it...")

            try:
                from core.importers.organization import OrganizationImporter

                org_importer = OrganizationImporter()
                created_count = org_importer.import_many([org_dto])

                if created_count > 0:
                    self.org_cache[org_id] = True
                    logger.info(f"Successfully imported organization {org_id}")
                else:
                    # Organization might already exist and was updated
                    self.org_cache[org_id] = True
                    logger.info(f"Organization {org_id} already exists or was updated")

            except Exception as import_error:
                logger.error(f"Failed to import organization {org_id}: {import_error}")
                # Don't raise - we'll use a placeholder if needed

    def _resolve_signer_organization(
        self, signer_id, fetcher, max_depth=5, visited=None
    ):
        """
        Resolves organization for a signer by checking units they belong to.
        Also returns the resolution path for auditing.

        Args:
            signer_id: The signer ID to resolve
            fetcher: DiavgeiaFetcher instance to use for API calls
            max_depth: Maximum recursion depth (for unit traversal)
            visited: Set of already visited unit IDs to prevent cycles

        Returns:
            Tuple of (org_id, resolution_path)
        """
        # Initialize resolution path tracking
        resolution_path = {
            "signer_id": signer_id,
            "path": [],
            "result": "unknown",
            "timestamp": timezone.now().isoformat(),
        }

        try:
            logger.info(
                f"[SIGNER RESOLUTION] Starting resolution for signer {signer_id}"
            )

            # 1. Fetch the signer
            logger.debug(f"[SIGNER RESOLUTION] Fetching signer {signer_id} from API")
            signer_dto = fetcher.fetch_a_signer(signer_id)

            if not signer_dto:
                logger.warning(
                    f"[SIGNER RESOLUTION] Signer {signer_id} not found in API"
                )
                resolution_path["result"] = "signer_not_found"
                return None, resolution_path

            logger.debug(f"[SIGNER RESOLUTION] Successfully fetched signer {signer_id}")

            # 2. Check if the signer has units
            if not hasattr(signer_dto, "units") or not signer_dto.units:
                logger.warning(
                    f"[SIGNER RESOLUTION] Signer {signer_id} has no units attribute or empty units list"
                )
                resolution_path["result"] = "no_units"
                return None, resolution_path

            logger.info(
                f"[SIGNER RESOLUTION] Signer {signer_id} has {len(signer_dto.units)} units"
            )

            # 3. For each unit associated with the signer, try to find its organization
            for idx, signer_unit in enumerate(signer_dto.units):
                logger.debug(
                    f"[SIGNER RESOLUTION] Processing unit {idx+1}/{len(signer_dto.units)} for signer {signer_id}"
                )

                if not hasattr(signer_unit, "uid") or not signer_unit.uid:
                    logger.debug(
                        f"[SIGNER RESOLUTION] Skipping unit {idx+1} - no uid attribute"
                    )
                    continue

                unit_id = signer_unit.uid
                logger.debug(
                    f"[SIGNER RESOLUTION] Trying unit {unit_id} for signer {signer_id}"
                )

                resolution_path["path"].append(
                    {
                        "tried_unit_id": unit_id,
                        "position_id": getattr(signer_unit, "positionId", None),
                        "position_label": getattr(signer_unit, "positionLabel", None),
                    }
                )

                # Try to find this unit's organization (either directly or through parent chain)
                logger.debug(f"[SIGNER RESOLUTION] Fetching unit {unit_id} from API")
                unit_dto = fetcher.fetch_a_unit(unit_id)

                if not unit_dto:
                    logger.warning(
                        f"[SIGNER RESOLUTION] Unit {unit_id} not found in API"
                    )
                    resolution_path["path"][-1]["unit_found"] = False
                    continue

                resolution_path["path"][-1]["unit_found"] = True
                logger.debug(f"[SIGNER RESOLUTION] Successfully fetched unit {unit_id}")

                # If this unit has an organization, use it
                if hasattr(unit_dto, "organizationId") and unit_dto.organizationId:
                    org_id = unit_dto.organizationId
                    logger.info(
                        f"[SIGNER RESOLUTION] [OK] Found organization {org_id} directly on unit {unit_id}"
                    )
                    resolution_path["path"][-1]["has_org_id"] = True
                    resolution_path["result"] = "found_through_unit"
                    resolution_path["resolved_through_unit"] = unit_id
                    resolution_path["organization_id"] = org_id
                    return org_id, resolution_path

                logger.debug(
                    f"[SIGNER RESOLUTION] Unit {unit_id} has no organizationId, trying parent chain"
                )
                resolution_path["path"][-1]["has_org_id"] = False

                # If the unit doesn't have an org, try to resolve through its parent chain
                if visited is None:
                    visited = set()

                # Don't include current signer ID in visited units - it's not a unit
                logger.debug(
                    f"[SIGNER RESOLUTION] Resolving unit {unit_id} through parent chain"
                )
                org_id, unit_resolution_path = (
                    self._resolve_unit_organization_through_parents(
                        unit_id, fetcher, max_depth, visited
                    )
                )

                if org_id:
                    logger.info(
                        f"[SIGNER RESOLUTION] [OK] Found organization {org_id} through parent chain of unit {unit_id}"
                    )
                    resolution_path["path"][-1]["resolved_through_parent_chain"] = True
                    resolution_path["path"][-1][
                        "unit_resolution_path"
                    ] = unit_resolution_path
                    resolution_path["result"] = "found_through_unit_parent_chain"
                    resolution_path["organization_id"] = org_id
                    resolution_path["resolved_through_unit"] = unit_id
                    return org_id, resolution_path

                logger.debug(
                    f"[SIGNER RESOLUTION] Could not resolve organization through parent chain of unit {unit_id}"
                )
                resolution_path["path"][-1]["resolved_through_parent_chain"] = False

            # 4. If no organization found through any unit, return None
            logger.warning(
                f"[SIGNER RESOLUTION] [FAIL] No organization found for signer {signer_id} "
                f"after checking {len(signer_dto.units)} units"
            )
            resolution_path["result"] = "no_org_found_through_units"
            return None, resolution_path

        except Exception as e:
            logger.error(
                f"[SIGNER RESOLUTION] [FAIL] Error resolving organization for signer {signer_id}: {e}",
                exc_info=True,
            )
            resolution_path["result"] = "error"
            resolution_path["error"] = str(e)
            return None, resolution_path

    def _ensure_default_organization(self, entity_type, entity_id):
        """
        Ensures that a default organization exists for entities without resolvable organizations.
        Returns the default organization UID.
        """
        default_org_uid = f"DEFAULT_{entity_type.upper()}_ORG"

        # Check if default org exists in cache first
        if default_org_uid in self.org_cache:
            default_org_exists = self.org_cache[default_org_uid]
        else:
            default_org_exists = Organization.objects.filter(
                uid=default_org_uid
            ).exists()
            self.org_cache[default_org_uid] = default_org_exists

        if not default_org_exists:
            try:
                # Create the default organization
                Organization.objects.create(
                    uid=default_org_uid,
                    label=f"Default Organization for Orphaned {entity_type.title()}s",
                    latin_name=f"default_{entity_type}_org",
                    status="SYSTEM",
                    category="SYSTEM",
                )
                self.org_cache[default_org_uid] = True
                logger.info(f"Created default organization {default_org_uid}")
            except Exception as org_err:
                logger.error(
                    f"Failed to create default organization for {entity_type}: {org_err}"
                )

        return default_org_uid

    def extract_and_save_amounts(self, decision: Decision):
        amount_patterns = self.find_amount_patterns_in_data(
            decision.extra_field_values_json, decision.ada
        )

        for pattern in amount_patterns:
            amount_info = pattern["amount_info"]

            # Skip container-level patterns (those without a dot in parent_path)
            if "." not in pattern["parent_path"]:
                logger.debug(
                    f"Skipping container-level pattern {pattern['parent_path']} "
                    f"for decision {decision.ada}"
                )
                continue

            for i, amount in enumerate(amount_info["amounts"]):
                # Create the amount field
                amount_field, created = DecisionAmountField.objects.get_or_create(
                    decision=decision,
                    parent_key_path=pattern["parent_path"],
                    source_field_name=amount_info["fields_found"][i],
                    defaults={
                        "amount": (
                            decimal.Decimal(str(amount)) if amount is not None else None
                        ),
                        "currency": (
                            amount_info["currencies"][i]
                            if i < len(amount_info["currencies"])
                            else "EUR"
                        ),
                        "structure_type": amount_info["structure_types"][i],
                        "raw_context": pattern["raw_data"],
                    },
                )

                # NEW: Link to entity relationship using the same logic as backfill
                # Always try to link, even if related_afms is empty (field-level amounts)
                if not amount_field.associated_relationship:
                    # Get all relationships for this decision
                    relationships = DecisionEntityRelationship.objects.filter(
                        decision=decision
                    )

                    matching_rel = None
                    for rel in relationships:
                        # Extract container path from relationship (e.g., "sponsor[0].sponsorAFMName" → "sponsor[0]")
                        rel_container = (
                            rel.parent_key_path.rsplit(".", 1)[0]
                            if "." in rel.parent_key_path
                            else rel.parent_key_path
                        )

                        # Extract container path from amount (e.g., "sponsor[0].expenseAmount" → "sponsor[0]" or use as-is for "sponsor[0]")
                        amount_container = (
                            pattern["parent_path"].rsplit(".", 1)[0]
                            if "." in pattern["parent_path"]
                            else pattern["parent_path"]
                        )  # Fixed: use 'parent_path'

                        # Match if they're in the same container AND the amount is a specific field (not a container)
                        if (
                            rel_container == amount_container
                            and "." in pattern["parent_path"]
                        ):
                            matching_rel = rel
                            break

                    # Set the FK if we found a matching relationship
                    if matching_rel:
                        amount_field.associated_relationship = matching_rel
                        amount_field.save(update_fields=["associated_relationship"])
                        logger.debug(
                            f"Linked amount {amount_field.id} ({amount_field.amount}) to relationship {matching_rel.id} (entity {matching_rel.entity.afm})"
                        )

                # Keep the old logic for backward compatibility (can remove later)
                if amount_info["related_afms"]:
                    rel = DecisionEntityRelationship.objects.filter(
                        decision=decision, parent_key_path=pattern["parent_path"]
                    ).first()
                    if rel:
                        rel.amount = (
                            decimal.Decimal(str(amount)) if amount is not None else None
                        )
                        rel.currency = amount_info["currencies"][i] or "EUR"
                        rel.amount_source_field = amount_info["fields_found"][i]
                        rel.amount_structure_type = amount_info["structure_types"][i]
                        rel.save()

    def find_amount_patterns_in_data(
        self, data: Any, decision_ada: str, parent_path: str = ""
    ) -> List[Dict]:
        patterns = []
        if isinstance(data, dict):
            amount_info = self.detect_amounts_in_dict(data, parent_path)
            if amount_info:
                patterns.append(
                    {
                        "parent_path": parent_path or "root",
                        "amount_info": amount_info,
                        "raw_data": data,
                    }
                )
            for key, value in data.items():
                new_path = f"{parent_path}.{key}" if parent_path else key
                patterns.extend(
                    self.find_amount_patterns_in_data(value, decision_ada, new_path)
                )
        elif isinstance(data, list):
            for i, item in enumerate(data):
                new_path = f"{parent_path}[{i}]" if parent_path else f"[{i}]"
                patterns.extend(
                    self.find_amount_patterns_in_data(item, decision_ada, new_path)
                )
        return patterns

    def detect_amounts_in_dict(
        self, data: Dict[str, Any], parent_path: str
    ) -> Dict[str, Any]:
        amount_info = {
            "fields_found": [],
            "structure_types": [],
            "amounts": [],
            "currencies": [],
            "related_afms": [],
        }
        amount_keywords = [
            "amount",
            "expenseAmount",
            "awardAmount",
            "amountWithVAT",
            "value",
            "cost",
            "price",
            "sum",
            "total",
            "ποσο",
            "αξια",
        ]
        for key, value in data.items():
            key_lower = key.lower()
            if any(amt_term in key_lower for amt_term in amount_keywords):
                amount_info["fields_found"].append(key)
                if isinstance(value, dict):
                    amount_info["structure_types"].append("nested_object")
                    amt = value.get("amount")
                    if amt is not None:
                        try:
                            amount_info["amounts"].append(float(amt))
                        except (ValueError, TypeError):
                            pass
                    curr = value.get("currency")
                    if curr:
                        amount_info["currencies"].append(curr)
                elif isinstance(value, (int, float)):
                    amount_info["structure_types"].append("plain_numeric")
                    amount_info["amounts"].append(float(value))
                else:
                    amount_info["structure_types"].append("other")
                    try:
                        if value is not None:
                            numeric_value = float(str(value).replace(",", ""))
                            amount_info["amounts"].append(numeric_value)
                    except (ValueError, TypeError):
                        pass
        for key, value in data.items():
            if "afm" in key.lower() and isinstance(value, str):
                amount_info["related_afms"].append(value)
            elif isinstance(value, dict) and "afm" in value:
                amount_info["related_afms"].append(value["afm"])
        return amount_info if amount_info["fields_found"] else {}
