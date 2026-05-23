"""
# Analyze what would be deleted (dry run)
python manage.py import_single_ada_reverse "9ΜΤΝ7ΛΛ-ΠΩΓ" --dry-run

# Safe rollback (keeps AFM entities)
python manage.py import_single_ada_reverse "9ΜΤΝ7ΛΛ-ΠΩΓ" --keep-entities

# Full rollback (removes orphaned AFM entities too)
python manage.py import_single_ada_reverse "9ΜΤΝ7ΛΛ-ΠΩΓ"

# Full rollback without confirmation prompt
python manage.py import_single_ada_reverse "9ΜΤΝ7ΛΛ-ΠΩΓ" --force
"""

from core.models.decisions import Attachment, Decision, DecisionAmountKAE
from core.models.entities import (
    AFMEntity,
    DecisionAmountField,
    DecisionEntityRelationship,
)
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Reverse (rollback) a single decision import by ADA - removes decision and all related data"

    def add_arguments(self, parser):
        parser.add_argument("ada", type=str, help="ADA to reverse/rollback")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting",
        )
        parser.add_argument(
            "--keep-entities",
            action="store_true",
            help="Keep AFM entities even if they become orphaned",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Skip confirmation prompt",
        )

    def handle(self, *args, **options):
        ada = options["ada"]
        dry_run = options["dry_run"]
        keep_entities = options["keep_entities"]
        force = options["force"]

        self.stdout.write(f"[RETRY] Analyzing decision rollback for: {ada}")

        try:
            decision = self._analyze_decision(ada)
            if not decision:
                return

            if dry_run:
                self.stdout.write("[SCAN] DRY RUN - No data will be deleted")
                return

            if not force:
                if not self._get_user_confirmation(keep_entities):
                    self.stdout.write("[ERROR] Rollback cancelled")
                    return

            self._execute_rollback(decision, keep_entities)

        except Decision.DoesNotExist:
            self.stdout.write(f"[ERROR] Decision {ada} not found in database")

    def _analyze_decision(self, ada):
        """Analyze what would be affected by the rollback."""
        try:
            decision = Decision.objects.get(ada=ada)

            self.stdout.write("=== CURRENT DATABASE STATE ===")
            self.stdout.write(f"[OK] Decision found: {decision.ada}")
            self.stdout.write(f"   ID: {decision.id}")
            self.stdout.write(f"   Subject: {decision.subject}")
            self.stdout.write(f"   Created: {decision.created_at}")
            self.stdout.write(
                f'   Organization: {getattr(decision, "organization_id", "N/A")}'
            )

            # Analyze related objects
            self.stdout.write("\n=== OBJECTS TO BE REMOVED ===")

            # 1. Decision Entity Relationships
            relationships = DecisionEntityRelationship.objects.filter(decision=decision)
            self.stdout.write(
                f"[CHART] DecisionEntityRelationship records: {relationships.count()}"
            )
            for rel in relationships:
                self.stdout.write(
                    f"   - ID: {rel.id}, Entity AFM: {rel.entity.afm}, Role: {rel.role}"
                )

            # 2. Decision Amount Fields
            amount_fields = DecisionAmountField.objects.filter(decision=decision)
            self.stdout.write(
                f"[COST] DecisionAmountField records: {amount_fields.count()}"
            )
            for amount in amount_fields:
                self.stdout.write(
                    f"   - ID: {amount.id}, Field: {amount.source_field_name}, Amount: {amount.amount}"
                )

            # 3. Attachments
            attachments = Attachment.objects.filter(decision=decision)
            self.stdout.write(f"[ATTACH] Attachment records: {attachments.count()}")
            for att in attachments:
                self.stdout.write(
                    f'   - ID: {att.id}, Filename: {getattr(att, "filename", "N/A")}'
                )

            # 4. KAE Amounts
            kae_amounts = DecisionAmountKAE.objects.filter(decision=decision)
            self.stdout.write(f"[BIZ] DecisionAmountKAE records: {kae_amounts.count()}")
            for kae in kae_amounts:
                self.stdout.write(
                    f"   - ID: {kae.id}, KAE: {kae.kae}, Amount: {kae.amount}"
                )

            # 5. AFM Entities analysis
            related_afm_entities = AFMEntity.objects.filter(
                decision_relationships__decision=decision
            ).distinct()
            self.stdout.write(
                f"[CORP] Related AFM entities: {related_afm_entities.count()}"
            )

            orphaned_entities = []
            for entity in related_afm_entities:
                other_decisions_count = (
                    DecisionEntityRelationship.objects.filter(entity=entity)
                    .exclude(decision=decision)
                    .count()
                )

                self.stdout.write(
                    f'   - AFM: {entity.afm}, Name: {entity.name[:50] if entity.name else "N/A"}...'
                )
                self.stdout.write(
                    f"     Other decisions using this entity: {other_decisions_count}"
                )

                if other_decisions_count == 0:
                    orphaned_entities.append(entity)
                    self.stdout.write(
                        f"     [WARN]️  This entity will be orphaned after deletion!"
                    )

            # Store for later use
            decision._orphaned_entities = orphaned_entities

            return decision

        except Decision.DoesNotExist:
            self.stdout.write(f"[ERROR] Decision {ada} not found in database")
            return None

    def _get_user_confirmation(self, keep_entities):
        """Get user confirmation for the rollback operation."""
        self.stdout.write("\n=== ROLLBACK OPTIONS ===")

        if keep_entities:
            self.stdout.write(
                "[RETRY] SAFE ROLLBACK - Will delete decision but keep AFM entities"
            )
        else:
            self.stdout.write(
                "[ALERT] FULL ROLLBACK - Will delete decision and orphaned AFM entities"
            )

        self.stdout.write("\nThis action cannot be undone!")

        response = input("Do you want to proceed? (yes/no): ").strip().lower()
        return response in ["yes", "y"]

    def _execute_rollback(self, decision, keep_entities):
        """Execute the actual rollback operation."""
        ada = decision.ada

        self.stdout.write(
            f'\n{"[RETRY] SAFE" if keep_entities else "[ALERT] FULL"} ROLLBACK - Starting deletion...'
        )

        try:
            with transaction.atomic():
                orphaned_entities = getattr(decision, "_orphaned_entities", [])

                # Delete the decision (this should cascade to relationships and amounts)
                decision.delete()
                self.stdout.write(f"[OK] Deleted decision {ada}")

                if not keep_entities and orphaned_entities:
                    # Clean up orphaned AFM entities
                    orphaned_count = 0
                    for entity in orphaned_entities:
                        # Double-check it's still orphaned after decision deletion
                        if not DecisionEntityRelationship.objects.filter(
                            entity=entity
                        ).exists():
                            afm = entity.afm
                            entity.delete()
                            orphaned_count += 1
                            self.stdout.write(
                                f"[PURGE]️  Deleted orphaned AFM entity: {afm}"
                            )

                    self.stdout.write(
                        f"[OK] Cleanup complete: {orphaned_count} AFM entities removed"
                    )
                elif keep_entities:
                    self.stdout.write("ℹ️  AFM entities preserved for potential reuse")

        except Exception as e:
            self.stdout.write(f"[ERROR] Rollback failed: {str(e)}")
            raise

        # Verification
        self._verify_rollback(ada)

    def _verify_rollback(self, ada):
        """Verify the rollback was successful."""
        self.stdout.write("\n=== VERIFICATION ===")

        try:
            Decision.objects.get(ada=ada)
            self.stdout.write(f"[WARN]️  Decision {ada} still exists in database")
        except Decision.DoesNotExist:
            self.stdout.write(f"[OK] Decision {ada} successfully removed")

        # Check DecisionEntityRelationship cleanup
        remaining_relationships = DecisionEntityRelationship.objects.filter(
            decision__ada=ada
        ).count()
        self.stdout.write(
            f"[CHART] Remaining DecisionEntityRelationship records: {remaining_relationships}"
        )

        # Check DecisionAmountField cleanup
        remaining_amounts = DecisionAmountField.objects.filter(
            decision__ada=ada
        ).count()
        self.stdout.write(
            f"[COST] Remaining DecisionAmountField records: {remaining_amounts}"
        )

        if remaining_relationships == 0 and remaining_amounts == 0:
            self.stdout.write("[OK] All related data successfully cleaned up")
        else:
            self.stdout.write("[WARN]️  Some related data may still exist")

        self.stdout.write(f"\n[EVENT] Rollback completed for decision {ada}")
