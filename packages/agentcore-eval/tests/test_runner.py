"""Verdicts, evidence, suite loading, and the dataset-runner adapter."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from agentcore_eval import (
    Eval,
    HarnessAgentInvoker,
    HarnessError,
    InMemoryRuntimeHarness,
    RuntimeHarness,
    SessionClosed,
    VerdictStatus,
    load_evals,
    load_on_demand_runner,
    run_eval,
    run_suite,
)
from agentcore_eval.evidence import write_evidence
from agentcore_eval.harness import TraceBundle
from agentcore_eval.verdict import Verdict


def _handler(
    payload: Mapping[str, Any],
    *,
    session_id: str,
    actor_id: str,
    agent_version: str,
) -> Mapping[str, Any]:
    del session_id, actor_id, agent_version
    return {"echo": payload["prompt"]}


def _passing() -> Eval:
    def setup(harness: RuntimeHarness, ctx: Any) -> None:
        ctx.session = harness.start(actor_id="actor-a", agent_version=ctx.agent_version)

    def act(harness: RuntimeHarness, ctx: Any) -> None:
        ctx.results.append(harness.invoke(ctx.session, {"prompt": "ping"}))

    def assert_(harness: RuntimeHarness, ctx: Any) -> None:
        del harness
        assert ctx.results[0].output["echo"] == "ping"

    return Eval(name="unit.pass", rubric="echoes the prompt", setup=setup, act=act, assert_=assert_)


def test_pass_and_fail_are_verdicts(tmp_path: Path) -> None:
    harness = InMemoryRuntimeHarness(_handler)
    passed = run_eval(_passing(), agent_version="0.1.0", harness=harness, evidence_dir=tmp_path)
    assert passed.status is VerdictStatus.PASS
    assert passed.evidence_path is not None
    assert passed.evidence_path.exists()

    def assert_fail(harness: RuntimeHarness, ctx: Any) -> None:
        del harness, ctx
        raise AssertionError("observable outcome missing")

    failing = Eval(
        name="unit.fail",
        rubric="always fails",
        setup=_passing().setup,
        act=_passing().act,
        assert_=assert_fail,
    )
    failed = run_eval(
        failing,
        agent_version="0.1.0",
        harness=InMemoryRuntimeHarness(_handler),
        evidence_dir=tmp_path,
    )
    assert failed.status is VerdictStatus.FAIL
    assert "observable outcome missing" in failed.failures[0]
    assert failed.evidence_path is not None


def test_notes_become_pass_notes(tmp_path: Path) -> None:
    def setup(harness: RuntimeHarness, ctx: Any) -> None:
        ctx.session = harness.start(actor_id="actor-a", agent_version=ctx.agent_version)

    def act(harness: RuntimeHarness, ctx: Any) -> None:
        del harness
        ctx.notes.append("usd estimate is still zero")

    def assert_(harness: RuntimeHarness, ctx: Any) -> None:
        del harness, ctx

    evaluation = Eval(name="unit.notes", rubric="records a note", setup=setup, act=act, assert_=assert_)
    verdict = run_eval(
        evaluation,
        agent_version="0.1.0",
        harness=InMemoryRuntimeHarness(_handler),
        evidence_dir=tmp_path,
    )
    assert verdict.status is VerdictStatus.PASS_NOTES
    assert verdict.notes == ("usd estimate is still zero",)


def test_load_evals_and_suite(tmp_path: Path) -> None:
    module = tmp_path / "sample_eval.py"
    module.write_text(
        "from agentcore_eval import Eval\n\n"
        "def _act(harness, ctx):\n"
        "    ctx.session = harness.start(actor_id='actor-a', agent_version=ctx.agent_version)\n\n"
        "def _assert(harness, ctx):\n"
        "    return None\n\n"
        "EVAL = Eval(name='loaded.sample', rubric='loads', act=_act, assert_=_assert)\n",
        encoding="utf-8",
    )
    loaded = load_evals(module)
    assert loaded[0].name == "loaded.sample"
    report = run_suite(
        module,
        harness_factory=lambda: InMemoryRuntimeHarness(_handler),
        agent_version="0.1.0",
        evidence_dir=tmp_path / "evidence",
    )
    assert report.ok
    assert report.verdicts[0].status is VerdictStatus.PASS


def test_dataset_adapter_reuses_session_for_one_scenario() -> None:
    def handler(
        payload: Mapping[str, Any],
        *,
        session_id: str,
        actor_id: str,
        agent_version: str,
    ) -> Mapping[str, Any]:
        del actor_id, agent_version
        return {"echo": payload["prompt"], "session_id": session_id}

    harness = InMemoryRuntimeHarness(handler)
    invoker = HarnessAgentInvoker(harness, actor_id="actor-a", agent_version="0.1.0")
    session_id = "scenario-" + ("b" * 24)

    class _Turn:
        def __init__(self, prompt: str) -> None:
            self.payload = {"prompt": prompt}
            self.session_id = session_id

    first = invoker(_Turn("one"))
    second = invoker(_Turn("two"))
    assert first.agent_output["echo"] == "one"
    assert second.agent_output["echo"] == "two"
    assert first.agent_output["session_id"] == second.agent_output["session_id"]
    invoker.close()
    with pytest.raises(SessionClosed):
        invoker(_Turn("three"))


def test_on_demand_runner_symbol_is_importable() -> None:
    runner = load_on_demand_runner()
    assert runner.__name__ == "OnDemandEvaluationDatasetRunner"
    assert callable(runner.run)


def test_evidence_refuses_resource_arns(tmp_path: Path) -> None:
    verdict = Verdict(
        status=VerdictStatus.FAIL,
        eval_name="unit.arn",
        agent_version="0.1.0",
        notes=(),
        failures=(),
        evidence_path=None,
    )
    secret = "arn:" + "aws:iam:::role/example"
    bundle = TraceBundle(session_id="sess", spans=(), logs=({"note": secret},))
    with pytest.raises(HarnessError):
        write_evidence(tmp_path, verdict, bundle)
