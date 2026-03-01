import logging
import os
import sys
from pathlib import Path


def setup_logging() -> None:
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console (Docker best practice)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    logger.handlers.clear()
    logger.addHandler(ch)

    # Optional file logging (if enabled)
    if os.getenv("LOG_TO_FILE", "0").strip() == "1":
        Path("logs").mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler("logs/bot.log", encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
