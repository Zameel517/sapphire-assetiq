"""
logger.py
=========
Structured logging, written to output/logs/ so a failed scan on a
remote machine can still be diagnosed after the fact.
"""

import logging
import os
import sys
from datetime import datetime


def get_logger(name: str = "SapphireAssetIQ", log_dir: str = "output/logs") -> logging.Logger:
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"scan_{datetime.now():%Y%m%d_%H%M%S}.log")

    logger = logging.getLogger(name)
    if logger.handlers:  # avoid duplicate handlers on repeated calls
        return logger

    logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))

    logger.addHandler(file_handler)
    if sys.stderr is not None:          # a windowed EXE has no console to write to
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        logger.addHandler(console_handler)
    return logger
