"""Judge process for the minimal-agent golden eval.

Run this in a process that did not author the change:

    PYTHONPATH=templates/minimal-agent/src uv run python -m minimal_agent.judge

``--harness memory`` calls the entrypoint in-process (no AWS credentials).
``--harness runtime`` calls AgentCore Runtime and writes SKIPPED, not PASS,
when the runtime settings are unset.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agentcore_eval.judge import format_outcome, judge_suite, skip_unconfigured_runtime
from agentcore_eval.runtime_client import missing_runtime_settings

from minimal_agent.entrypoint import AGENT_VERSION
from minimal_agent.harness import MinimalAgentHarness

_SUITE = Path(__file__).resolve().parents[2] / "evals"
_PASS = frozenset({"PASS", "PASS+NOTES", "SKIPPED"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independent judge for minimal-agent.golden-turn.")
    parser.add_argument("--harness", choices=("memory", "runtime"), default="memory")
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=Path("evidence/judge"),
        help="Directory for verdict.json and per-eval evidence. Created if needed.",
    )
    args = parser.parse_args(argv)
    if args.harness == "runtime" and missing_runtime_settings():
        outcome = skip_unconfigured_runtime(
            evidence_dir=args.evidence_dir,
            suite=_SUITE,
            agent_version=AGENT_VERSION,
        )
    else:
        factory = MinimalAgentHarness.for_agentcore_runtime if args.harness == "runtime" else MinimalAgentHarness
        outcome = judge_suite(
            suite=_SUITE,
            agent_version=AGENT_VERSION,
            harness_factory=factory,
            evidence_dir=args.evidence_dir,
            harness_name=args.harness,
        )
    print(format_outcome(outcome))
    if outcome.status in _PASS:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
