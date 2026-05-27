"""Unified logging configuration for the agent system.

Usage::

    from src.utils.logging_config import setup_logger
    logger = setup_logger(__name__)
"""

from __future__ import annotations

import logging
import os


def setup_logger(name: str, log_dir: str | None = None) -> logging.Logger:
    """Create (or retrieve) a logger with console + file handlers.

    Args:
        name: Logger name (typically ``__name__``).
        log_dir: Directory for log files.  Defaults to ``<project_root>/logs``.

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if logger.handlers:
        return logger

    # Console — INFO and above
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console.setFormatter(fmt)

    # File — DEBUG and above
    if log_dir is None:
        log_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "logs",
        )
    os.makedirs(log_dir, exist_ok=True)
    file_handler = logging.FileHandler(
        os.path.join(log_dir, f"{name}.log"), encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)

    logger.addHandler(console)
    logger.addHandler(file_handler)
    return logger
