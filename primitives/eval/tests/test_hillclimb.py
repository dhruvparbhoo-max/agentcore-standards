"""Dataset tags, the climb filter, and the evidence diff. No Runtime calls."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from agentcore_eval import Eval, InMemoryRuntimeHarness, RuntimeHarness, VerdictStatus, load_evals
from agentcore_eval.evidence import write_evidence
from agentcore_eval.harness import TraceBundle
from agentcore_eval.hillclimb import (
    STEPS,
    audit_dataset,
    compare_evidence,
    main,
    run_tagged,
    select_evals,
)
from agentcore_eval.tags import BehaviorTag, DatasetTags, SplitTag
from agentcore_eval.verdict import Verdict

_REPO = Path(__file__).resolve().parents[3]


def _tags(
    behavior: BehaviorTag = BehaviorTag.CAPABILITY,
    split: SplitTag = SplitTag.OPTIMIZATION,
    categories: tuple[str, ...] = ("tool_selection",),
) -> DatasetTags:
    return DatasetTags(behavior=behavior, split=split, categories=categories)


def _eval(name: str, tags: DatasetTags | None) -> Eval:
    def act(harness: RuntimeHarness, ctx: Any) -> None:
        del harness, ctx

    def assert_(harness: RuntimeHarness, ctx: Any) -> None:
        del harness, ctx

    return Eval(name=name, rubric="climb case", act=act, assert_=assert_, tags=tags)


def _write(directory: Path, name: str, status: VerdictStatus, tags: DatasetTags | None) -> Path:
    verdict = Verdict(
        status=status,
        eval_name=name,
        agent_version="0.1.0",
        notes=(),
        failures=() if status is not VerdictStatus.FAIL else ("broke",),
        evidence_path=None,
        tags=tags,
    )
    return write_evidence(directory, verdict, TraceBundle(session_id="sess", spans=(), logs=()))


def test_dataset_tags_reject_bad_shapes() -> None:
    with pytest.raises(ValueError, match="category"):
        DatasetTags(behavior=BehaviorTag.CAPABILITY, split=SplitTag.OPTIMIZATION, categories=())
    with pytest.raises(ValueError, match="slug"):
        DatasetTags(
            behavior=BehaviorTag.CAPABILITY,
            split=SplitTag.OPTIMIZATION,
            categories=("Tool Selection",),
        )
    with pytest.raises(ValueError, match="sequence"):
        DatasetTags(
            behavior=BehaviorTag.CAPABILITY,
            split=SplitTag.OPTIMIZATION,
            categories="tool_selection",  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="unique"):
        DatasetTags(
            behavior=BehaviorTag.REGRESSION,
            split=SplitTag.HOLDOUT,
            categories=("tool_selection", "tool_selection"),
        )
    tags = DatasetTags(
        behavior=BehaviorTag.CAPABILITY,
        split=SplitTag.HOLDOUT,
        categories=("followup_quality", "tool_selection"),
    )
    assert tags.categories == ("followup_quality", "tool_selection")
    with pytest.raises(ValueError, match="DatasetTags"):
        _eval("tool.bad", "not-tags")  # type: ignore[arg-type]


def test_select_skips_untagged_and_audit_requires_both_splits() -> None:
    tagged = (
        _eval("ship.gate", None),
        _eval("tool.opt", _tags()),
        _eval("tool.hold", _tags(split=SplitTag.HOLDOUT)),
        _eval("tool.keep", _tags(behavior=BehaviorTag.REGRESSION, split=SplitTag.HOLDOUT)),
    )
    optimization = select_evals(tagged, split=SplitTag.OPTIMIZATION)
    assert [item.name for item in optimization] == ["tool.opt"]
    regressions = select_evals(tagged, behavior=BehaviorTag.REGRESSION)
    assert [item.name for item in regressions] == ["tool.keep"]
    assert audit_dataset(tagged) == ()
    assert audit_dataset((_eval("ship.gate", None),)) == ()
    one_sided = (_eval("tool.only", _tags()),)
    assert audit_dataset(one_sided) == ("tool_selection: no holdout case",)


def test_run_tagged_writes_tags_and_skips_the_golden_eval(tmp_path: Path) -> None:
    module = tmp_path / "climb_eval.py"
    module.write_text(
        "from agentcore_eval import Eval\n"
        "from agentcore_eval.tags import BehaviorTag, DatasetTags, SplitTag\n"
        "def _act(harness, ctx):\n"
        "    ctx.session = harness.start(actor_id='actor-a', agent_version=ctx.agent_version)\n"
        "    ctx.results.append(harness.invoke(ctx.session, {'prompt': 'ping'}))\n"
        "def _assert(harness, ctx):\n"
        "    assert ctx.results[0].output['echo'] == 'ping'\n"
        "EVALS = (\n"
        "    Eval(name='tool.opt', rubric='opt', act=_act, assert_=_assert,\n"
        "         tags=DatasetTags(behavior=BehaviorTag.CAPABILITY, split=SplitTag.OPTIMIZATION,\n"
        "                          categories=('tool_selection',))),\n"
        "    Eval(name='tool.hold', rubric='hold', act=_act, assert_=_assert,\n"
        "         tags=DatasetTags(behavior=BehaviorTag.REGRESSION, split=SplitTag.HOLDOUT,\n"
        "                          categories=('tool_selection',))),\n"
        "    Eval(name='ship.untagged', rubric='gate', act=_act, assert_=_assert),\n"
        ")\n",
        encoding="utf-8",
    )

    def handler(
        payload: Mapping[str, Any],
        *,
        session_id: str,
        actor_id: str,
        agent_version: str,
    ) -> Mapping[str, Any]:
        del session_id, actor_id, agent_version
        return {"echo": payload["prompt"]}

    report = run_tagged(
        module,
        harness_factory=lambda: InMemoryRuntimeHarness(handler),
        agent_version="0.1.0",
        evidence_dir=tmp_path / "evidence",
        split=SplitTag.OPTIMIZATION,
    )
    assert [item.eval_name for item in report.verdicts] == ["tool.opt"]
    assert report.verdicts[0].status is VerdictStatus.PASS
    body = json.loads((tmp_path / "evidence" / "tool.opt.json").read_text(encoding="utf-8"))
    assert body["behavior"] == "capability"
    assert body["split"] == "optimization"
    assert body["categories"] == ["tool_selection"]
    assert "ship.untagged.json" not in {path.name for path in (tmp_path / "evidence").iterdir()}

    golden = _REPO / "patterns" / "minimal-agent" / "evals" / "golden_turn.py"
    loaded = load_evals(golden)
    assert loaded[0].name == "minimal-agent.golden-turn"
    assert loaded[0].tags is None
    with pytest.raises(ValueError, match="no tagged evals"):
        run_tagged(
            golden,
            harness_factory=lambda: InMemoryRuntimeHarness(handler),
            agent_version="0.1.0",
            evidence_dir=tmp_path / "golden",
        )


def test_untagged_evidence_keeps_the_original_keys(tmp_path: Path) -> None:
    path = _write(tmp_path, "unit.pass", VerdictStatus.PASS, None)
    body = json.loads(path.read_text(encoding="utf-8"))
    assert set(body) == {"agent_version", "eval", "failures", "logs", "notes", "spans", "status"}


def test_compare_blocks_regressions_missing_cases_and_tag_drift(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    opt = _tags()
    hold = _tags(behavior=BehaviorTag.REGRESSION, split=SplitTag.HOLDOUT)
    _write(baseline, "tool.gain", VerdictStatus.FAIL, opt)
    _write(candidate, "tool.gain", VerdictStatus.PASS, opt)
    _write(baseline, "tool.broke", VerdictStatus.PASS, hold)
    _write(candidate, "tool.broke", VerdictStatus.FAIL, hold)
    _write(baseline, "tool.gone", VerdictStatus.PASS, opt)
    _write(candidate, "tool.new", VerdictStatus.PASS, opt)

    diff = compare_evidence(baseline, candidate)
    assert diff.blocked
    kinds = {item.eval_name: item.kind for item in diff.deltas}
    assert kinds["tool.gain"] == "gain"
    assert kinds["tool.broke"] == "regression"
    assert kinds["tool.gone"] == "missing"
    assert kinds["tool.new"] == "unbaselined"
    text = diff.format()
    assert "This diff is not a Runtime ship verdict." in text
    assert main(["compare", "--baseline", str(baseline), "--candidate", str(candidate)]) == 1

    drifted = tmp_path / "drifted"
    retagged = _tags(behavior=BehaviorTag.REGRESSION)
    _write(baseline, "tool.gain", VerdictStatus.PASS, opt)
    _write(drifted, "tool.gain", VerdictStatus.PASS, retagged)
    _write(drifted, "tool.broke", VerdictStatus.PASS, hold)
    _write(drifted, "tool.gone", VerdictStatus.PASS, opt)
    drift = compare_evidence(baseline, drifted)
    assert drift.blocked
    assert any(item.kind == "tag_drift" for item in drift.deltas)


def test_clear_diff_is_not_a_ship_verdict(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    tags = _tags(split=SplitTag.HOLDOUT)
    _write(baseline, "tool.hold", VerdictStatus.PASS, tags)
    _write(candidate, "tool.hold", VerdictStatus.PASS_NOTES, tags)
    diff = compare_evidence(baseline, candidate)
    assert not diff.blocked
    assert diff.deltas[0].kind == "note"
    text = diff.format()
    assert "climb diff: clear" in text
    assert "gains: 0" in text
    assert "not a Runtime ship verdict" in text
    assert main(["compare", "--baseline", str(baseline), "--candidate", str(candidate)]) == 0


def test_steps_lists_the_rhythm_in_order() -> None:
    markers = [
        "1. Source",
        "2. Tag",
        "3. Split",
        "4. Baseline",
        "5. One harness change",
        "6. Validate regressions",
        "7. Human review",
        "8. Promote or prune",
        "Flywheel",
    ]
    positions = [STEPS.index(marker) for marker in markers]
    assert positions == sorted(positions)
    assert "optimization" in STEPS and "holdout" in STEPS
    assert "capability" in STEPS and "regression" in STEPS
    assert "not a ship verdict" in STEPS
    assert main(["steps"]) == 0


def test_filter_and_audit_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    module = tmp_path / "tagged.py"
    module.write_text(
        "from agentcore_eval import Eval\n"
        "from agentcore_eval.tags import BehaviorTag, DatasetTags, SplitTag\n"
        "def _act(harness, ctx):\n"
        "    return None\n"
        "def _assert(harness, ctx):\n"
        "    return None\n"
        "EVALS = (\n"
        "    Eval(name='tool.opt', rubric='opt', act=_act, assert_=_assert,\n"
        "         tags=DatasetTags(behavior=BehaviorTag.CAPABILITY, split=SplitTag.OPTIMIZATION,\n"
        "                          categories=('tool_selection',))),\n"
        "    Eval(name='tool.hold', rubric='hold', act=_act, assert_=_assert,\n"
        "         tags=DatasetTags(behavior=BehaviorTag.REGRESSION, split=SplitTag.HOLDOUT,\n"
        "                          categories=('tool_selection',))),\n"
        ")\n",
        encoding="utf-8",
    )
    assert main(["audit", "--suite", str(module)]) == 0
    assert main(["filter", "--suite", str(module), "--split", "holdout"]) == 0
    listed = capsys.readouterr().out
    assert "tool.hold\tregression\tholdout\ttool_selection" in listed
    assert main(["filter", "--suite", str(module), "--category", "missing_topic"]) == 1
