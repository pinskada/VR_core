"""Utility to set up loggers that write to a central logs/ directory."""

import logging
import os
from datetime import datetime
from pathlib import Path

import vr_core


def _project_root() -> Path:
    # Resolve the installed editable package path back to your source tree
    pkg_dir = Path(vr_core.__file__).resolve().parent # .../VR_core/vr_core
    return pkg_dir.parent # .../VR_core


def setup_logger(name: str,
                 level=logging.INFO,
                 datefmt: str = "%H:%M:%S",
                 per_process_file: bool = True
) -> logging.Logger:
    """
    Create a logger that always writes to VR_core/logs, regardless of CWD.
    If per_process_file=True, appends the PID to avoid multi-process file clashes.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    root = _project_root()
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    pid = f"_{os.getpid()}" if per_process_file else ""
    logfile = log_dir / f"{name}_{ts}{pid}.log"

    formatter = logging.Formatter(
        fmt='[%(asctime)s] %(processName)s | %(name)s | %(levelname)s | %(message)s',
        datefmt=datefmt,
    )

    fh = logging.FileHandler(logfile)
    fh.setLevel(level)
    fh.setFormatter(formatter)

    # ch = logging.StreamHandler()
    # ch.setLevel(level)
    # ch.setFormatter(formatter)

    logger.setLevel(level)
    logger.addHandler(fh)
    # logger.addHandler(ch)
    return logger
