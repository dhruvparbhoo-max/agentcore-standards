"""Offline eval modules. ``run_suite`` loads every module in this directory."""

from pathlib import Path


def pack_suite_dir() -> Path:
    """Directory of suite modules that export ``EVALS``."""
    return Path(__file__).resolve().parent
