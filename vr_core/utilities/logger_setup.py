"""Utility to set up loggers that write to a central logs/ directory."""

import logging
import os
import re
from datetime import datetime
from pathlib import Path

import vr_core


# ---------- paths / session ----------
def _project_root() -> Path:
    pkg_dir = Path(vr_core.__file__).resolve().parent  # .../VR_core/vr_core
    return pkg_dir.parent                               # .../VR_core

def _session_id() -> str:
    # Shared across processes if VR_SESSION_ID is set
    return os.getenv("VR_SESSION_ID", datetime.now().strftime("%H-%M-%S"))

def _safe_name(name: str) -> str:
    # Make a safe folder/file name from logger name
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")


# ---------- aligned formatter ----------
class AlignedFormatter(logging.Formatter):
    """
    Pads/truncates fields to fixed widths so the vertical bars align.
    Only the final %(message)s is free-length.
    """
    def __init__(self, datefmt="%H:%M:%S", name_w=18, level_w=8, ellipsis="…"):
        fmt = (
            "[%(asctime)s.%(msecs)03d] | "
            "%(name_a)s | %(level_a)s | "
            "%(message)s"
        )
        super().__init__(fmt=fmt, datefmt=datefmt)
        self.name_w  = name_w
        self.level_w = level_w
        self.ellipsis = ellipsis

    def _padclip(self, s: str, width: int) -> str:
        s = str(s)
        if len(s) <= width:
            return s.ljust(width)
        ell = self.ellipsis or ""
        keep = max(0, width - len(ell))
        return (s[:keep] + ell)[:width]

    def format(self, record):
        record.name_a  = self._padclip(record.name,      self.name_w)
        record.level_a = self._padclip(record.levelname, self.level_w)
        return super().format(record)


# ---------- setup ----------
def setup_logger(
    name: str,
    level: int = logging.INFO,
    per_process_file: bool = True,
    console: bool = True,
) -> logging.Logger:
    """
    Create a logger that writes:
      1) logs/<module_name>/<module_name>_<time>[_pid].log
      2) logs/_combined/<session>.log (shared across modules/processes in the run)
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured in this process

    root = _project_root()
    session = _session_id()
    time_only = datetime.now().strftime("%H-%M-%S")
    pid_suffix = f"_{os.getpid()}" if per_process_file else ""

    # per-module file in its own folder
    mod = _safe_name(name)
    mod_dir = root / "logs" / mod
    mod_dir.mkdir(parents=True, exist_ok=True)
    mod_path = mod_dir / f"{mod}_{time_only}{pid_suffix}.log"

    # combined file for this session (shared across modules/processes)
    comb_dir = root / "logs" / "_combined"
    comb_dir.mkdir(parents=True, exist_ok=True)
    comb_path = comb_dir / f"{session}.log"

    formatter = AlignedFormatter(datefmt="%H:%M:%S", name_w=18, level_w=8, ellipsis="…")

    # Per-module file handler
    fh = logging.FileHandler(mod_path, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # Combined session file handler (append)
    try:
        ch_all = logging.FileHandler(comb_path, encoding="utf-8")
        ch_all.setLevel(level)
        ch_all.setFormatter(formatter)
        logger.addHandler(ch_all)
    except Exception:
        # If another process locks the file on Windows, skip silently.
        # (For bulletproof cross-process logging, switch to a SocketHandler-based listener.)
        pass

    # Optional console output
    if console:
        sh = logging.StreamHandler()
        sh.setLevel(level)
        sh.setFormatter(formatter)
        logger.addHandler(sh)

    logger.setLevel(level)
    logger.propagate = False
    return logger
