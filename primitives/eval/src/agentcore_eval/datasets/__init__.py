"""JSON datasets shipped inside the package so tests and wheels load the same files."""

import json
from pathlib import Path
from typing import Any


def dataset_dir() -> Path:
    """Directory that holds the packaged JSON datasets."""
    return Path(__file__).resolve().parent


def read_json(name: str) -> dict[str, Any]:
    """Read one JSON object from ``dataset_dir``."""
    path = dataset_dir() / name
    if not path.is_file():
        raise ValueError(f"dataset file is missing: {name}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{name} must be a JSON object")
    typed: dict[str, Any] = {}
    for key, value in payload.items():
        if not isinstance(key, str):
            raise ValueError(f"{name} keys must be strings")
        typed[key] = value
    return typed
