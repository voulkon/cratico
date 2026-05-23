from core.services.document_parser_tester import DocumentParserTester
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Test document parsing rules against extracted documents"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit", type=int, default=100, help="Number of documents to test"
        )
        parser.add_argument(
            "--ada-file", type=str, help="File with list of ADAs to test"
        )
        parser.add_argument(
            "--min-length", type=int, default=100, help="Minimum text length"
        )

    def handle(self, *args, **options):
        tester = DocumentParserTester()

        # Load ADA list if provided
        ada_list = None
        if options["ada_file"]:
            with open(options["ada_file"], "r") as f:
                ada_list = [line.strip() for line in f if line.strip()]

        result = tester.test_parsing_rules(
            limit=options["limit"],
            sample_ada_list=ada_list,
            min_text_length=options["min_length"],
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"[OK] Test completed: {result.success_rate:.1f}% success rate "
                f"({result.successful_parses}/{result.total_documents})"
            )
        )

        if result.failure_breakdown:
            self.stdout.write("[ERROR] Failure breakdown:")
            for failure_type, count in result.failure_breakdown.items():
                self.stdout.write(f"  - {failure_type}: {count}")
