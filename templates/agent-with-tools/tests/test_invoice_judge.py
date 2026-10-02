"""The tools judge fails closed when Runtime settings are missing."""

import json
from pathlib import Path

import pytest
from agent_with_tools.judge import main


def test_memory_judge_passes(tmp_path: Path) -> None:
    code = main(["--harness", "memory", "--evidence-dir", str(tmp_path)])
    assert code == 0
    verdict = json.loads((tmp_path / "verdict.json").read_text(encoding="utf-8"))
    assert verdict["status"] == "PASS"
    assert verdict["harness"] == "memory"
    assert len(verdict["evals"]) == 5


def test_runtime_judge_skip_is_not_a_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_REGION",
        "AGENTCORE_RUNTIME_ARN",
        "AGENTCORE_SPAN_LOG_GROUP",
    ):
        monkeypatch.delenv(name, raising=False)
    code = main(["--harness", "runtime", "--evidence-dir", str(tmp_path)])
    assert code == 1
    verdict = json.loads((tmp_path / "verdict.json").read_text(encoding="utf-8"))
    assert verdict["status"] == "SKIPPED"
    assert verdict["evals"] == []
    assert "AGENTCORE_RUNTIME_ARN" in verdict["missing_settings"]
