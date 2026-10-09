"""scripts/images.py finds every unit and builds bases before units."""

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))

import images  # noqa: E402


def test_repo_units_have_one_base_each() -> None:
    found = {image.name: image.base_arg for image in images.units()}
    assert found["template-agent"] == "BASE_AGENT_IMAGE"
    assert found["tool-template"] == "BASE_LAMBDA_IMAGE"


def test_build_order_is_bases_then_units() -> None:
    ran: list[list[str]] = []
    assert images.main(["build", "--tag", "t", "--only", "template-agent"], run=lambda c: ran.append(c) or 0) == 0
    tags = [command[command.index("-t") + 1] for command in ran]
    assert tags == [
        "agentcore-standards/base-agent:t",
        "agentcore-standards/base-lambda:t",
        "agentcore-standards/template-agent:t",
    ]
    assert "linux/arm64" in ran[-1]
    assert "BASE_AGENT_IMAGE=agentcore-standards/base-agent:t" in ran[-1]
    assert ran[-1][-1] == str(_ROOT)


def test_unknown_unit_is_an_error() -> None:
    assert images.main(["build", "--only", "nope"], run=lambda c: 0) == 1


def test_dockerfile_must_name_one_base(tmp_path: Path) -> None:
    folder = tmp_path / "primitives" / "front_door"
    folder.mkdir(parents=True)
    (folder / "Dockerfile").write_text("FROM python\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="declare exactly one"):
        images.units(tmp_path)


def test_scan_checks_every_image_and_reports_all_failures() -> None:
    ran: list[list[str]] = []

    def run(command: list[str]) -> int:
        ran.append(command)
        return 1 if command[-1].endswith("base-lambda:t") else 0

    assert images.main(["scan", "--tag", "t"], run=run) == 1
    assert [command[-1] for command in ran][:2] == [
        "agentcore-standards/base-agent:t",
        "agentcore-standards/base-lambda:t",
    ]
    assert len(ran) == 2 + len(images.units())
    assert all("--ignore-unfixed" in command and "HIGH,CRITICAL" in command for command in ran)
