from core.models.document_analysis import DocumentExtraction
from core.services.opensearch_service import OpenSearchService
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Test OpenSearch migration with a single document"

    def handle(self, *args, **options):
        self.stdout.write("Testing OpenSearch migration...")

        # Find one completed extraction
        extraction = (
            DocumentExtraction.objects.filter(
                extraction_status="COMPLETED", raw_text__isnull=False
            )
            .exclude(raw_text="")
            .first()
        )

        if not extraction:
            self.stdout.write(self.style.ERROR("No completed extractions found"))
            return

        decision = extraction.decision

        self.stdout.write(f"Found test document:")
        self.stdout.write(f"  ID: {extraction.id}")
        self.stdout.write(f"  ADA: {decision.ada}")
        self.stdout.write(f"  Subject: {decision.subject}")
        self.stdout.write(f"  Organization: {decision.organization}")
        self.stdout.write(f"  Decision Type: {decision.decision_type}")
        self.stdout.write(
            f"  Content length: {len(extraction.raw_text) if extraction.raw_text else 0} chars"
        )

        # Show preview of content
        content_preview = extraction.raw_text[:300] if extraction.raw_text else ""
        self.stdout.write(f"  Content preview: {content_preview}...")

        # Test indexing
        try:
            opensearch_service = OpenSearchService()

            document_data = {
                "decision_id": decision.id,
                "ada": decision.ada,
                "title": decision.subject or "",
                "content": extraction.raw_text,
                "organization": (
                    str(decision.organization) if decision.organization else ""
                ),
                "decision_type": (
                    str(decision.decision_type) if decision.decision_type else ""
                ),
                "issue_date": (
                    decision.issue_date.isoformat() if decision.issue_date else None
                ),
                "extraction_date": (
                    extraction.extraction_date.isoformat()
                    if extraction.extraction_date
                    else None
                ),
                "character_count": extraction.character_count,
                "page_count": extraction.page_count,
            }

            success = opensearch_service.index_document(document_data)

            if success:
                self.stdout.write(
                    self.style.SUCCESS("[OK] Document indexed successfully")
                )

                # Test multiple search terms that should be common
                search_terms = [
                    "ΔΗΜΟΚΡΑΤΙΑ",  # Most common
                    "ΕΛΛΗΝΙΚΗ",  # Part of "ΕΛΛΗΝΙΚΗ ΔΗΜΟΚΡΑΤΙΑ"
                    "ΥΠΟΥΡΓΕΙΟ",  # Ministry
                    "ΑΝΑΛΗΨΗ",  # From the decision type
                    "υπηρεσιών",  # From the title (lowercase)
                    "ΥΠΗΡΕΣΙΩΝ",  # From the title (uppercase)
                ]

                for term in search_terms:
                    self.stdout.write(f"\n--- Testing search for: '{term}' ---")

                    # Check if term is in the content first
                    is_in_title = term.upper() in (decision.subject or "").upper()
                    is_in_content = term.upper() in (extraction.raw_text or "").upper()

                    self.stdout.write(f"Term present in title: {is_in_title}")
                    self.stdout.write(f"Term present in content: {is_in_content}")

                    search_results = opensearch_service.search_documents(term, size=5)
                    hits = search_results.get("hits", {}).get("hits", [])
                    total_hits = (
                        search_results.get("hits", {}).get("total", {}).get("value", 0)
                    )

                    self.stdout.write(
                        f"Search returned {len(hits)} results (total: {total_hits})"
                    )

                    if hits:
                        for i, hit in enumerate(hits):
                            source = hit["_source"]
                            score = hit["_score"]
                            highlights = hit.get("highlight", {})

                            self.stdout.write(f"  Result {i+1} (score: {score:.2f}):")
                            self.stdout.write(f"    ADA: {source['ada']}")
                            self.stdout.write(f"    Title: {source['title'][:60]}...")

                            # Show highlights if available
                            if highlights:
                                for field, highlight_list in highlights.items():
                                    self.stdout.write(
                                        f"    Highlight ({field}): {highlight_list[0][:100]}..."
                                    )
                    else:
                        self.stdout.write("  No results found")

                # Test raw analyzer to see what tokens are produced
                self.stdout.write(f"\n--- Testing text analysis ---")
                test_texts = [
                    decision.subject[:100] if decision.subject else "",
                    "ΕΛΛΗΝΙΚΗ ΔΗΜΟΚΡΑΤΙΑ",
                    "ΥΠΟΥΡΓΕΙΟ ΥΠΟΔΟΜΩΝ",
                ]

                for text in test_texts:
                    if text:
                        self.stdout.write(f"Analyzing: '{text}'")
                        tokens = opensearch_service._analyze_text(text)
                        if tokens:
                            self.stdout.write(
                                f"  Tokens: {tokens[:10]}"
                            )  # Show first 10 tokens
                        else:
                            self.stdout.write(f"  Failed to analyze")

                # Check total documents in index
                self.stdout.write(f"\n--- Index status ---")
                match_all_results = opensearch_service._test_match_all()
                if match_all_results:
                    total_docs = (
                        match_all_results.get("hits", {})
                        .get("total", {})
                        .get("value", 0)
                    )
                    self.stdout.write(f"Total documents in index: {total_docs}")

                    if total_docs > 0:
                        # Show first document in index
                        first_doc = match_all_results.get("hits", {}).get("hits", [])
                        if first_doc:
                            sample = first_doc[0]["_source"]
                            self.stdout.write(
                                f"Sample document ADA: {sample.get('ada')}"
                            )
                else:
                    self.stdout.write("Failed to get index statistics")

            else:
                self.stdout.write(self.style.ERROR("[FAIL] Failed to index document"))

        except Exception as e:
            import traceback

            self.stdout.write(self.style.ERROR(f"[FAIL] Error: {e}"))
            self.stdout.write(f"Traceback: {traceback.format_exc()}")
