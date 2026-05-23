"""Pydantic models for POTHEN data structures."""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, HttpUrl, validator


class DeclarationType(str, Enum):
    """Types of asset declarations."""

    INITIAL = "arxiki"  # αρχική - initial declaration
    ANNUAL = "ethsia"  # ετήσια - annual declaration


class DeclarationEntry(BaseModel):
    """Individual declaration entry from parliament table."""

    last_name: str = Field(..., description="MP's last name")
    first_name: str = Field(..., description="MP's first name")
    pdf_url: HttpUrl = Field(..., description="URL to the PDF declaration")
    year: int = Field(..., description="Declaration year")
    declaration_type: DeclarationType = Field(..., description="Type of declaration")

    # Extracted from filename
    afm: Optional[str] = Field(None, description="Tax identification number (AFM)")
    file_id: Optional[str] = Field(None, description="Unique file identifier")

    @validator("pdf_url")
    def validate_parliament_url(cls, v):
        """Ensure URL is from parliament domain."""
        if not str(v).startswith("http://www.hellenicparliament.gr/"):
            raise ValueError("PDF URL must be from hellenicparliament.gr domain")
        return v

    @property
    def filename(self) -> str:
        """Extract filename from PDF URL."""
        return Path(str(self.pdf_url)).name

    @property
    def full_name(self) -> str:
        """Formatted full name."""
        return f"{self.first_name} {self.last_name}"


class PDFMetadata(BaseModel):
    """Metadata about a downloaded PDF file."""

    url: HttpUrl = Field(..., description="Original PDF URL")
    filepath: Path = Field(..., description="Local file path")
    filesize_bytes: int = Field(..., description="File size in bytes")
    download_timestamp: datetime = Field(default_factory=datetime.now)
    content_hash: Optional[str] = Field(None, description="SHA256 hash of content")

    @property
    def filesize_mb(self) -> float:
        """File size in megabytes."""
        return self.filesize_bytes / (1024 * 1024)


class ParsedDeclarationContent(BaseModel):
    """Extracted and parsed content from a declaration PDF."""

    raw_text: str = Field(..., description="Raw extracted text")
    page_count: int = Field(..., description="Number of pages in PDF")
    extraction_method: str = Field(..., description="Method used to extract text")

    # Structured data (to be expanded based on actual PDF content analysis)
    mp_name: Optional[str] = Field(None, description="Extracted MP name")
    declaration_date: Optional[datetime] = Field(None, description="Declaration date")
    assets: Optional[Dict[str, Any]] = Field(
        None, description="Structured asset information"
    )

    @validator("raw_text")
    def validate_text_length(cls, v):
        """Ensure extracted text has minimum content."""
        if len(v.strip()) < 50:
            raise ValueError("Extracted text too short to be valid")
        return v


class YearlyDeclarations(BaseModel):
    """Collection of declarations for a specific year."""

    year: int = Field(..., description="Declaration year")
    page_url: HttpUrl = Field(..., description="Source parliament page URL")
    scrape_timestamp: datetime = Field(default_factory=datetime.now)
    entries: List[DeclarationEntry] = Field(default_factory=list)

    @property
    def total_declarations(self) -> int:
        """Total number of declarations found."""
        return len(self.entries)

    @property
    def declarations_by_type(self) -> Dict[DeclarationType, int]:
        """Count declarations by type."""
        counts = {}
        for entry in self.entries:
            counts[entry.declaration_type] = counts.get(entry.declaration_type, 0) + 1
        return counts


class ScrapingSession(BaseModel):
    """Complete scraping session data."""

    session_id: str = Field(..., description="Unique session identifier")
    start_time: datetime = Field(default_factory=datetime.now)
    end_time: Optional[datetime] = Field(None)
    years_scraped: List[int] = Field(default_factory=list)
    total_declarations_found: int = Field(0)
    total_pdfs_downloaded: int = Field(0)
    errors: List[str] = Field(default_factory=list)

    @property
    def duration_minutes(self) -> Optional[float]:
        """Session duration in minutes."""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds() / 60
        return None
