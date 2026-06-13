import json
import os

from core.models.decisions import Decision
from core.models.document_analysis import DocumentExtraction
from core.models.types import ActType
from core.services.financial_calculation_service import financial_service
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Export sample decisions grouped by type for manual inspection"

    def add_arguments(self, parser):
        parser.add_argument(
            "--sample-size", type=int, default=5, help="Number of decisions per type"
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default="decision_samples",
            help="Output directory",
        )
        parser.add_argument(
            "--separate-files",
            action="store_true",
            help="Save text and metadata in separate files",
        )
        parser.add_argument(
            "--include-txt",
            action="store_true",
            help="Also create .txt file for easier reading (in addition to JSON)",
        )
        parser.add_argument(
            "--include-no-text",
            action="store_true",
            help="Include decisions without extracted text",
        )

    def handle(self, *args, **options):
        sample_size = options["sample_size"]
        output_dir = options["output_dir"]
        separate_files = options["separate_files"]
        include_txt = options["include_txt"]
        include_no_text = options["include_no_text"]

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        types = ActType.objects.all()
        total_exported = 0
        total_skipped = 0

        for act_type in types:
            # Get random samples with extraction (filter first for efficiency)
            if not include_no_text:
                # Only get decisions that have extractions
                decisions = Decision.objects.filter(
                    decision_type=act_type,
                    text_extraction__isnull=False,  # Correct relation name
                ).order_by("?")[:sample_size]
            else:
                decisions = Decision.objects.filter(decision_type=act_type).order_by(
                    "?"
                )[:sample_size]

            if not decisions.exists():
                continue

            # Create safe directory name
            safe_label = "".join(
                [
                    c if c.isalnum() or c in (" ", "-", "_") else "_"
                    for c in act_type.label
                ]
            ).strip()
            type_dir_name = f"{act_type.uid}_{safe_label}"
            type_dir = os.path.join(output_dir, type_dir_name)

            if not os.path.exists(type_dir):
                os.makedirs(type_dir)

            self.stdout.write(f"Exporting samples for {act_type.label}...")

            for decision in decisions:
                # Get extraction text
                text = ""
                extraction_status = "not_found"
                try:
                    extraction = DocumentExtraction.objects.get(decision=decision)
                    text = extraction.raw_text or ""
                    extraction_status = extraction.extraction_status
                except DocumentExtraction.DoesNotExist:
                    text = ""

                # Skip if no text and flag is not set
                if not text and not include_no_text:
                    total_skipped += 1
                    continue

                # Calculate accurate amount using FinancialCalculationService
                accurate_amount = financial_service.get_decision_total_amount(decision)

                # Get entity amounts for additional context
                entity_amounts = [
                    ea.model_dump(mode="json")
                    for ea in financial_service.get_decision_entity_amounts(decision)
                ]

                # Build comprehensive metadata
                metadata = {
                    "ada": decision.ada,
                    "subject": decision.subject,
                    "issue_date": str(decision.issue_date),
                    "decision_type": {"uid": act_type.uid, "label": act_type.label},
                    "organization": {
                        "uid": (
                            decision.organization.uid if decision.organization else None
                        ),
                        "label": (
                            str(decision.organization)
                            if decision.organization
                            else None
                        ),
                    },
                    "amounts": {
                        "calculated_total": str(accurate_amount),  # From relationships
                        "decision_field": (
                            str(decision.amount) if decision.amount else None
                        ),  # Legacy field
                        "entity_breakdown": [
                            {
                                "entity_name": ea["entity"]["name"],
                                "afm": ea["entity"]["afm"],
                                "role": ea["role"],
                                "amount": str(ea["total_amount"]),
                            }
                            for ea in entity_amounts
                        ],
                    },
                    "extraction": {
                        "status": extraction_status,
                        "text_length": len(text),
                        "has_text": bool(text),
                    },
                    "document_url": decision.document_url,
                    "status": decision.status,
                }

                if separate_files:
                    # Old behavior: separate .txt and .json files
                    with open(
                        os.path.join(type_dir, f"{decision.ada}.txt"),
                        "w",
                        encoding="utf-8",
                    ) as f:
                        f.write(f"ADA: {decision.ada}\n")
                        f.write(f"Subject: {decision.subject}\n")
                        f.write(f"Type: {act_type.label}\n")
                        f.write("-" * 80 + "\n")
                        f.write(text)

                    with open(
                        os.path.join(type_dir, f"{decision.ada}.json"),
                        "w",
                        encoding="utf-8",
                    ) as f:
                        json.dump(metadata, f, ensure_ascii=False, indent=2)
                else:
                    # New behavior: combined JSON with text included
                    metadata["text"] = text
                    with open(
                        os.path.join(type_dir, f"{decision.ada}.json"),
                        "w",
                        encoding="utf-8",
                    ) as f:
                        json.dump(metadata, f, ensure_ascii=False, indent=2)

                    # Optionally also create .txt for easier reading in editors
                    if include_txt:
                        with open(
                            os.path.join(type_dir, f"{decision.ada}.txt"),
                            "w",
                            encoding="utf-8",
                        ) as f:
                            f.write(text)

                total_exported += 1

        summary = f"Successfully exported {total_exported} decisions to {output_dir}"
        if total_skipped > 0:
            summary += f"\nSkipped {total_skipped} decisions without extracted text"
        if separate_files:
            summary += "\nFormat: Separate .txt and .json files"
        elif include_txt:
            summary += "\nFormat: Combined JSON files + companion .txt files"
        else:
            summary += "\nFormat: Combined JSON files"

        self.stdout.write(self.style.SUCCESS(summary))
