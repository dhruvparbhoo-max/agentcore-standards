"""Eval harness at the AgentCore Runtime boundary.

``RuntimeHarness`` is the thin client interface every product entrypoint implements
for evals: ``start``, ``invoke``, ``capture_traces``, ``tear_down``.

``BedrockAgentCoreApp`` is the server process AgentCore Runtime hosts. It is not
this harness. ``InMemoryRuntimeHarness`` calls that entrypoint in-process.
``AgentCoreRuntimeHarness`` calls the Runtime service (``InvokeAgentRuntime``).
"""

from agentcore_eval.dataset_adapter import HarnessAgentInvoker, load_on_demand_runner
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
from agentcore_eval.memory import InMemoryRuntimeHarness, TurnHandler
from agentcore_eval.model import Eval, EvalContext
from agentcore_eval.runner import load_evals, run_eval, run_suite
from agentcore_eval.runtime_client import AgentCoreRuntimeHarness
from agentcore_eval.verdict import Report, Verdict, VerdictStatus

__all__ = [
    "AgentCoreRuntimeHarness",
    "Eval",
    "EvalContext",
    "HarnessAgentInvoker",
    "HarnessError",
    "InMemoryRuntimeHarness",
    "InvokeResult",
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
    "load_evals",
    "load_on_demand_runner",
    "run_eval",
    "run_suite",
]
