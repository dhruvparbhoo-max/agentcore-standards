"""CI path bans: experiments stay out of templates, package guts are not copied, no ARNs."""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))

import check_boundaries  # noqa: E402


def test_repository_has_no_boundary_violations() -> None:
    assert check_boundaries.find_violations(_ROOT) == []


def test_templates_cannot_import_experiments(tmp_path: Path) -> None:
    template = tmp_path / "templates" / "demo"
    template.mkdir(parents=True)
    (template / "app.py").write_text("import experiments.draft\n", encoding="utf-8")
    violations = check_boundaries.find_violations(tmp_path)
    assert any("imports experiments.draft" in item for item in violations)


def test_templates_cannot_copy_package_source(tmp_path: Path) -> None:
    package = tmp_path / "packages" / "widget"
    template = tmp_path / "templates" / "demo"
    package.mkdir(parents=True)
    template.mkdir(parents=True)
    body = "\n".join(f"value_{index} = 'abcdefghijklmnopqrstuvwxyz-{index}'" for index in range(8)) + "\n"
    (package / "impl.py").write_text(body, encoding="utf-8")
    (template / "impl.py").write_text(body, encoding="utf-8")
    violations = check_boundaries.find_violations(tmp_path)
    assert any("copies package source" in item for item in violations)


def test_four_line_copy_is_rejected(tmp_path: Path) -> None:
    package = tmp_path / "packages" / "widget"
    template = tmp_path / "templates" / "demo"
    package.mkdir(parents=True)
    template.mkdir(parents=True)
    body = "\n".join(f"value_{index} = 'abcdefghijklmnopqrstuvwxyz-{index}'" for index in range(4)) + "\n"
    (package / "impl.py").write_text(body, encoding="utf-8")
    (template / "impl.py").write_text(body, encoding="utf-8")
    violations = check_boundaries.find_violations(tmp_path)
    assert any("copies package source" in item for item in violations)


def test_three_line_overlap_is_not_a_copy(tmp_path: Path) -> None:
    package = tmp_path / "packages" / "widget"
    template = tmp_path / "templates" / "demo"
    package.mkdir(parents=True)
    template.mkdir(parents=True)
    body = "\n".join(f"value_{index} = 'abcdefghijklmnopqrstuvwxyz-{index}'" for index in range(3)) + "\n"
    (package / "impl.py").write_text(body, encoding="utf-8")
    (template / "impl.py").write_text(body, encoding="utf-8")
    violations = check_boundaries.find_violations(tmp_path)
    assert violations == []


def test_resource_arns_are_rejected(tmp_path: Path) -> None:
    note = tmp_path / "README.md"
    marker = "arn:" + "aws:"
    note.write_text(f"deployed at {marker}iam:::role/example\n", encoding="utf-8")
    violations = check_boundaries.find_violations(tmp_path)
    assert any("resource ARN" in item for item in violations)
