"""Independent judge process for a RuntimeHarness suite.

The author test and this module are different entrypoints. A judge re-runs the
suite in its own process, records ``start`` / ``invoke`` / ``capture_traces`` /
``tear_down``, and writes evidence. PASS and PASS+NOTES are the only ship
verdicts. SKIPPED means the real Runtime settings were absent, so no verdict
was claimed.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from agentcore_eval.harness import (
    InvokeResult,
    RuntimeHarness,
    SessionHandle,
    TraceBundle,
    assert_no_resource_arn,
)
from agentcore_eval.runner import run_suite
from agentcore_eval.runtime_client import missing_runtime_settings
from agentcore_eval.verdict import Report, VerdictStatus

PASS_STATUSES = frozenset({VerdictStatus.PASS.value, VerdictStatus.PASS_NOTES.value, "SKIPPED"})


class JudgeOutcome:
    """Roll-up written to ``verdict.json`` plus the per-eval evidence files."""

    def __init__(
        self,
        *,
        status: str,
        harness_name: str,
        evidence_dir: Path,
        summary_path: Path,
        report: Report | None,
    ) -> None:
        self.status = status
        self.harness_name = harness_name
        self.evidence_dir = evidence_dir
        self.summary_path = summary_path
        self.report = report


class RecordingHarness:
    """Delegates to a harness and records the lifecycle call order."""

    def __init__(self, inner: RuntimeHarness) -> None:
        self._inner = inner
        self.calls: list[str] = []

    def start(
        self,
        *,
        actor_id: str,
        agent_version: str,
        session_id: str | None = None,
    ) -> SessionHandle:
        self.calls.append("start")
        return self._inner.start(actor_id=actor_id, agent_version=agent_version, session_id=session_id)

    def invoke(self, session: SessionHandle, payload: Mapping[str, Any]) -> InvokeResult:
        self.calls.append("invoke")
        return self._inner.invoke(session, payload)

    def capture_traces(self, session: SessionHandle) -> TraceBundle:
        self.calls.append("capture_traces")
        return self._inner.capture_traces(session)

    def tear_down(self, session: SessionHandle) -> None:
        self.calls.append("tear_down")
        self._inner.tear_down(session)


def judge_suite(
    *,
    suite: Path,
    agent_version: str,
    harness_factory: Callable[[], RuntimeHarness],
    evidence_dir: Path,
    harness_name: str,
) -> JudgeOutcome:
    """Re-run ``suite`` and write ``verdict.json`` under ``evidence_dir``."""
    recorded: list[RecordingHarness] = []

    def factory() -> RuntimeHarness:
        harness = RecordingHarness(harness_factory())
        recorded.append(harness)
        return harness

    report = run_suite(
        suite,
        harness_factory=factory,
        agent_version=agent_version,
        evidence_dir=evidence_dir,
    )
    status = _rollup(report)
    evals: list[dict[str, Any]] = []
    for index, verdict in enumerate(report.verdicts):
        lifecycle = recorded[index].calls if index < len(recorded) else []
        evidence = None if verdict.evidence_path is None else verdict.evidence_path.name
        evals.append(
            {
                "evidence": evidence,
                "failures": list(verdict.failures),
                "lifecycle": lifecycle,
                "name": verdict.eval_name,
                "notes": list(verdict.notes),
                "status": verdict.status.value,
            }
        )
    summary_path = _write_summary(
        evidence_dir,
        {
            "agent_version": agent_version,
            "evals": evals,
            "harness": harness_name,
            "missing_settings": [],
            "status": status,
            "suite": str(suite),
        },
    )
    return JudgeOutcome(
        status=status,
        harness_name=harness_name,
        evidence_dir=evidence_dir,
        summary_path=summary_path,
        report=report,
    )


def skip_unconfigured_runtime(*, evidence_dir: Path, suite: Path, agent_version: str) -> JudgeOutcome:
    """Record SKIPPED when real Runtime settings are missing. This is not a PASS."""
    missing = missing_runtime_settings()
    summary_path = _write_summary(
        evidence_dir,
        {
            "agent_version": agent_version,
            "evals": [],
            "harness": "runtime",
            "missing_settings": list(missing),
            "status": "SKIPPED",
            "suite": str(suite),
        },
    )
    return JudgeOutcome(
        status="SKIPPED",
        harness_name="runtime",
        evidence_dir=evidence_dir,
        summary_path=summary_path,
        report=None,
    )


def load_harness_factory(spec: str) -> Callable[[], RuntimeHarness]:
    """Load ``module:Callable`` or ``module:Type.classmethod``."""
    module_name, separator, attr_path = spec.partition(":")
    if not separator or not module_name or not attr_path:
        raise ValueError("harness factory must look like module:callable")
    module = importlib.import_module(module_name)
    target: Any = module
    for part in attr_path.split("."):
        target = getattr(target, part)
    if not callable(target):
        raise ValueError(f"{spec} is not callable")
    return cast(Callable[[], RuntimeHarness], target)


def format_outcome(outcome: JudgeOutcome) -> str:
    """One block a judge log can retain next to the evidence directory."""
    lines = [
        f"status: {outcome.status}",
        f"harness: {outcome.harness_name}",
        f"verdict: {outcome.summary_path}",
    ]
    if outcome.report is None:
        return "\n".join(lines)
    for verdict in outcome.report.verdicts:
        evidence = verdict.evidence_path if verdict.evidence_path is not None else ""
        lines.append(f"eval: {verdict.eval_name} {verdict.status.value} {evidence}")
        for failure in verdict.failures:
            lines.append(f"failure: {failure}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Generic judge CLI. Product templates wrap this with a concrete harness."""
    parser = argparse.ArgumentParser(description="Re-run a RuntimeHarness eval suite and write evidence.")
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--agent-version", required=True)
    parser.add_argument("--harness-factory", required=True, help="Import path module:callable")
    parser.add_argument("--harness-name", default="memory")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument(
        "--allow-runtime-skip",
        action="store_true",
        help="When harness-name is runtime and settings are missing, write SKIPPED and exit 0.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.harness_name == "runtime" and args.allow_runtime_skip and missing_runtime_settings():
        outcome = skip_unconfigured_runtime(
            evidence_dir=args.evidence_dir,
            suite=args.suite,
            agent_version=args.agent_version,
        )
    else:
        factory = load_harness_factory(args.harness_factory)
        outcome = judge_suite(
            suite=args.suite,
            agent_version=args.agent_version,
            harness_factory=factory,
            evidence_dir=args.evidence_dir,
            harness_name=args.harness_name,
        )
    print(format_outcome(outcome))
    if outcome.status in PASS_STATUSES:
        return 0
    return 1


def _rollup(report: Report) -> str:
    statuses = [verdict.status for verdict in report.verdicts]
    if any(status is VerdictStatus.FAIL for status in statuses):
        return VerdictStatus.FAIL.value
    if any(status is VerdictStatus.PASS_NOTES for status in statuses):
        return VerdictStatus.PASS_NOTES.value
    return VerdictStatus.PASS.value


def _write_summary(directory: Path, body: Mapping[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    text = json.dumps(body, indent=2, sort_keys=True) + "\n"
    assert_no_resource_arn(text)
    path = directory / "verdict.json"
    path.write_text(text, encoding="utf-8")
    return path


if __name__ == "__main__":
    sys.exit(main())
