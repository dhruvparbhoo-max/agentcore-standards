"""Hard gates for template and experiment boundaries.

Fails when:

- ``templates/`` or ``packages/`` import ``experiments``
- a template file repeats a contiguous block of package source
- a tracked text file contains a resource ARN or a private-key marker

Soft wording in docs is not a control. This script is the control.
"""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

_SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "evidence",
    "uploads",
}
_TEXT_SUFFIXES = {".py", ".md", ".toml", ".yml", ".yaml", ".txt", ".example", ".json"}
_TEXT_NAMES = {"CODEOWNERS", "AGENTS.md", ".env.example", "uv.lock"}
_SHINGLE = 4
_MIN_LINE = 12
_ARN_RE = re.compile("arn:" + "aws" + r"[a-z0-9-]*:")
_SECRET_RES = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def find_violations(root: Path) -> list[str]:
    """Return human-readable violations under ``root``. Empty means the tree is clean."""
    violations: list[str] = []
    violations.extend(_experiment_imports(root))
    violations.extend(_copied_package_guts(root))
    violations.extend(_secret_and_arn(root))
    return violations


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    violations = find_violations(root)
    if violations:
        for item in violations:
            print(item)
        return 1
    print("boundary checks passed")
    return 0


def _experiment_imports(root: Path) -> list[str]:
    found: list[str] = []
    for base in (root / "templates", root / "packages"):
        for path in _python_files(base):
            for module in _imported_modules(path):
                if module == "experiments" or module.startswith("experiments."):
                    found.append(f"{path.relative_to(root)}: imports {module}")
    return found


def _copied_package_guts(root: Path) -> list[str]:
    package_shingles: dict[tuple[str, ...], Path] = {}
    for path in _python_files(root / "packages"):
        for window in _shingles(path):
            package_shingles.setdefault(window, path)
    found: list[str] = []
    for path in _python_files(root / "templates"):
        for window in _shingles(path):
            source = package_shingles.get(window)
            if source is not None:
                found.append(f"{path.relative_to(root)}: copies package source from {source.relative_to(root)}")
                break
    return found


def _secret_and_arn(root: Path) -> list[str]:
    found: list[str] = []
    for path in _text_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        if _ARN_RE.search(text):
            found.append(f"{path.relative_to(root)}: resource ARN must not be committed")
        for pattern in _SECRET_RES:
            if pattern.search(text):
                found.append(f"{path.relative_to(root)}: secret-shaped material must not be committed")
                break
    return found


def _imported_modules(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return []
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def _shingles(path: Path) -> set[tuple[str, ...]]:
    lines = _code_lines(path)
    found: set[tuple[str, ...]] = set()
    if len(lines) < _SHINGLE:
        return found
    for index in range(len(lines) - _SHINGLE + 1):
        window = tuple(lines[index : index + _SHINGLE])
        if all(len(line) >= _MIN_LINE for line in window):
            found.add(window)
    return found


def _code_lines(path: Path) -> list[str]:
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(("import ", "from ", '"""', "'''")):
            continue
        if _is_structural(stripped):
            continue
        lines.append(stripped)
    return lines


def _is_structural(line: str) -> bool:
    """Drop import continuations and signatures so a protocol is not a copy.

    The shingle compares statements. A shared ``start`` signature or a shared
    import list is the public contract, not vendored package source.
    """
    if line.startswith(("class ", "def ", "async def ", "@")):
        return True
    if line.startswith(")") and "->" in line:
        return True
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\s*,?", line):
        return True
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\s*:\s*[^#]+,?", line))


def _python_files(base: Path) -> list[Path]:
    if not base.exists():
        return []
    return [path for path in base.rglob("*.py") if _kept(path)]


def _text_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in _SKIP_DIRS and not name.endswith(".egg-info")]
        for name in filenames:
            path = Path(dirpath) / name
            if name in _TEXT_NAMES or path.suffix in _TEXT_SUFFIXES:
                found.append(path)
    return found


def _kept(path: Path) -> bool:
    return not any(part in _SKIP_DIRS for part in path.parts)


if __name__ == "__main__":
    sys.exit(main())
