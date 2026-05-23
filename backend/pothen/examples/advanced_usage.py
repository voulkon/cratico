"""
Advanced usage example for POTHEN scraper.

This example shows how to:
1. Scrape multiple years with configuration
2. Use custom settings
3. Handle errors and sessions
"""

import logging
from pathlib import Path

from pothen import PothenClient
from pothen.config import LoggingConfig, PothenConfig, ScrapingConfig
from pothen.utils import setup_logging


def main():
    """Advanced scraping example with custom configuration."""

    # Custom configuration
    config = PothenConfig(
        scraping=ScrapingConfig(
            download_dir=Path("./advanced_downloads"),
            requests_per_minute=5,  # Be more conservative
            timeout=60,
            max_pdf_size_mb=25,
        ),
        logging=LoggingConfig(
            level="DEBUG", file_path=Path("./logs/pothen_advanced.log")
        ),
    )

    # Setup logging with custom config
    setup_logging(config.logging)
    logger = logging.getLogger("pothen")

    print("POTHEN Scraper - Advanced Example")
    print("=" * 45)

    # Create client with custom settings
    with PothenClient(
        download_dir=config.scraping.download_dir,
        timeout=config.scraping.timeout,
        requests_per_minute=config.scraping.requests_per_minute,
    ) as client:

        # 1. Get available years
        print("\n1. Getting available years...")
        try:
            years = client.get_available_years()
            print(f"Available years: {years}")

            # Select multiple recent years for demo
            target_years = years[:2] if len(years) >= 2 else years
            print(f"Will scrape years: {target_years}")

        except Exception as e:
            logger.error(f"Failed to get years: {e}")
            return

        # 2. Complete scraping workflow for multiple years
        print(f"\n2. Complete scraping workflow...")
        try:
            results = client.scrape_multiple_years(
                years=target_years,
                download_pdfs=True,
                extract_text=True,
                max_downloads_per_year=5,  # Limit downloads for demo
            )

            # Display results
            for year, result in results.items():
                print(f"\nResults for {year}:")
                print(f"  Declarations found: {len(result['declarations'].entries)}")
                print(f"  PDFs downloaded: {len(result['pdf_metadata'])}")
                print(f"  Text extracted: {len(result['extracted_content'])}")

                # Show some extracted MP names
                mp_names = [
                    content.mp_name
                    for content in result["extracted_content"]
                    if content.mp_name
                ]
                if mp_names:
                    print(f"  MPs identified: {', '.join(mp_names[:3])}")
                    if len(mp_names) > 3:
                        print(f"    ... and {len(mp_names) - 3} more")

        except Exception as e:
            logger.error(f"Scraping failed: {e}")
            return

        # 3. Show comprehensive statistics
        print(f"\n3. Final Statistics:")
        stats = client.get_download_stats()
        print(f"  Total files downloaded: {stats['total_files']}")
        print(f"  Total storage used: {stats['total_size_mb']:.2f} MB")

        print("\n  Breakdown by year:")
        for year, year_stats in stats["by_year"].items():
            print(
                f"    {year}: {year_stats['files']} files "
                f"({year_stats['size_mb']:.2f} MB)"
            )

        # 4. Configuration info
        print(f"\n4. Configuration Used:")
        print(f"  Download directory: {config.scraping.download_dir}")
        print(f"  Rate limit: {config.scraping.requests_per_minute} req/min")
        print(f"  Timeout: {config.scraping.timeout}s")
        print(f"  Max PDF size: {config.scraping.max_pdf_size_mb} MB")
        print(f"  Log file: {config.logging.file_path}")


def demonstrate_error_handling():
    """Demonstrate error handling and recovery."""
    print("\n" + "=" * 45)
    print("Error Handling Demonstration")
    print("=" * 45)

    with PothenClient() as client:
        # Try to scrape a non-existent year
        try:
            declarations = client.get_declarations(1999)  # Very unlikely to exist
            print(
                f"Unexpectedly found declarations for 1999: {len(declarations.entries)}"
            )
        except Exception as e:
            print(f"Expected error for invalid year: {type(e).__name__}")

        # Try with valid year but limited downloads
        try:
            years = client.get_available_years()
            if years:
                print(f"\nTrying valid year {years[0]} with download limit...")
                result = client.scrape_year(
                    years[0], download_pdfs=True, max_downloads=1
                )
                print(
                    f"Success with limit: {len(result['pdf_metadata'])} PDFs downloaded"
                )
        except Exception as e:
            print(f"Error with valid year: {e}")


if __name__ == "__main__":
    main()
    demonstrate_error_handling()
