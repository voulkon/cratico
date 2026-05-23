import os
import pickle

from core.importers.decisions import DecisionImporter
from django.core.management.base import BaseCommand
from loguru import logger


class Command(BaseCommand):
    help = "Retry importing decisions from a recovery file"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            required=True,
            help="Path to the recovery/retry pickle file",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=25,
            help="Batch size for retry (smaller than original)",
        )

    def handle(self, *args, **options):
        recovery_file = options["file"]
        batch_size = options["batch_size"]

        if not os.path.exists(recovery_file):
            self.stdout.write(
                self.style.ERROR(f"Recovery file not found: {recovery_file}")
            )
            return

        try:
            with open(recovery_file, "rb") as f:
                data = pickle.load(
                    f
                )  # nosec: B301 - Internal pickle files for import recovery

            if "remaining_decisions" in data:
                # This is a retry file
                decisions = data["remaining_decisions"]
                self.stdout.write(
                    f"Found retry file with {len(decisions)} remaining decisions"
                )
                self.stdout.write(
                    f"Original failure at batch: {data.get('failed_at_batch', 'unknown')}"
                )
                self.stdout.write(
                    f"Already processed: {data.get('total_processed_so_far', 0)} decisions"
                )
            elif "decisions" in data:
                # This is a full recovery file
                decisions = data["decisions"]
                self.stdout.write(
                    f"Found recovery file with {len(decisions)} total decisions"
                )
            else:
                self.stdout.write(self.style.ERROR("Invalid recovery file format"))
                return

            # Initialize importer and retry
            decision_importer = DecisionImporter()

            self.stdout.write(f"Starting retry with batch size {batch_size}")
            logger.info(
                f"Retrying import from {recovery_file} with {len(decisions)} decisions"
            )

            created = decision_importer.import_decisions_in_batches(
                decisions, batch_size
            )

            self.stdout.write(
                self.style.SUCCESS(f"Retry completed! Created {created} decisions")
            )

            # Move processed file to completed folder
            completed_dir = "/code/logs/recovery/completed"
            os.makedirs(completed_dir, exist_ok=True)
            completed_file = os.path.join(
                completed_dir, os.path.basename(recovery_file)
            )
            os.rename(recovery_file, completed_file)

            self.stdout.write(f"Moved recovery file to: {completed_file}")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Retry failed: {str(e)}"))
            logger.error(f"Retry failed for {recovery_file}: {str(e)}", exc_info=True)
            raise
