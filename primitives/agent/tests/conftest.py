from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
TEMPLATE = REPO / "patterns" / "_template"


@pytest.fixture
def template_raw() -> dict[str, Any]:
    raw = yaml.safe_load((TEMPLATE / "pattern.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


@pytest.fixture
def make_pattern(tmp_path: Path, template_raw: dict[str, Any]) -> Callable[..., Path]:
    """Copy the template into ``tmp_path/<name>`` with top-level overrides."""

    def make(name: str = "demo-pattern", **overrides: Any) -> Path:
        folder = tmp_path / name
        shutil.copytree(TEMPLATE, folder, ignore=shutil.ignore_patterns("agentcore", "__pycache__"))
        raw = dict(template_raw)
        raw["name"] = name
        for key, value in overrides.items():
            if isinstance(value, Mapping) and isinstance(raw.get(key), Mapping):
                raw[key] = {**raw[key], **value}
            else:
                raw[key] = value
        (folder / "pattern.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        return folder

    return make
