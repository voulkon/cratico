"""Configuration management for POTHEN scraper."""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load environment variables from .env file
load_dotenv()


class ScrapingConfig(BaseModel):
    """Configuration for scraping operations."""

    # HTTP settings
    timeout: int = Field(default=30, description="HTTP request timeout in seconds")
    max_retries: int = Field(default=3, description="Maximum retry attempts")
    requests_per_minute: int = Field(default=10, description="Rate limit for requests")
    user_agent: str = Field(
        default="pothen-scraper/1.0.0", description="User agent string"
    )

    # Download settings
    download_dir: Path = Field(
        default=Path("./pothen_downloads"), description="Directory for downloads"
    )
    pdf_chunk_size: int = Field(default=8192, description="Chunk size for downloads")
    max_pdf_size_mb: int = Field(default=50, description="Maximum PDF file size")

    # Text extraction settings
    preferred_pdf_method: str = Field(
        default="pdfplumber", description="Preferred PDF extraction method"
    )
    min_content_length: int = Field(
        default=100, description="Minimum content length for valid extraction"
    )

    # Validation
    def __post_init__(self):
        """Post-initialization validation."""
        # Ensure download directory exists
        self.download_dir.mkdir(parents=True, exist_ok=True)

        # Validate PDF extraction method
        if self.preferred_pdf_method not in ["pdfplumber", "pypdf2"]:
            raise ValueError("preferred_pdf_method must be 'pdfplumber' or 'pypdf2'")


class LoggingConfig(BaseModel):
    """Configuration for logging."""

    level: str = Field(default="INFO", description="Logging level")
    format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log format string",
    )
    file_path: Optional[Path] = Field(None, description="Log file path")
    max_file_size: int = Field(
        default=10 * 1024 * 1024, description="Max log file size in bytes"
    )
    backup_count: int = Field(default=3, description="Number of backup log files")


class PothenConfig(BaseModel):
    """Main configuration class for POTHEN scraper."""

    scraping: ScrapingConfig = Field(default_factory=ScrapingConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @classmethod
    def from_env(cls) -> "PothenConfig":
        """Create configuration from environment variables."""
        config_dict = {"scraping": {}, "logging": {}}

        # Scraping configuration from environment
        if os.getenv("POTHEN_TIMEOUT"):
            config_dict["scraping"]["timeout"] = int(os.getenv("POTHEN_TIMEOUT"))

        if os.getenv("POTHEN_MAX_RETRIES"):
            config_dict["scraping"]["max_retries"] = int(
                os.getenv("POTHEN_MAX_RETRIES")
            )

        if os.getenv("POTHEN_RATE_LIMIT"):
            config_dict["scraping"]["requests_per_minute"] = int(
                os.getenv("POTHEN_RATE_LIMIT")
            )

        if os.getenv("POTHEN_DOWNLOAD_DIR"):
            config_dict["scraping"]["download_dir"] = Path(
                os.getenv("POTHEN_DOWNLOAD_DIR")
            )

        if os.getenv("POTHEN_USER_AGENT"):
            config_dict["scraping"]["user_agent"] = os.getenv("POTHEN_USER_AGENT")

        if os.getenv("POTHEN_PDF_METHOD"):
            config_dict["scraping"]["preferred_pdf_method"] = os.getenv(
                "POTHEN_PDF_METHOD"
            )

        # Logging configuration from environment
        if os.getenv("POTHEN_LOG_LEVEL"):
            config_dict["logging"]["level"] = os.getenv("POTHEN_LOG_LEVEL")

        if os.getenv("POTHEN_LOG_FILE"):
            config_dict["logging"]["file_path"] = Path(os.getenv("POTHEN_LOG_FILE"))

        return cls(**config_dict)

    @classmethod
    def from_file(cls, config_path: Path) -> "PothenConfig":
        """Load configuration from a JSON file."""
        import json

        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(config_path, "r") as f:
            config_dict = json.load(f)

        return cls(**config_dict)

    def save_to_file(self, config_path: Path) -> None:
        """Save configuration to a JSON file."""
        import json

        config_path.parent.mkdir(parents=True, exist_ok=True)

        with open(config_path, "w") as f:
            json.dump(self.dict(), f, indent=2, default=str)


# Default configuration instance
default_config = PothenConfig()


def get_config() -> PothenConfig:
    """Get configuration, prioritizing environment variables."""
    try:
        return PothenConfig.from_env()
    except Exception:
        return default_config
