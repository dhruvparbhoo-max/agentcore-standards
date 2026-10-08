"""Eval harness at the AgentCore Runtime boundary.

``RuntimeHarness`` is the thin client interface every product entrypoint implements
for evals: ``start``, ``invoke``, ``capture_traces``, ``tear_down``.

``BedrockAgentCoreApp`` is the server process AgentCore Runtime hosts. It is not
this harness. ``InMemoryRuntimeHarness`` calls that entrypoint in-process.
``AgentCoreRuntimeHarness`` calls the Runtime service (``InvokeAgentRuntime``).

The eval pack (golden datasets, guardrail fixtures, groundedness, HITL, and the
optional Evaluators adapter) sits on that harness. ``run_eval`` / ``run_suite``
remain the ship gate. Offline stand-ins (``PatternGuard``, ``BusinessStub``,
``LexicalGroundednessScorer``, ``InMemoryHitlGate``) stay in their modules.
They are not ``agentcore-guardrails``, Memory, or the human-in-the-loop template.
"""

from typing import Any

from agentcore_eval.dataset_adapter import HarnessAgentInvoker, load_on_demand_runner
from agentcore_eval.evaluators import (
    DEFAULT_EVALUATOR_IDS,
    EvaluatorsConfigError,
    OnDemandEvaluatorsAdapter,
)
from agentcore_eval.golden import GoldenDataset, dataset_evals, load_golden_dataset
from agentcore_eval.groundedness import (
    assert_groundedness,
    load_groundedness_pack,
)
from agentcore_eval.guardrails import (
    assert_guardrail,
    load_guardrail_fixtures,
)
from agentcore_eval.harness import (
    HarnessError,
    InvokeResult,
    RuntimeConfigError,
    RuntimeHarness,
    SessionClosed,
    SessionHandle,
    SpanRecord,
    TraceBundle,
)
from agentcore_eval.hitl import (
    ApprovalStatus,
    assert_approval_expired,
    assert_blocked_without_approval,
    assert_proceeds_with_approval,
)
from agentcore_eval.in_memory import InMemoryRuntimeHarness, TurnHandler
from agentcore_eval.judge import judge_suite
from agentcore_eval.model import Eval, EvalContext
from agentcore_eval.runner import load_evals, run_eval, run_suite
from agentcore_eval.runtime_client import AgentCoreRuntimeHarness, missing_runtime_settings
from agentcore_eval.suites import pack_suite_dir
from agentcore_eval.verdict import Report, Verdict, VerdictStatus

_STAND_INS = {
    "BusinessStub": "agentcore_eval.stub_agent",
    "GroundednessScorer": "agentcore_eval.groundedness",
    "GuardrailCheck": "agentcore_eval.guardrails",
    "HitlGate": "agentcore_eval.hitl",
    "InMemoryHitlGate": "agentcore_eval.hitl",
    "LexicalGroundednessScorer": "agentcore_eval.groundedness",
    "PatternGuard": "agentcore_eval.guardrails",
    "business_harness": "agentcore_eval.stub_agent",
}


def __getattr__(name: str) -> Any:
    """Refuse product-shaped imports of the offline stand-ins."""
    module = _STAND_INS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    raise ImportError(
        f"{name} is an offline eval stand-in in {module}. "
        "It is not agentcore-guardrails, agentcore-memory, or templates/human-in-the-loop. "
        "Import it from that module only inside the eval pack."
    )


__all__ = [
    "DEFAULT_EVALUATOR_IDS",
    "AgentCoreRuntimeHarness",
    "ApprovalStatus",
    "Eval",
    "EvalContext",
    "EvaluatorsConfigError",
    "GoldenDataset",
    "HarnessAgentInvoker",
    "HarnessError",
    "InMemoryRuntimeHarness",
    "InvokeResult",
    "OnDemandEvaluatorsAdapter",
    "Report",
    "RuntimeConfigError",
    "RuntimeHarness",
    "SessionClosed",
    "SessionHandle",
    "SpanRecord",
    "TraceBundle",
    "TurnHandler",
    "Verdict",
    "VerdictStatus",
    "assert_approval_expired",
    "assert_blocked_without_approval",
    "assert_groundedness",
    "assert_guardrail",
    "assert_proceeds_with_approval",
    "dataset_evals",
    "judge_suite",
    "load_evals",
    "load_golden_dataset",
    "load_groundedness_pack",
    "load_guardrail_fixtures",
    "load_on_demand_runner",
    "missing_runtime_settings",
    "pack_suite_dir",
    "run_eval",
    "run_suite",
]
