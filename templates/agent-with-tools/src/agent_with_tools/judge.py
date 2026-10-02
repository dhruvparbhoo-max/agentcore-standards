"""Judge process for the invoice desk.

``--harness memory`` installs the scripted model and runs the offline graders.
That pass does not call AgentCore Runtime.

``--harness runtime`` calls InvokeAgentRuntime. Missing settings write
``SKIPPED`` and this process exits 1. SKIPPED is not a ship verdict.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from agentcore_eval import RuntimeHarness
from agentcore_eval.judge import format_outcome, judge_suite, skip_unconfigured_runtime
from agentcore_eval.runtime_client import missing_runtime_settings

from agent_with_tools.agent import build_agent
from agent_with_tools.billing import reset_desk
from agent_with_tools.entrypoint import set_agent_factory
from agent_with_tools.harness import AgentWithToolsHarness
from agent_with_tools.scripted import ScriptedInvoiceModel
from agent_with_tools.version import AGENT_VERSION

_OFFLINE = Path(__file__).resolve().parents[2] / "evals" / "offline"
_RUNTIME = Path(__file__).resolve().parents[2] / "evals" / "runtime"
_SHIP = frozenset({"PASS", "PASS+NOTES"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independent judge for the invoice desk.")
    parser.add_argument("--harness", choices=("memory", "runtime"), default="memory")
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=Path("evidence/judge-tools"),
        help="Directory for verdict.json and per-eval evidence. Created if needed.",
    )
    args = parser.parse_args(argv)
    if args.harness == "runtime" and missing_runtime_settings():
        outcome = skip_unconfigured_runtime(
            evidence_dir=args.evidence_dir,
            suite=_RUNTIME,
            agent_version=AGENT_VERSION,
        )
        print(format_outcome(outcome))
        return 1
    factory: Callable[[], RuntimeHarness]
    if args.harness == "memory":
        reset_desk()
        set_agent_factory(lambda: build_agent(ScriptedInvoiceModel()))
        suite = _OFFLINE
        factory = AgentWithToolsHarness
    else:
        suite = _RUNTIME
        factory = AgentWithToolsHarness.for_agentcore_runtime
    outcome = judge_suite(
        suite=suite,
        agent_version=AGENT_VERSION,
        harness_factory=factory,
        evidence_dir=args.evidence_dir,
        harness_name=args.harness,
    )
    print(format_outcome(outcome))
    if outcome.status in _SHIP:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
