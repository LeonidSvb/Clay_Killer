"""
app/utils/logger.py — File logger for enrichment runs.
No Streamlit dependency. Writes to logs/enrichment.log.
"""

import logging
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent.parent / "logs"


def get_logger(name: str = "enrichment") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        LOG_DIR.mkdir(exist_ok=True)
        handler = logging.FileHandler(LOG_DIR / "enrichment.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-5s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    return logger
