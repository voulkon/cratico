# POTHEN Scraper

Python package for scraping and parsing Greek Parliament asset declarations from the POTHEN (Πόθεν Έσχες) system.

## Overview

This package provides tools to:
- Scrape declaration pages from the Hellenic Parliament website
- Download PDF asset declarations
- Extract and parse text content from PDFs
- Provide structured data models for the extracted information

## Installation

```bash
cd backend/pothen
poetry install
```

## Usage

```python
from pothen import PothenClient

client = PothenClient()

# Scrape declarations for a specific year
declarations = client.get_declarations(year=2022)

# Download and parse a specific PDF
content = client.parse_pdf_declaration(url="...")
```

## Architecture

The package follows a modular design similar to the gemi package:

- `base_scraper.py`: HTTP client with rate limiting and error handling
- `parliament_parser.py`: HTML parsing for parliament pages
- `pdf_downloader.py`: PDF download management
- `pdf_parser.py`: Text extraction from PDFs
- `schemas/`: Pydantic models for data structures
- `client.py`: Main orchestration client

## Development

```bash
# Install dependencies
poetry install

# Run tests
poetry run pytest

# Format code
poetry run black src/
poetry run isort src/
```
