"""Golden eval: in-memory by default, real AgentCore Runtime when configured."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from agentcore_eval import AgentCoreRuntimeHarness, VerdictStatus, missing_runtime_settings, run_suite
from agentcore_eval.runtime_client import RUNTIME_ACTOR_HEADER
from agentcore_tracing import hash_session_id
from minimal_agent import AGENT_VERSION, MinimalAgentHarness

_EVALS = Path(__file__).resolve().parents[1] / "evals"
_RUNTIME = pytest.mark.runtime
_MISSING_RUNTIME = bool(missing_runtime_settings())


def test_golden_turn_on_in_memory_harness(tmp_path: Path) -> None:
    report = run_suite(
        _EVALS,
        harness_factory=MinimalAgentHarness,
        agent_version=AGENT_VERSION,
        evidence_dir=tmp_path,
    )
    assert report.ok
    verdict = report.verdicts[0]
    assert verdict.status is VerdictStatus.PASS
    assert verdict.eval_name == "minimal-agent.golden-turn"
    assert verdict.evidence_path is not None
    assert verdict.evidence_path.exists()


def test_golden_turn_passes_on_a_fake_runtime_harness(tmp_path: Path) -> None:
    """The golden contract is satisfiable by AgentCoreRuntimeHarness, not only the in-process one."""
    client = _RuntimeClient()
    report = run_suite(
        _EVALS,
        harness_factory=lambda: MinimalAgentHarness(
            AgentCoreRuntimeHarness(
                runtime_arn=_RUNTIME_ARN,
                region="us-east-1",
                client=client,
                span_collector=_SpanCollector(),
                log_collector=_LogCollector(),
            )
        ),
        agent_version=AGENT_VERSION,
        evidence_dir=tmp_path,
    )
    assert report.ok
    assert report.verdicts[0].status is VerdictStatus.PASS
    assert [item[RUNTIME_ACTOR_HEADER] for item in client.headers] == ["actor-golden", "actor-golden"]
    assert client.stops


@_RUNTIME
@pytest.mark.skipif(
    _MISSING_RUNTIME,
    reason="Set AWS_ACCESS_KEY_ID, AWS_REGION, AGENTCORE_RUNTIME_ARN, and AGENTCORE_SPAN_LOG_GROUP",
)
def test_golden_turn_on_agentcore_runtime(tmp_path: Path) -> None:
    report = run_suite(
        _EVALS,
        harness_factory=MinimalAgentHarness.for_agentcore_runtime,
        agent_version=AGENT_VERSION,
        evidence_dir=tmp_path,
    )
    assert report.ok
    assert report.verdicts[0].status in {VerdictStatus.PASS, VerdictStatus.PASS_NOTES}


_RUNTIME_ARN = "arn:" + "aws:bedrock-agentcore:us-east-1:000000000000:runtime/example"


class _Body:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload


class _RuntimeClient:
    def __init__(self) -> None:
        self.headers: list[Mapping[str, str]] = []
        self.stops: list[Mapping[str, Any]] = []

    def invoke_agent_runtime(self, **kwargs: Any) -> Mapping[str, Any]:
        self.headers.append(dict(kwargs["_agentcore_headers"]))
        prompt = json.loads(kwargs["payload"].decode("utf-8"))["prompt"]
        body = json.dumps({"result": f"pong:{prompt}"}).encode("utf-8")
        return {"contentType": "application/json", "response": _Body(body)}

    def stop_runtime_session(self, **kwargs: Any) -> dict[str, str]:
        self.stops.append(kwargs)
        return {"status": "STOPPED"}


class _SpanCollector:
    def collect(self, session_id: str, start_time: object, end_time: object) -> list[dict[str, Any]]:
        del start_time, end_time
        hashed = hash_session_id(session_id)
        spans: list[dict[str, Any]] = []
        for index in (1, 2):
            spans.append(_adot_span("agent.turn", f"turn-{index}", None, session_id, hashed))
            spans.append(_adot_span("model.invoke", f"model-{index}", f"turn-{index}", session_id, hashed))
        return spans


class _LogCollector:
    def collect(self, session_id: str, start_time: object, end_time: object) -> list[dict[str, Any]]:
        del start_time, end_time
        hashed = hash_session_id(session_id)
        return [
            {
                "actorId": "actor-golden",
                "agentVersion": AGENT_VERSION,
                "errorClass": None,
                "latencyMs": 1.0,
                "requestId": f"request-{index}",
                "runtimeSessionId": hashed,
            }
            for index in (1, 2)
        ]


def _adot_span(name: str, span_id: str, parent: str | None, session_id: str, hashed: str) -> dict[str, Any]:
    return {
        "attributes": [
            {"key": "agent.version", "value": {"stringValue": AGENT_VERSION}},
            {"key": "cost.source", "value": {"stringValue": "length-heuristic"}},
            {"key": "cost.tokens", "value": {"stringValue": "4"}},
            {"key": "cost.usd_estimate", "value": {"intValue": 0}},
            {"key": "runtime.session_id", "value": {"stringValue": hashed}},
            {"key": "session.id", "value": {"stringValue": session_id}},
        ],
        "name": name,
        "parentSpanId": parent,
        "spanId": span_id,
        "status": {"code": 1},
        "traceId": "trace-golden",
    }
