"""
utils/logger.py
Configures application-wide logging for Friday.
"""

import logging
import logging.handlers
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")


def setup_logger(level: str = "INFO"):
    """
    Configure the root 'Friday' logger with:
      - Rotating file handler  (friday_YYYY-MM-DD.log)
      - Console (stdout) handler
    """
    os.makedirs(LOG_DIR, exist_ok=True)

    log_level = getattr(logging, level.upper(), logging.INFO)

    root_logger = logging.getLogger("Friday")
    root_logger.setLevel(log_level)

    if root_logger.handlers:
        return  # Already configured

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # --- File handler ---
    log_file = os.path.join(LOG_DIR, f"friday_{datetime.now().strftime('%Y-%m-%d')}.log")
    fh = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    fh.setLevel(log_level)

    # --- Console handler ---
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    ch.setLevel(log_level)

    root_logger.addHandler(fh)
    root_logger.addHandler(ch)

    root_logger.info("Logger initialised – log file: %s", log_file)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the Friday namespace."""
    return logging.getLogger(f"Friday.{name}")
