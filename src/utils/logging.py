"""Thin wrapper around ``logging`` so the CLI and Streamlit UI share a format."""
from __future__ import annotations

import logging
import sys


_CONFIGURED = False


def get_logger(name: str = "hso", level: int = logging.INFO) -> logging.Logger:
    """Return a module-level logger with a single stream handler.

    Safe to call repeatedly from any module; the global ``_CONFIGURED`` flag
    keeps the handler count from exploding under pytest / Streamlit reloads.
    """
    global _CONFIGURED
    logger = logging.getLogger(name)
    logger.setLevel(level)
    if not _CONFIGURED:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s",
                              datefmt="%H:%M:%S")
        )
        logger.addHandler(handler)
        _CONFIGURED = True
    return logger
