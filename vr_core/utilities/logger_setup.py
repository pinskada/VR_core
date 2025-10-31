"""Utility to set up logging for VR core components."""

import logging
import os
from datetime import datetime

def setup_logger(name: str, level=logging.INFO) -> logging.Logger:
    """Set up a logger with file and console handlers."""

    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)

    # Time-stamped log file
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    logfile = f"logs/{name}_{timestamp}.log"

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Formatter
    formatter = logging.Formatter(
        '[%(asctime)s] %(name)s | %(levelname)s | %(message)s',
        datefmt='%H:%M:%S'
    )

    # File handler
    fh = logging.FileHandler(logfile)
    fh.setLevel(level)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    return logger
