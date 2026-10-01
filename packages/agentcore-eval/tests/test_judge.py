"""The judge re-runs a suite and writes a verdict file."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from agentcore_eval import InMemoryRuntimeHarness
from agentcore_eval.judge import judge_suite, load_harness_factory, main, skip_unconfigured_runtime


def _handler(
    payload: Mapping[str, Any],
    *,
    session_id: str,
    actor_id: str,
    agent_version: str,
) -> Mapping[str, Any]:
    del session_id, actor_id, agent_version
    return {"echo": payload["prompt"]}


def _write_suite(directory: Path, *, fail: bool) -> Path:
    directory.mkdir(parents=True)
    assertion = "raise AssertionError('missing outcome')" if fail else "assert ctx.results[0].output['echo'] == 'ping'"
    (directory / "sample.py").write_text(
        "from agentcore_eval import Eval\n"
        "def setup(harness, ctx):\n"
        "    ctx.session = harness.start(actor_id='actor-a', agent_version=ctx.agent_version)\n"
        "def act(harness, ctx):\n"
        "    ctx.results.append(harness.invoke(ctx.session, {'prompt': 'ping'}))\n"
        "def check(harness, ctx):\n"
        f"    {assertion}\n"
        "EVAL = Eval(name='judge.sample', rubric='echoes', setup=setup, act=act, assert_=check)\n",
        encoding="utf-8",
    )
    return directory


def test_judge_suite_records_lifecycle_and_pass(tmp_path: Path) -> None:
    suite = _write_suite(tmp_path / "suite", fail=False)
    evidence = tmp_path / "evidence"
    outcome = judge_suite(
        suite=suite,
        agent_version="0.1.0",
        harness_factory=lambda: InMemoryRuntimeHarness(_handler),
        evidence_dir=evidence,
        harness_name="memory",
    )
    assert outcome.status == "PASS"
    summary = json.loads(outcome.summary_path.read_text(encoding="utf-8"))
    lifecycle = summary["evals"][0]["lifecycle"]
    assert lifecycle[0] == "start"
    assert "invoke" in lifecycle
    assert "capture_traces" in lifecycle
    assert lifecycle[-1] == "tear_down"
    assert lifecycle.index("invoke") < lifecycle.index("capture_traces") < lifecycle.index("tear_down")
    evidence_file = evidence / summary["evals"][0]["evidence"]
    assert evidence_file.exists()
    assert json.loads(evidence_file.read_text(encoding="utf-8"))["status"] == "PASS"


def test_judge_suite_fail_is_not_a_ship_verdict(tmp_path: Path) -> None:
    suite = _write_suite(tmp_path / "suite", fail=True)
    outcome = judge_suite(
        suite=suite,
        agent_version="0.1.0",
        harness_factory=lambda: InMemoryRuntimeHarness(_handler),
        evidence_dir=tmp_path / "evidence",
        harness_name="memory",
    )
    assert outcome.status == "FAIL"
    bundle = json.loads((tmp_path / "evidence" / "judge.sample.json").read_text(encoding="utf-8"))
    assert bundle["status"] == "FAIL"
    assert bundle["failures"]


def test_cli_exit_code_matches_the_verdict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    factory_dir = tmp_path / "factories"
    factory_dir.mkdir()
    (factory_dir / "demo_factory.py").write_text(
        "from collections.abc import Mapping\n"
        "from typing import Any\n"
        "from agentcore_eval import InMemoryRuntimeHarness\n"
        "def handler(payload: Mapping[str, Any], *, session_id: str, actor_id: str, agent_version: str):\n"
        "    return {'echo': payload['prompt']}\n"
        "def factory():\n"
        "    return InMemoryRuntimeHarness(handler)\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(factory_dir))
    passing = _write_suite(tmp_path / "pass-suite", fail=False)
    failing = _write_suite(tmp_path / "fail-suite", fail=True)
    assert _cli(passing, tmp_path / "pass-evidence") == 0
    assert _cli(failing, tmp_path / "fail-evidence") == 1


def _cli(suite: Path, evidence: Path) -> int:
    return main(
        [
            "--suite",
            str(suite),
            "--agent-version",
            "0.1.0",
            "--harness-factory",
            "demo_factory:factory",
            "--harness-name",
            "memory",
            "--evidence-dir",
            str(evidence),
        ]
    )


def test_runtime_skip_does_not_claim_pass(tmp_path: Path, monkeypatch: Any) -> None:
    for name in ("AWS_ACCESS_KEY_ID", "AWS_REGION", "AGENTCORE_RUNTIME_ARN", "AGENTCORE_SPAN_LOG_GROUP"):
        monkeypatch.delenv(name, raising=False)
    outcome = skip_unconfigured_runtime(evidence_dir=tmp_path / "evidence", suite=tmp_path, agent_version="0.1.0")
    summary = json.loads(outcome.summary_path.read_text(encoding="utf-8"))
    assert outcome.status == "SKIPPED"
    assert summary["status"] == "SKIPPED"
    assert "AWS_ACCESS_KEY_ID" in summary["missing_settings"]
    assert summary["evals"] == []


def test_load_harness_factory_rejects_a_bad_spec() -> None:
    try:
        load_harness_factory("not-a-spec")
    except ValueError as exc:
        assert "module:callable" in str(exc)
    else:
        raise AssertionError("bad factory spec must fail")
