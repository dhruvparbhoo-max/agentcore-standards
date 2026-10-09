"""``framework: harness``. Config only: AgentCore runs the loop, we call ``InvokeHarness``.

The managed harness has no pause hook a pattern can answer, so a pattern that
lists risky tools cannot choose it. ``build_agent`` refuses that config before
any call is made.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any, Protocol

from agentcore_agent.frameworks.base import LoopOutcome, ToolSpec, UnsupportedFramework


class HarnessClient(Protocol):
    def invoke_harness(self, **kwargs: Any) -> Mapping[str, Any]:
        """The boto3 ``bedrock-agentcore`` call."""


class HarnessLoop:
    framework = "harness"

    def __init__(
        self,
        *,
        client: HarnessClient,
        harness_arn: str,
        tools: Sequence[ToolSpec] = (),
        actor_id: str = "",
        max_steps: int | None = None,
        timeout_s: int | None = None,
    ) -> None:
        risky = [tool.name for tool in tools if tool.risky]
        if risky:
            raise UnsupportedFramework(f"framework harness cannot pause for approval; risky tools: {risky}")
        if not harness_arn:
            raise UnsupportedFramework("framework harness needs the deployed harness ARN")
        self._client = client
        self._arn = harness_arn
        self._actor_id = actor_id
        self._max_steps = max_steps
        self._timeout_s = timeout_s

    def invoke(self, prompt: str, *, thread_id: str) -> LoopOutcome:
        text = "".join(self.stream(prompt, thread_id=thread_id))
        return LoopOutcome(status="completed", text=text.strip())

    def resume(self, *, approved: bool, message: str, thread_id: str) -> LoopOutcome:
        raise UnsupportedFramework("framework harness never pauses, so there is nothing to resume")

    def stream(self, prompt: str, *, thread_id: str) -> Iterator[str]:
        request: dict[str, Any] = {
            "harnessArn": self._arn,
            "runtimeSessionId": thread_id,
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
        }
        if self._actor_id:
            request["actorId"] = self._actor_id
        if self._max_steps is not None:
            request["maxIterations"] = self._max_steps
        if self._timeout_s is not None:
            request["timeoutSeconds"] = self._timeout_s
        response = self._client.invoke_harness(**request)
        for event in response.get("stream", ()):
            for key in ("internalServerException", "validationException", "runtimeClientError"):
                if key in event:
                    raise RuntimeError(f"harness {key}: {event[key].get('message', '')}")
            delta = event.get("contentBlockDelta", {}).get("delta", {})
            text = delta.get("text")
            if isinstance(text, str) and text:
                yield text
