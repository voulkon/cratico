"""
Basic usage example for POTHEN scraper.

This example shows how to:
1. Get available declaration years
2. Scrape declarations for specific years
3. Download and parse PDFs
"""

import logging

from pothen import PothenClient
from pothen.utils import setup_logging


def main():
    """Basic scraping example."""
    # Setup logging
    setup_logging()
    logging.getLogger("pothen")

    # Create client
    with PothenClient(download_dir="./example_downloads") as client:

        print("POTHEN Scraper - Basic Example")
        print("=" * 40)

        # 1. Get available years
        print("\n1. Getting available declaration years...")
        try:
            years = client.get_available_years()
            print(f"Available years: {years}")

            # Use the most recent year for demo
            if years:
                target_year = years[0]
                print(f"Using most recent year: {target_year}")
            else:
                print("No years found!")
                return

        except Exception as e:
            print(f"Error getting years: {e}")
            return

        # 2. Get declarations for the year
        print(f"\n2. Getting declarations for {target_year}...")
        try:
            declarations = client.get_declarations(target_year)
            print(f"Found {len(declarations.entries)} declarations")

            # Show first few declarations
            for i, entry in enumerate(declarations.entries[:3]):
                print(f"  {i+1}. {entry.full_name} - {entry.pdf_url}")

            if len(declarations.entries) > 3:
                print(f"  ... and {len(declarations.entries) - 3} more")

        except Exception as e:
            print(f"Error getting declarations: {e}")
            return

        # 3. Download a few PDFs (limit to 3 for demo)
        print(f"\n3. Downloading sample PDFs...")
        try:
            pdf_metadata = client.download_pdfs(
                declarations.entries[:3], max_downloads=3  # Only first 3 for demo
            )
            print(f"Downloaded {len(pdf_metadata)} PDFs")

            for metadata in pdf_metadata:
                print(f"  - {metadata.filepath.name} ({metadata.filesize_mb:.2f} MB)")

        except Exception as e:
            print(f"Error downloading PDFs: {e}")
            return

        # 4. Extract text from PDFs
        if pdf_metadata:
            print(f"\n4. Extracting text from PDFs...")
            try:
                extracted_content = client.extract_text(pdf_metadata)
                print(f"Extracted text from {len(extracted_content)} PDFs")

                for i, content in enumerate(extracted_content):
                    print(
                        f"  - PDF {i+1}: {len(content.raw_text)} characters, "
                        f"{content.page_count} pages"
                    )
                    if content.mp_name:
                        print(f"    MP Name: {content.mp_name}")

            except Exception as e:
                print(f"Error extracting text: {e}")

        # 5. Show download statistics
        print(f"\n5. Download Statistics:")
        stats = client.get_download_stats()
        print(f"  Total files: {stats['total_files']}")
        print(f"  Total size: {stats['total_size_mb']:.2f} MB")
        for year, year_stats in stats["by_year"].items():
            print(
                f"  {year}: {year_stats['files']} files, {year_stats['size_mb']:.2f} MB"
            )


if __name__ == "__main__":
    main()
