"""Hill-climbing loop over tagged evals.

The command prints the operating rhythm and diffs two evidence directories.
It does not call AgentCore Runtime and it does not emit a ship verdict.

    uv run python -m agentcore_eval.hillclimb steps
    uv run python -m agentcore_eval.hillclimb audit --suite <dir>
    uv run python -m agentcore_eval.hillclimb filter --suite <dir> --split optimization
    uv run python -m agentcore_eval.hillclimb compare --baseline <dir> --candidate <dir>

Full rhythm: ``docs/evals/hill-climbing.md``.
"""

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from agentcore_eval.harness import RuntimeHarness
from agentcore_eval.model import Eval
from agentcore_eval.runner import load_evals, run_eval
from agentcore_eval.tags import BehaviorTag, SplitTag
from agentcore_eval.verdict import Report, VerdictStatus

_PASSING = frozenset({VerdictStatus.PASS.value, VerdictStatus.PASS_NOTES.value})
_STATUSES = frozenset(item.value for item in VerdictStatus)

STEPS = """\
Hill-climbing rhythm (structure only — this command does not run Runtime)

1. Source
   Hand-write a case, adapt an external task, or mine a redacted production
   trace. Traces come from RuntimeHarness.capture_traces (and, on the service,
   the span log group named by AGENTCORE_SPAN_LOG_GROUP). Do not commit
   resource identifiers, account ids, or secrets. evidence/ is gitignored.

2. Tag
   Attach DatasetTags: behavior capability|regression, split
   optimization|holdout, and at least one topic slug. Ship-gate evals such as
   minimal-agent.golden-turn stay untagged and keep using run_suite.

3. Split
   Every topic that appears in the optimization set also needs a holdout case.
   Do not read holdout traces while you edit. If you do, move that case to
   optimization and pick a new holdout.
   uv run python -m agentcore_eval.hillclimb audit --suite <suite>
   uv run python -m agentcore_eval.hillclimb filter --suite <suite> --split optimization
   uv run python -m agentcore_eval.hillclimb filter --suite <suite> --split holdout
   uv run python -m agentcore_eval.hillclimb filter --suite <suite> --behavior regression

4. Baseline
   Run the current agent version on both splits before the edit. Write evidence
   under evidence/baseline/ (gitignored). One harness concern per candidate.

   from pathlib import Path
   from agentcore_eval.hillclimb import run_tagged
   from agentcore_eval.tags import SplitTag
   run_tagged(
       Path("<suite>"),
       harness_factory=harness_factory,
       agent_version="<version>",
       evidence_dir=Path("evidence/baseline"),
       split=SplitTag.OPTIMIZATION,
   )
   Repeat with SplitTag.HOLDOUT. Use the same harness_factory you pass to
   run_suite. On the service that factory is AgentCoreRuntimeHarness.from_env
   after the Runtime settings are present.

5. One harness change
   Edit one concern (an instruction, a tool description, or the pair that only
   works together). Re-run both splits to evidence/candidate/.

6. Validate regressions
   uv run python -m agentcore_eval.hillclimb compare \\
     --baseline evidence/baseline --candidate evidence/candidate
   A previously passing case that fails blocks the diff. A missing case blocks
   the diff. Exit 0 means the structure check found no regression. It is not
   PASS and it is not a ship verdict.

7. Human review
   Read the gains, the holdout, and the traces. Reject a change that only
   makes sense for the optimization examples, or that games the assert.

8. Promote or prune
   Promote only after that review and an independent judge re-runs the Runtime
   path (a different process from the author). The Runtime command in this
   repo is: uv run pytest -m runtime
   It skips when AWS settings are unset. A skip is not PASS.
   Prune a saturated or obsolete case in its own dataset change, then take a
   new baseline. Do not delete a failing case to make compare exit 0.

Flywheel
   A production failure or a user correction becomes the next sourced case:
   more traces, more tagged cases, a tighter harness, more traces. Retag a
   case from capability to regression only after a later baseline still passes,
   and do that retag as a dataset change.
"""


class EvidenceCase:
    """Status and tags read back from one evidence JSON file."""

    def __init__(
        self,
        *,
        eval_name: str,
        status: str,
        behavior: str | None,
        split: str | None,
        categories: tuple[str, ...],
    ) -> None:
        self.eval_name = eval_name
        self.status = status
        self.behavior = behavior
        self.split = split
        self.categories = categories


class CaseDelta:
    """One eval's baseline status against the candidate."""

    def __init__(self, *, eval_name: str, kind: str, detail: str) -> None:
        self.eval_name = eval_name
        self.kind = kind
        self.detail = detail


class ClimbDiff:
    """Structure check between two evidence trees. Not a ship verdict."""

    def __init__(self, *, deltas: tuple[CaseDelta, ...], blocked: bool, reasons: tuple[str, ...]) -> None:
        self.deltas = deltas
        self.blocked = blocked
        self.reasons = reasons

    def format(self) -> str:
        lines = ["climb diff: blocked" if self.blocked else "climb diff: clear"]
        for kind in ("regression", "missing", "tag_drift", "gain", "note", "unbaselined", "unchanged"):
            group = [item for item in self.deltas if item.kind == kind]
            if not group:
                continue
            lines.append(f"{kind}:")
            for item in group:
                lines.append(f"  - {item.eval_name}: {item.detail}")
        if self.reasons:
            lines.append("blocked because:")
            for reason in self.reasons:
                lines.append(f"  - {reason}")
        gains = sum(1 for item in self.deltas if item.kind == "gain")
        lines.append(f"gains: {gains}")
        if gains == 0:
            lines.append("a zero-gain diff is not a climb; human review decides if a neutral change is worth keeping.")
        lines.append("This diff is not a Runtime ship verdict.")
        lines.append("Promote only after human review and an independent judge PASS or PASS+NOTES.")
        return "\n".join(lines) + "\n"


def select_evals(
    evaluations: Sequence[Eval],
    *,
    split: SplitTag | None = None,
    behavior: BehaviorTag | None = None,
    category: str | None = None,
) -> tuple[Eval, ...]:
    """Return climb cases matching the filters. Untagged ship-gate evals are skipped."""
    found: list[Eval] = []
    for item in evaluations:
        tags = item.tags
        if tags is None:
            continue
        if split is not None and tags.split is not split:
            continue
        if behavior is not None and tags.behavior is not behavior:
            continue
        if category is not None and category not in tags.categories:
            continue
        found.append(item)
    return tuple(found)


def audit_dataset(evaluations: Sequence[Eval]) -> tuple[str, ...]:
    """Return split problems. An empty result means the tagged set is stratified.

    Zero tagged evals is not a problem: ship-gate suites can stay untagged.
    A topic that has one side and not the other is a problem.
    """
    splits_by_category: dict[str, set[SplitTag]] = {}
    for item in evaluations:
        if item.tags is None:
            continue
        for category in item.tags.categories:
            splits_by_category.setdefault(category, set()).add(item.tags.split)
    problems: list[str] = []
    for category in sorted(splits_by_category):
        splits = splits_by_category[category]
        if SplitTag.OPTIMIZATION not in splits:
            problems.append(f"{category}: no optimization case")
        if SplitTag.HOLDOUT not in splits:
            problems.append(f"{category}: no holdout case")
    return tuple(problems)


def run_tagged(
    path: Path,
    *,
    harness_factory: Callable[[], RuntimeHarness],
    agent_version: str,
    evidence_dir: Path,
    split: SplitTag | None = None,
    behavior: BehaviorTag | None = None,
    category: str | None = None,
) -> Report:
    """Run the tagged subset. The caller supplies the same harness ``run_suite`` uses."""
    selected = select_evals(
        load_evals(path),
        split=split,
        behavior=behavior,
        category=category,
    )
    if not selected:
        raise ValueError("no tagged evals matched the climb filter")
    verdicts = tuple(
        run_eval(
            evaluation,
            agent_version=agent_version,
            harness=harness_factory(),
            evidence_dir=evidence_dir,
        )
        for evaluation in selected
    )
    return Report(verdicts)


def load_evidence_tree(directory: Path) -> dict[str, EvidenceCase]:
    """Read evidence JSON under ``directory``. Names must be unique."""
    if not directory.is_dir():
        raise ValueError(f"evidence directory does not exist: {directory}")
    files = sorted(path for path in directory.rglob("*.json") if path.is_file())
    if not files:
        raise ValueError(f"no evidence json in {directory}")
    found: dict[str, EvidenceCase] = {}
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or "eval" not in payload or "status" not in payload:
            raise ValueError(f"{path} is not an evidence bundle")
        case = _case_from_payload(payload, path)
        if case.eval_name in found:
            raise ValueError(f"duplicate eval {case.eval_name} in {directory}")
        found[case.eval_name] = case
    return found


def compare_evidence(baseline_dir: Path, candidate_dir: Path) -> ClimbDiff:
    """Diff two evidence trees. Pass-to-fail and missing cases block promotion."""
    baseline = load_evidence_tree(baseline_dir)
    candidate = load_evidence_tree(candidate_dir)
    deltas: list[CaseDelta] = []
    reasons: list[str] = []
    for name in sorted(set(baseline) | set(candidate)):
        before = baseline.get(name)
        after = candidate.get(name)
        if after is not None and before is None:
            deltas.append(CaseDelta(eval_name=name, kind="unbaselined", detail=after.status))
            continue
        if before is not None and after is None:
            detail = f"missing from candidate (baseline {before.status})"
            deltas.append(CaseDelta(eval_name=name, kind="missing", detail=detail))
            reasons.append(f"{name}: {detail}")
            continue
        if before is None or after is None:
            continue
        drift = _tag_drift(before, after)
        if drift:
            deltas.append(CaseDelta(eval_name=name, kind="tag_drift", detail=drift))
            reasons.append(f"{name}: {drift}")
            continue
        kind, detail = _status_delta(before, after)
        deltas.append(CaseDelta(eval_name=name, kind=kind, detail=detail))
        if kind == "regression":
            reasons.append(f"{name}: {detail}")
    return ClimbDiff(deltas=tuple(deltas), blocked=bool(reasons), reasons=tuple(reasons))


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry. ``steps`` prints the rhythm; ``compare`` diffs evidence."""
    parser = argparse.ArgumentParser(description="Document and check the harness hill-climbing loop.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("steps", help="print the source → promote rhythm")

    audit = sub.add_parser("audit", help="check that each topic has optimization and holdout")
    audit.add_argument("--suite", type=Path, required=True)

    filt = sub.add_parser("filter", help="list tagged evals")
    filt.add_argument("--suite", type=Path, required=True)
    filt.add_argument("--split", type=_split, default=None)
    filt.add_argument("--behavior", type=_behavior, default=None)
    filt.add_argument("--category", default=None)

    compare = sub.add_parser("compare", help="diff baseline evidence against a candidate")
    compare.add_argument("--baseline", type=Path, required=True)
    compare.add_argument("--candidate", type=Path, required=True)

    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return _dispatch(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "steps":
        print(STEPS, end="")
        return 0
    if args.command == "audit":
        problems = audit_dataset(load_evals(args.suite))
        if problems:
            print("\n".join(problems))
            return 1
        print("climb tags ok")
        return 0
    if args.command == "filter":
        matched = select_evals(
            load_evals(args.suite),
            split=args.split,
            behavior=args.behavior,
            category=args.category,
        )
        if not matched:
            print("no tagged evals matched", file=sys.stderr)
            return 1
        for item in matched:
            tags = item.tags
            assert tags is not None
            print(f"{item.name}\t{tags.behavior.value}\t{tags.split.value}\t{','.join(tags.categories)}")
        return 0
    diff = compare_evidence(args.baseline, args.candidate)
    print(diff.format(), end="")
    return 1 if diff.blocked else 0


def _case_from_payload(payload: Mapping[str, Any], path: Path) -> EvidenceCase:
    name = payload["eval"]
    status = payload["status"]
    if not isinstance(name, str) or not name:
        raise ValueError(f"{path} has an empty eval name")
    if not isinstance(status, str) or status not in _STATUSES:
        raise ValueError(f"{path} has unknown status {status!r}")
    behavior = payload.get("behavior")
    split = payload.get("split")
    categories = payload.get("categories", [])
    if behavior is not None and behavior not in {item.value for item in BehaviorTag}:
        raise ValueError(f"{path} has unknown behavior {behavior!r}")
    if split is not None and split not in {item.value for item in SplitTag}:
        raise ValueError(f"{path} has unknown split {split!r}")
    if not isinstance(categories, list):
        raise ValueError(f"{path} categories must be a list of strings")
    slugs: list[str] = []
    for item in categories:
        if not isinstance(item, str):
            raise ValueError(f"{path} categories must be a list of strings")
        slugs.append(item)
    if (behavior is None) != (split is None):
        raise ValueError(f"{path} must set both behavior and split, or neither")
    if behavior is None and slugs:
        raise ValueError(f"{path} categories require behavior and split")
    return EvidenceCase(
        eval_name=name,
        status=status,
        behavior=behavior if isinstance(behavior, str) else None,
        split=split if isinstance(split, str) else None,
        categories=tuple(slugs),
    )


def _tag_drift(before: EvidenceCase, after: EvidenceCase) -> str:
    if before.behavior == after.behavior and before.split == after.split and before.categories == after.categories:
        return ""
    return (
        f"tag drift {before.behavior}/{before.split}/{list(before.categories)} "
        f"-> {after.behavior}/{after.split}/{list(after.categories)}"
    )


def _status_delta(before: EvidenceCase, after: EvidenceCase) -> tuple[str, str]:
    detail = f"{before.status} -> {after.status} ({_role(after)})"
    if before.status in _PASSING and after.status == VerdictStatus.FAIL.value:
        return "regression", detail
    if before.status == VerdictStatus.FAIL.value and after.status in _PASSING:
        return "gain", detail
    if before.status == VerdictStatus.PASS.value and after.status == VerdictStatus.PASS_NOTES.value:
        return "note", detail
    if before.status == VerdictStatus.PASS_NOTES.value and after.status == VerdictStatus.PASS.value:
        return "gain", detail
    return "unchanged", detail


def _role(case: EvidenceCase) -> str:
    behavior = case.behavior or "untagged"
    split = case.split or "untagged"
    topics = ",".join(case.categories) if case.categories else "no-topic"
    return f"{behavior}, {split}, {topics}"


def _split(value: str) -> SplitTag:
    try:
        return SplitTag(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected optimization or holdout") from exc


def _behavior(value: str) -> BehaviorTag:
    try:
        return BehaviorTag(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected capability or regression") from exc


if __name__ == "__main__":
    raise SystemExit(main())
