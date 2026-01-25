"""Logging configuration for bluesky_search."""

import logging
import sys


def setup_logger(name: str = "bluesky_search", level: str = "INFO") -> logging.Logger:
    """Set up and return a configured logger.

    Args:
        name: Logger name (default: bluesky_search)
        level: Logging level (default: INFO)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper()))

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(handler)

    return logger
