import time
from datetime import date
from typing import Optional, Union

from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.fetchers.nominatim_fetcher import NominatimFetcher
from core.importers.dictionary import DictionaryItemImporter, DictionaryListImporter
from core.importers.geo_data import OrganizationGeoDataImporter
from core.importers.organization import OrganizationImporter
from core.importers.positions import PositionImporter
from core.importers.signer import SignerImporter
from core.importers.types import ActTypeImporter, ExtraFieldImporter
from core.importers.unit import UnitDomainImporter, UnitImporter
from core.models.dictionaries import Dictionary, DictionaryItem
from core.models.organizations import (
    Organization,
    OrganizationGeoData,
    Position,
    Signer,
    SignerUnit,
    Unit,
)
from core.models.types import ActType
from django.db import transaction
from django.db.models import QuerySet
from loguru import logger


class SeedService:
    unforced_response = {
        "status": "success",
        "seeded": False,
        "count": 0,
        "message": "Already populated",
    }
    min_time_per_nomatim_request = 1.2

    def __init__(
        self,
        number_of_ents_in_lite_mode: Union[int, None] = None,
    ):
        self.fetcher = DiavgeiaFetcher()
        self.org_importer = OrganizationImporter()
        self.dict_importer = DictionaryListImporter()
        self.dict_item_importer = DictionaryItemImporter()
        # New importers
        self.unit_importer = UnitImporter()
        self.unit_domain_importer = UnitDomainImporter()
        self.position_importer = PositionImporter()
        self.signer_importer = SignerImporter()
        self.nominatim_fetcher = NominatimFetcher()
        self.geo_data_importer = OrganizationGeoDataImporter()

        self.number_of_ents_in_lite_mode = number_of_ents_in_lite_mode

    def create_successful_response(self, created: int) -> dict:
        return {
            "status": "success",
            "seeded": True,
            "count": created,
            "message": f"Processed {created} entities",
        }

    def seed_organizations(self, *, force: bool = False, batch_size: int = 50) -> dict:
        """Seed organizations data and their details."""
        if not force and Organization.objects.exists():
            logger.info("Organizations already exist. Skipping main import.")
            return self.unforced_response

        logger.info("Fetching organizations...")
        dtos = self.fetcher.fetch_organizations()
        logger.info(f"Fetched {len(dtos)} organizations.")

        # Apply lite mode limit if specified
        dtos_to_process = (
            dtos[: self.number_of_ents_in_lite_mode]
            if self.number_of_ents_in_lite_mode
            else dtos
        )

        # Process in batches
        total_created = 0
        batch_count = len(dtos_to_process) // batch_size + (
            1 if len(dtos_to_process) % batch_size else 0
        )

        for i in range(batch_count):
            batch_start = i * batch_size
            batch_end = (i + 1) * batch_size
            batch = dtos_to_process[batch_start:batch_end]

            try:
                # Verify connection before each batch
                from django.db import connection

                if not connection.is_usable():
                    connection.close()
                    connection.connect()

                with transaction.atomic():
                    created = self.org_importer.import_many(batch)
                    total_created += created

                    logger.info(
                        f"Imported batch {i+1}/{batch_count} ({len(batch)} organizations). "
                        f"Total: {total_created}"
                    )

            except Exception as e:
                logger.error(
                    f"Failed batch {i+1}/{batch_count} for organizations: {str(e)}"
                )
                raise  # Re-raise to abort and allow retry

        logger.info(f"Imported/Updated {total_created} organizations.")

        # Rest of the method remains the same for seeding details...
        organizations_to_detail: QuerySet[Organization]
        if force:
            organizations_to_detail = Organization.objects.all()
            logger.info(
                f"Force mode: Seeding details for all {organizations_to_detail.count()} organizations."
            )
        else:
            org_uids = [dto.uid for dto in dtos_to_process]
            organizations_to_detail = Organization.objects.filter(uid__in=org_uids)
            logger.info(
                f"Seeding details for {organizations_to_detail.count()} fetched organizations."
            )

        processed_details_count = 0
        for org in organizations_to_detail:
            logger.debug(f"Seeding details for organization {org.uid} ({org.label})")
            try:
                self.seed_organization_details(org.uid)
                processed_details_count += 1
            except Exception as e:
                logger.error(f"Failed to seed details for organization {org.uid}: {e}")

        response = self.create_successful_response(total_created)
        response["message"] = (
            f"Processed {total_created} organizations. Seeded details for {processed_details_count} organizations."
        )
        return response

    def seed_organization_details(self, organization_uid: str) -> dict:
        """Seed related data (units, positions, signers) for a specific organization."""
        logger.debug(
            f"Starting detail seeding for organization UID: {organization_uid}"
        )
        try:
            org = Organization.objects.get(uid=organization_uid)
        except Organization.DoesNotExist:
            logger.error(
                f"Organization {organization_uid} not found for detail seeding."
            )
            return {
                "error": "Organization not found",
                "units": 0,
                "positions": 0,
                "signers": 0,
            }

        results = {"units": 0, "positions": 0, "signers": 0, "unit_domains": 0}

        try:
            logger.debug(f"Fetching units for {organization_uid}...")
            unit_dtos = self.fetcher.fetch_organization_units(organization_uid)
            logger.debug(f"Fetched {len(unit_dtos)} units for {organization_uid}.")
            units_created_or_updated = self.unit_importer.import_many(
                unit_dtos, defaults={"organization": org, "parent": None}
            )
            results["units"] = units_created_or_updated
            logger.debug(
                f"Imported/Updated {units_created_or_updated} units (pass 1) for {organization_uid}."
            )

            parents_set = 0
            for unit_dto in unit_dtos:
                if (
                    hasattr(unit_dto, "parentId")
                    and unit_dto.parentId
                    and unit_dto.parentId != organization_uid
                ):
                    try:
                        unit = Unit.objects.get(uid=unit_dto.uid, organization=org)
                        parent = Unit.objects.get(
                            uid=unit_dto.parentId, organization=org
                        )
                        if unit.parent != parent:
                            unit.parent = parent
                            unit.save(update_fields=["parent"])
                            parents_set += 1
                    except Unit.DoesNotExist:
                        logger.warning(
                            f"Unit {unit_dto.uid} or Parent {unit_dto.parentId} not found for org {organization_uid}. Skipping parent assignment."
                        )
                    except Exception as e:
                        logger.error(
                            f"Error setting parent for unit {unit_dto.uid}: {e}"
                        )
            logger.debug(
                f"Set parents for {parents_set} units (pass 2) for {organization_uid}."
            )

            domains_created_total = 0
            for unit_dto in unit_dtos:
                if hasattr(unit_dto, "unitDomains") and unit_dto.unitDomains:
                    try:
                        unit = Unit.objects.get(uid=unit_dto.uid, organization=org)
                        domain_created = self.unit_domain_importer.import_many(
                            unit_dto.unitDomains, defaults={"unit": unit}
                        )
                        domains_created_total += domain_created
                    except Unit.DoesNotExist:
                        logger.warning(
                            f"Unit {unit_dto.uid} not found for domain import (org {organization_uid})."
                        )
                    except Exception as e:
                        logger.error(
                            f"Error importing domains for unit {unit_dto.uid}: {e}"
                        )
            results["unit_domains"] = domains_created_total
            logger.debug(
                f"Imported/Updated {domains_created_total} unit domains for {organization_uid}."
            )

            logger.debug(f"Fetching positions for {organization_uid}...")
            position_dtos = self.fetcher.fetch_organization_positions(organization_uid)
            logger.debug(
                f"Fetched {len(position_dtos)} positions for {organization_uid}."
            )
            positions_created_or_updated = self.position_importer.import_many(
                position_dtos
            )
            results["positions"] = positions_created_or_updated
            logger.debug(
                f"Imported/Updated {positions_created_or_updated} positions for {organization_uid}."
            )

            logger.debug(f"Fetching signers for {organization_uid}...")
            signer_dtos = self.fetcher.fetch_organization_signers(organization_uid)
            logger.debug(f"Fetched {len(signer_dtos)} signers for {organization_uid}.")
            signers_created_or_updated = self.signer_importer.import_many(
                signer_dtos, defaults={"organization": org}
            )
            results["signers"] = signers_created_or_updated
            logger.debug(
                f"Imported/Updated {signers_created_or_updated} signers for {organization_uid}."
            )

            signer_units_processed = 0
            for signer_dto in signer_dtos:
                try:
                    signer = Signer.objects.get(uid=signer_dto.uid, organization=org)
                    if hasattr(signer_dto, "units") and signer_dto.units:
                        for unit_info in signer_dto.units:
                            try:
                                unit_exists = Unit.objects.filter(
                                    uid=unit_info.uid, organization=org
                                ).exists()
                                position_exists = Position.objects.filter(
                                    uid=unit_info.positionId
                                ).exists()

                                if unit_exists:
                                    if not position_exists and hasattr(
                                        unit_info, "positionLabel"
                                    ):
                                        Position.objects.create(
                                            uid=unit_info.positionId,
                                            label=unit_info.positionLabel,
                                        )
                                        position_exists = True
                                    if position_exists:
                                        _, created = (
                                            SignerUnit.objects.update_or_create(
                                                signer=signer,
                                                unit_id=unit_info.uid,
                                                position_id=unit_info.positionId,
                                            )
                                        )
                                        signer_units_processed += 1
                                else:
                                    logger.warning(
                                        f"Skipping SignerUnit link: Unit {unit_info.uid} or Position {unit_info.positionId} not found for org {organization_uid}."
                                    )
                            except Exception as e:
                                logger.error(
                                    f"Error linking signer {signer.uid} to unit {unit_info.uid}/pos {unit_info.positionId}: {e}"
                                )
                except Signer.DoesNotExist:
                    logger.warning(
                        f"Signer {signer_dto.uid} not found for unit linking (org {organization_uid})."
                    )
                except Exception as e:
                    logger.error(
                        f"Error processing units for signer {signer_dto.uid}: {e}"
                    )
            logger.debug(
                f"Processed {signer_units_processed} signer-unit links for {organization_uid}."
            )

        except Exception as e:
            logger.error(
                f"General error during detail seeding for organization {organization_uid}: {e}"
            )
            return {"error": str(e), **results}

        logger.debug(
            f"Finished detail seeding for organization UID: {organization_uid}. Results: {results}"
        )
        return results

    def force_seed_all_details(self) -> dict:
        """
        Forces seeding of details (units, positions, signers) for ALL existing organizations.
        This bypasses the check in seed_organizations and iterates through DB entries.
        """
        organizations = Organization.objects.all()
        org_count = organizations.count()
        if org_count == 0:
            return {
                "status": "skipped",
                "seeded": False,
                "count": 0,
                "message": "No organizations found in the database to seed details for.",
            }

        logger.info(f"Starting forced detail seeding for {org_count} organizations.")
        processed_org_count = 0
        failed_org_count = 0

        for org in organizations:
            logger.debug(f"Forcing details for organization {org.uid} ({org.label})")
            try:
                self.seed_organization_details(org.uid)
                processed_org_count += 1
            except Exception as e:
                logger.error(f"Failed to force details for organization {org.uid}: {e}")
                failed_org_count += 1

        success = failed_org_count == 0
        message = f"Forced detail seeding completed. Processed: {processed_org_count}, Failed: {failed_org_count} organizations."
        logger.info(message)

        return {
            "status": "success" if success else "partial_success",
            "seeded": True,
            "count": processed_org_count,
            "message": message,
        }

    def seed_dictionaries(self, *, force: bool = False) -> dict:
        if not force and Dictionary.objects.exists():
            return self.unforced_response

        dtos = self.fetcher.fetch_dictionaries()
        created = self.dict_importer.import_many(dtos)

        return self.create_successful_response(created)

    def seed_dictionary_items(
        self, *, force: bool = False, batch_size: int = 100
    ) -> dict:
        if not force and DictionaryItem.objects.exists():
            return self.unforced_response

        total_created = 0
        dictionaries = Dictionary.objects.all()

        # Track progress per dictionary
        progress = {}

        for dictionary in dictionaries:
            if (
                not force
                and DictionaryItem.objects.filter(dictionary=dictionary).exists()
            ):
                logger.info(
                    f"Dictionary items for {dictionary.uid} already exist. Skipping."
                )
                continue

            logger.info(
                f"Fetching items for dictionary {dictionary.uid}: {dictionary.label}"
            )
            dtos = self.fetcher.fetch_dictionary_items(uid=dictionary.uid)

            dtos_to_process = (
                dtos[: self.number_of_ents_in_lite_mode]
                if self.number_of_ents_in_lite_mode
                else dtos
            )

            # Process orphans in batches with checkpoint
            orphan_dtos = [dto for dto in dtos_to_process if dto.parent is None]
            batch_count = len(orphan_dtos) // batch_size + (
                1 if len(orphan_dtos) % batch_size else 0
            )

            # Check if we have existing progress for this dictionary
            last_processed = progress.get(dictionary.uid, {}).get("last_batch", 0)
            if last_processed > 0:
                logger.info(f"Resuming from batch {last_processed + 1}/{batch_count}")

            for i in range(last_processed, batch_count):
                batch_start = i * batch_size
                batch_end = (i + 1) * batch_size
                batch = orphan_dtos[batch_start:batch_end]

                try:
                    # Verify connection before each batch
                    from django.db import connection

                    if not connection.is_usable():
                        connection.close()
                        connection.connect()

                    with transaction.atomic():
                        created = self.dict_item_importer.import_many(
                            batch, defaults={"dictionary": dictionary}
                        )
                        total_created += created

                        # Update progress after successful batch
                        progress[dictionary.uid] = {
                            "last_batch": i + 1,
                            "processed": batch_end,
                        }

                        logger.info(
                            f"Imported batch {i+1}/{batch_count} ({len(batch)} items) "
                            f"for dictionary {dictionary.uid}. Total: {total_created}"
                        )

                except Exception as e:
                    logger.error(
                        f"Failed batch {i+1}/{batch_count} for {dictionary.uid}: {str(e)}"
                    )
                    # Save progress before exiting
                    progress[dictionary.uid] = {
                        "last_batch": i,
                        "processed": batch_start,
                    }
                    raise  # Re-raise to abort and allow retry from last batch

            # Process non-orphans with parent references
            non_orphan_dtos = [dto for dto in dtos_to_process if dto.parent is not None]
            item_cache = {
                item.uid: item
                for item in DictionaryItem.objects.filter(dictionary=dictionary)
            }

            for dto in non_orphan_dtos:
                try:
                    with transaction.atomic():
                        parent_item = item_cache.get(dto.parent)
                        if parent_item is None:
                            parent_item = DictionaryItem.objects.get(uid=dto.parent)
                            item_cache[dto.parent] = parent_item

                        obj, created = (
                            self.dict_item_importer.model.objects.update_or_create(
                                uid=dto.uid,
                                defaults={
                                    **self.dict_item_importer._to_defaults(dto),
                                    "dictionary": dictionary,
                                    "parent": parent_item,
                                },
                            )
                        )
                        if created:
                            total_created += 1
                            item_cache[dto.uid] = obj

                except DictionaryItem.DoesNotExist:
                    logger.warning(
                        f"Parent item {dto.parent} not found, skipping {dto.uid}"
                    )
                except Exception as e:
                    logger.error(f"Error importing item {dto.uid}: {str(e)}")
                    continue

        return self.create_successful_response(total_created)

    def seed_organization_geodata(
        self, *, force: bool = False, max_orgs: int = None
    ) -> dict:
        """
        Seed geographical data for organizations using Nominatim.

        Args:
            force: If True, update existing geodata records
            max_orgs: Optional limit on number of organizations to process
        """
        if not force and OrganizationGeoData.objects.exists():
            logger.info("OrganizationGeoData already exists. Skipping fetch.")
            return self.unforced_response

        # Get all organizations
        all_organizations = Organization.objects.all()
        org_count = all_organizations.count()

        if org_count == 0:
            logger.warning("No organizations found in DB to fetch geodata for.")
            return {
                "status": "skipped",
                "seeded": False,
                "count": 0,
                "message": "No organizations found.",
            }

        # Apply max_orgs limit if specified
        if max_orgs is not None and max_orgs > 0:
            organizations = all_organizations[:max_orgs]
            logger.info(
                f"Starting geodata fetch for {len(organizations)} of {org_count} organizations (limit: {max_orgs})."
            )
        else:
            organizations = all_organizations
            logger.info(f"Starting geodata fetch for all {org_count} organizations.")

        created_count = 0
        updated_count = 0
        failed_count = 0
        skipped_count = 0

        # Track when we last made a request to implement rate limiting
        last_request_time = 0

        for org in organizations:
            # Check if we need to skip based on 'force' flag
            if (
                not force
                and OrganizationGeoData.objects.filter(organization=org).exists()
            ):
                skipped_count += 1
                continue

            logger.debug(f"Fetching geodata for org: {org.uid} - {org.label}")

            # Implement rate limiting - ensure 1 second between API calls
            current_time = time.time()
            elapsed = current_time - last_request_time

            if last_request_time > 0 and elapsed < self.min_time_per_nomatim_request:
                sleep_time = self.min_time_per_nomatim_request - elapsed
                logger.debug(
                    f"Rate limiting: waiting {sleep_time:.2f}s before next request"
                )
                time.sleep(sleep_time)

            # Record time immediately before making the API call
            last_request_time = time.time()
            results = self.nominatim_fetcher.fetch_geo_data(org.label)

            if results:
                # Strategy: Use the first result for now
                best_result = results
                try:
                    _, created = self.geo_data_importer.import_one(best_result, org)
                    if created:
                        created_count += 1
                    else:
                        updated_count += 1
                except Exception as e:
                    logger.error(f"Failed to import geodata for org {org.uid}: {e}")
                    failed_count += 1
            else:
                logger.warning(f"No geodata found for org {org.uid} - {org.label}")
                failed_count += 1  # Count as failed if no results returned

        total_processed = created_count + updated_count
        limit_msg = f" (limited to {max_orgs})" if max_orgs else ""
        message = (
            f"Geodata seeding complete{limit_msg}. "
            f"Created: {created_count}, Updated: {updated_count}, "
            f"Failed/No Results: {failed_count}, Skipped: {skipped_count}."
        )
        logger.info(message)

        return {
            "status": "success" if failed_count == 0 else "partial_success",
            "seeded": True,
            "count": total_processed,
            "message": message,
        }

    def seed_types(self, *, force: bool = False) -> dict:
        """
        Seed act types and their extra fields from Diavgeia API.
        Also updates any existing decisions that have null decision_type_id.

        Args:
            force: If True, update existing types
        """
        if not force and ActType.objects.exists():
            logger.info("Act types already exist. Skipping import.")
            return self.unforced_response

        logger.info("Fetching all act types...")
        type_summaries = self.fetcher.fetch_all_types()
        logger.info(f"Fetched {len(type_summaries)} act type summaries")

        # First pass: Create or update basic type information
        act_type_importer = ActTypeImporter()
        created_types = act_type_importer.import_many(type_summaries)
        logger.info(f"Imported/Updated {created_types} act types")

        # Second pass: Fetch details and create/update extra fields
        created_fields = 0
        updated_fields = 0
        failed_fields = 0
        extra_field_importer = ExtraFieldImporter()

        for type_summary in type_summaries:
            try:
                type_details = self.fetcher.fetch_type_details(type_summary.uid)
                if not type_details or not hasattr(type_details, "extraFields"):
                    logger.warning(f"No extra fields found for type {type_summary.uid}")
                    continue

                # Import the extra fields
                result = extra_field_importer.import_for_type(type_details)
                created_fields += result.get("created", 0)
                updated_fields += result.get("updated", 0)
            except Exception as e:
                logger.error(
                    f"Failed to process extra fields for type {type_summary.uid}: {e}"
                )
                failed_fields += 1

        # Check for decisions with null decision_type_id and attempt to update them
        from core.models import Decision

        null_decisions = Decision.objects.filter(decision_type_id__isnull=True)
        null_count = null_decisions.count()

        if null_count > 0:
            logger.info(
                f"Found {null_count} decisions with null decision_type_id. Attempting to update..."
            )

            updated_decisions = 0
            still_null = 0

            for decision in null_decisions:
                # If the decision has decisionTypeId in extraFieldValues, try to use that
                type_id = None

                # First check if we have the raw field stored in the model
                if decision.extra_field_values_json and isinstance(
                    decision.extra_field_values_json, dict
                ):
                    # TODO: THis is not existing there, I'm afraid we'll have to re-fetch each and every decision to find the type
                    type_id = decision.extra_field_values_json.get("decisionTypeId")

                # If we don't have it in the raw field, try other sources
                if not type_id:
                    # We may need to fetch the decision from the API if we don't have the data locally
                    try:
                        # Try to find the act type in the database
                        if type_id and ActType.objects.filter(uid=type_id).exists():
                            decision.decision_type_id = type_id
                            decision.save(update_fields=["decision_type_id"])
                            updated_decisions += 1
                        else:
                            still_null += 1
                    except Exception as e:
                        logger.error(f"Failed to update decision {decision.ada}: {e}")
                        still_null += 1

            logger.info(
                f"Updated {updated_decisions} decisions with proper decision types. {still_null} remain null."
            )

        total_processed = created_types + created_fields + updated_fields
        message = (
            f"Act type seeding complete. "
            f"Types Created/Updated: {created_types}, "
            f"Fields Created: {created_fields}, Fields Updated: {updated_fields}, "
            f"Failed: {failed_fields}. "
            f"Updated {updated_decisions if 'updated_decisions' in locals() else 0} decisions with null types."
        )
        logger.info(message)

        return {
            "status": "success" if failed_fields == 0 else "partial_success",
            "seeded": True,
            "count": total_processed,
            "message": message,
        }

    def seed_all(
        self,
        *,
        force: bool = False,
        include_decisions: bool = False,
        decision_start_date: Optional[date] = None,
        decision_end_date: Optional[date] = None,
        decision_limit: Optional[int] = 1000,
    ) -> dict:
        """
        Seed all data types in correct dependency order.

        Args:
            force: If True, update existing records
            include_decisions: Whether to also fetch and import decisions
            decision_start_date: Start date for decisions (default: 30 days ago)
            decision_end_date: End date for decisions (default: today)
            decision_limit: Maximum number of decisions to import (default: 1000)

        Returns:
            Dictionary with results for each data type
        """
        results = {}

        # 1. Load types first - critical for decisions
        logger.info("STEP 1: Seeding act types and extra fields...")
        types_result = self.seed_types(force=force)
        results["types"] = types_result

        # 2. Load dictionaries next (often referenced by other entities)
        logger.info("STEP 2: Seeding dictionaries...")
        dictionary_result = self.seed_dictionaries(force=force)
        results["dictionaries"] = dictionary_result

        dictionary_items_result = self.seed_dictionary_items(force=force)
        results["dictionary_items"] = dictionary_items_result

        # 3. Load organizations, which are top-level entities
        logger.info("STEP 3: Seeding organizations...")
        org_result = self.seed_organizations(force=force)
        results["organizations"] = org_result

        # 4. Load organization geodata for location features
        logger.info("STEP 4: Seeding organization geodata...")
        geodata_result = self.seed_organization_geodata(force=force)
        results["organization_geodata"] = geodata_result

        # 5. If decisions are requested, import a sample set
        if include_decisions:
            logger.info("STEP 5: Seeding sample decisions...")
            decisions_result = self._seed_sample_decisions(
                force=force,
                start_date=decision_start_date,
                end_date=decision_end_date,
                limit=decision_limit,
            )
            results["decisions"] = decisions_result

        # Calculate overall status
        success = all(
            r.get("status") == "success"
            for r in results.values()
            if isinstance(r, dict) and "status" in r
        )

        return {
            "status": "success" if success else "partial_success",
            "seeded": True,
            "results": results,
            "message": f"Completed seeding with {'full' if success else 'partial'} success.",
        }

    def _seed_sample_decisions(
        self,
        *,
        force: bool = False,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 1000,
    ) -> dict:
        """
        Seed a limited number of decisions for initial setup or testing.

        Args:
            force: If True, proceed even if decisions already exist
            start_date: Start date for decisions (defaults to 30 days ago)
            end_date: End date for decisions (defaults to today)
            limit: Maximum number of decisions to fetch

        Returns:
            Dictionary with results
        """
        from datetime import datetime, timedelta

        from core.models import Decision
        from core.services.decision_ingestion_service import DecisionIngestionService
        from django.db.models import Count

        # Check if we already have decisions
        existing_count = Decision.objects.count()
        if not force and existing_count > 0:
            logger.info(
                f"Found {existing_count} existing decisions. Use --force to override."
            )
            return {
                "status": "skipped",
                "seeded": False,
                "count": 0,
                "message": f"Already have {existing_count} decisions.",
            }

        # Set default dates if not provided
        today = datetime.now().date()
        if start_date is None:
            start_date = today - timedelta(days=30)
        if end_date is None:
            end_date = today

        logger.info(
            f"Seeding sample decisions from {start_date} to {end_date} (limit: {limit})..."
        )

        # Create service components
        fetcher = DiavgeiaFetcher()
        decision_importer = DecisionImporter()
        service = DecisionIngestionService(
            diavgeia_fetcher=fetcher,
            decision_importer=decision_importer,
        )

        # Create search params to limit results
        search_params = {"size": min(500, limit)}  # Respect API max page size

        # Fetch decisions (ensure_types=True by default)
        decisions = service.fetch_decisions_for_period(
            start_date=start_date,
            end_date=end_date,
            date_increment_days=30,  # Large increment for sample data
            search_params=search_params,
            save_to_db=True,
            ensure_types=True,  # Ensure types are ready
        )

        # We might exceed our limit due to the pagination, so let's limit after the fact
        new_count = Decision.objects.count() - existing_count

        # Calculate statistics about the imported decisions
        stats = {}
        if new_count > 0:
            # Get organization distribution
            org_stats = (
                Decision.objects.values("organization_id")
                .annotate(count=Count("id"))
                .order_by("-count")[:5]
            )

            stats["top_organizations"] = [
                {"id": item["organization_id"], "count": item["count"]}
                for item in org_stats
            ]

            # Get type distribution
            type_stats = (
                Decision.objects.values("decision_type_id")
                .annotate(count=Count("id"))
                .order_by("-count")[:5]
            )

            stats["top_types"] = [
                {"id": item["decision_type_id"], "count": item["count"]}
                for item in type_stats
            ]

        # Report on the results
        message = (
            f"Imported {len(decisions)} decisions "
            f"({new_count} new in database). "
            f"Date range: {start_date} to {end_date}."
        )
        logger.info(message)

        return {
            "status": "success",
            "seeded": True,
            "count": len(decisions),
            "new_count": new_count,
            "stats": stats,
            "message": message,
        }
