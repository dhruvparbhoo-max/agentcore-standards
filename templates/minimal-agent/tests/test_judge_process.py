"""The minimal-agent judge is a separate process from the author tests."""

import json
import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_SRC = Path(__file__).resolve().parents[1] / "src"


def _run_judge(evidence: Path, *extra: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy() if env is None else env
    process_env["PYTHONPATH"] = str(_SRC)
    return subprocess.run(
        [sys.executable, "-m", "minimal_agent.judge", "--evidence-dir", str(evidence), *extra],
        cwd=_REPO,
        env=process_env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_memory_judge_process_passes_golden_eval(tmp_path: Path) -> None:
    evidence = tmp_path / "judge"
    completed = _run_judge(evidence)
    assert completed.returncode == 0, completed.stderr
    summary = json.loads((evidence / "verdict.json").read_text(encoding="utf-8"))
    assert summary["status"] == "PASS"
    assert summary["harness"] == "memory"
    assert summary["evals"][0]["name"] == "minimal-agent.golden-turn"
    lifecycle = summary["evals"][0]["lifecycle"]
    assert lifecycle[0] == "start"
    assert lifecycle[-1] == "tear_down"
    bundle = json.loads((evidence / summary["evals"][0]["evidence"]).read_text(encoding="utf-8"))
    assert bundle["status"] == "PASS"
    assert any(span["name"] == "agent.turn" for span in bundle["spans"])
    assert bundle["logs"]
    assert "status: PASS" in completed.stdout


def test_runtime_judge_process_skips_without_credentials(tmp_path: Path) -> None:
    env = os.environ.copy()
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        env.pop(name, None)
    for name in ("AWS_REGION", "AGENTCORE_RUNTIME_ARN", "AGENTCORE_SPAN_LOG_GROUP"):
        env[name] = ""
    evidence = tmp_path / "judge"
    completed = _run_judge(evidence, "--harness", "runtime", env=env)
    assert completed.returncode == 0, completed.stderr
    summary = json.loads((evidence / "verdict.json").read_text(encoding="utf-8"))
    assert summary["status"] == "SKIPPED"
    assert summary["evals"] == []
    assert "PASS" not in summary["status"]
