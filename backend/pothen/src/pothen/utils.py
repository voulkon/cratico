"""Logging utilities for POTHEN scraper."""

import logging
import logging.handlers
from typing import Optional

from .config import LoggingConfig


def setup_logging(config: Optional[LoggingConfig] = None) -> logging.Logger:
    """
    Setup logging configuration for POTHEN scraper.

    Args:
        config: LoggingConfig object. If None, uses default configuration.

    Returns:
        Configured logger instance
    """
    if config is None:
        from .config import default_config

        config = default_config.logging

    # Get the root logger for our package
    logger = logging.getLogger("pothen")
    logger.setLevel(getattr(logging, config.level.upper()))

    # Remove existing handlers to avoid duplicates
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Create formatter
    formatter = logging.Formatter(config.format)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, config.level.upper()))
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler if specified
    if config.file_path:
        # Ensure log directory exists
        config.file_path.parent.mkdir(parents=True, exist_ok=True)

        # Use rotating file handler to prevent huge log files
        file_handler = logging.handlers.RotatingFileHandler(
            config.file_path,
            maxBytes=config.max_file_size,
            backupCount=config.backup_count,
        )
        file_handler.setLevel(getattr(logging, config.level.upper()))
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # Prevent propagation to avoid duplicate messages
    logger.propagate = False

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger for a specific module."""
    return logging.getLogger(f"pothen.{name}")
