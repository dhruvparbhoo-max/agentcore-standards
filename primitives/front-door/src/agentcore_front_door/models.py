"""The one model access layer: capped backoff, the fallback model, and a geographic profile.

Every agent calls the model through here (directly with ``ModelAccess.converse``,
or through the LangChain and Strands adapters in ``agentcore_agent.models``).

- Retryable codes and token usage from the Converse response are copied from
  aws-samples/sample-eval-first-building-enterprise-agents-with-agentcore
  ``evaluators/mtg_eval/shared/llm_client.py`` (MIT-0). The botocore client
  there uses ``mode: adaptive`` retries; here botocore makes one attempt and
  ``agentcore_recovery.run_with_recovery`` owns the backoff, so the attempt and
  elapsed caps and the circuit breaker are the shared ones.
- A ``Retry-After`` the service sends is honoured, up to the delay cap.
- When the primary stops (retries spent or the circuit opens), the fallback
  profile is tried once with its own budget. A fatal error does not fall back.
- ``region_profile: eu`` requires ``eu.`` geographic inference profiles. UK
  workloads in eu-west-2 use the EU profile. A cross-region profile adds
  capacity; it is not failover, which is why the fallback exists.
- Each agent has its own model key: an application inference profile created
  by ``infra/constructs`` (``AgentModelProfile``) and tagged with the team, the
  same idea as Loom's ``loom:group`` tag. Its id arrives in
  ``AGENTCORE_MODEL_PROFILE_ARN``; it is never written in git.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from agentcore_recovery import AttemptOutcome, CircuitBreaker, Clock, RecoveryBudget, run_with_recovery

RETRYABLE_CODES = frozenset(
    {
        "ThrottlingException",
        "TooManyRequestsException",
        "ServiceUnavailableException",
        "ModelNotReadyException",
        "InternalServerException",
        "RequestTimeout",
        "ReadTimeoutError",
        "ConnectTimeoutError",
        "EndpointConnectionError",
    }
)
PROFILE_ENV = "AGENTCORE_MODEL_PROFILE_ARN"
FALLBACK_PROFILE_ENV = "AGENTCORE_FALLBACK_PROFILE_ARN"
GEOGRAPHIES = ("eu", "us", "apac", "global")
_APPLICATION_PROFILE = ":application-inference-profile/"


class ModelRouteError(ValueError):
    """The model section names a profile outside the pattern's geography."""


class ModelUnavailable(Exception):
    """Primary and fallback both stopped. ``code`` is the last error code."""

    def __init__(self, code: str, attempts: int) -> None:
        super().__init__(f"model unavailable after {attempts} attempts: {code}")
        self.code = code
        self.attempts = attempts


@dataclass(frozen=True)
class ModelRoute:
    primary: str
    fallback: str
    region: str
    region_profile: str
    team_tag: str
    max_retries: int = 3

    @classmethod
    def from_pattern(
        cls,
        model: Mapping[str, Any],
        *,
        region: str,
        max_retries: int = 3,
        env: Mapping[str, str] | None = None,
    ) -> ModelRoute:
        source = os.environ if env is None else env
        route = cls(
            primary=source.get(PROFILE_ENV, "").strip() or str(model["primary"]),
            fallback=source.get(FALLBACK_PROFILE_ENV, "").strip() or str(model.get("fallback") or ""),
            region=region,
            region_profile=str(model["region_profile"]),
            team_tag=str(model["team_tag"]),
            max_retries=max_retries,
        )
        route.check()
        return route

    def check(self) -> None:
        if self.region_profile not in GEOGRAPHIES:
            raise ModelRouteError(f"region_profile must be one of {GEOGRAPHIES}")
        for label, model_id in (("primary", self.primary), ("fallback", self.fallback)):
            if not model_id or _APPLICATION_PROFILE in model_id:
                continue
            if not model_id.startswith(f"{self.region_profile}."):
                raise ModelRouteError(
                    f"model.{label} {model_id!r} is not a {self.region_profile} geographic inference profile"
                )
        if self.fallback and self.fallback == self.primary:
            raise ModelRouteError("model.fallback must differ from model.primary")

    @property
    def chain(self) -> tuple[str, ...]:
        return (self.primary, self.fallback) if self.fallback else (self.primary,)


def error_code(exc: BaseException) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, Mapping):
        code = response.get("Error", {}).get("Code")
        if code:
            return str(code)
    return type(exc).__name__


def retryable(exc: BaseException) -> bool:
    return error_code(exc) in RETRYABLE_CODES


def retry_after_ms(exc: BaseException) -> int:
    response = getattr(exc, "response", None)
    if not isinstance(response, Mapping):
        return 0
    headers = response.get("ResponseMetadata", {}).get("HTTPHeaders", {})
    value = headers.get("retry-after") if isinstance(headers, Mapping) else None
    try:
        return max(0, int(float(value) * 1000)) if value is not None else 0
    except (TypeError, ValueError):
        return 0


class WallClock(Clock):
    """Real milliseconds for ``run_with_recovery``. ``hint_ms`` stretches the next sleep to a server wait."""

    def __init__(self, *, cap_ms: int, sleep: Callable[[float], None] = time.sleep) -> None:
        super().__init__(start_ms=int(time.monotonic() * 1000))
        self.cap_ms = cap_ms
        self.hint_ms = 0
        self._sleep = sleep

    def sleep(self, delay_ms: int) -> None:
        wait = min(max(delay_ms, self.hint_ms), self.cap_ms)
        self.hint_ms = 0
        self._sleep(wait / 1000)
        self.now_ms = int(time.monotonic() * 1000)


@dataclass
class UsageTotals:
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""

    def add(self, model: str, usage: Mapping[str, Any]) -> None:
        self.model_calls += 1
        self.input_tokens += int(usage.get("inputTokens", 0) or 0)
        self.output_tokens += int(usage.get("outputTokens", 0) or 0)
        self.model = model

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_calls": self.model_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "model": self.model,
        }


@dataclass
class ModelAccess:
    """Bedrock Converse through the shared recovery loop, primary then fallback."""

    route: ModelRoute
    client: Any = None
    budget: RecoveryBudget = field(
        default_factory=lambda: RecoveryBudget(
            max_attempts=4, max_elapsed_ms=60_000, base_delay_ms=500, max_delay_ms=8_000
        )
    )
    clock: Clock | None = None
    usage: UsageTotals = field(default_factory=UsageTotals)
    circuits: dict[str, CircuitBreaker] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = bedrock_runtime_client(self.route.region)

    def converse(self, **request: Any) -> Mapping[str, Any]:
        """``Converse`` with ``modelId`` filled in from the route. Raises ``ModelUnavailable``."""
        last_code, attempts = "no_model", 0
        for model_id in self.route.chain:
            result, response = self._try(model_id, request)
            attempts += result.attempts
            if result.ok and response is not None:
                self.usage.add(model_id, response.get("usage", {}))
                return response
            last_code = result.code
        raise ModelUnavailable(last_code, attempts)

    def _try(self, model_id: str, request: Mapping[str, Any]) -> tuple[Any, Mapping[str, Any] | None]:
        clock = self.clock or WallClock(cap_ms=self.budget.max_delay_ms)
        circuit = self.circuits.setdefault(model_id, CircuitBreaker(failure_threshold=5, cooldown_ms=30_000))
        box: dict[str, Mapping[str, Any]] = {}
        failure: dict[str, BaseException] = {}

        def attempt() -> AttemptOutcome:
            try:
                box["response"] = self.client.converse(**{**request, "modelId": model_id})
            except Exception as exc:
                failure["error"] = exc
                if isinstance(clock, WallClock):
                    clock.hint_ms = retry_after_ms(exc)
                return AttemptOutcome(ok=False, retryable=retryable(exc), code=error_code(exc))
            return AttemptOutcome(ok=True, retryable=False, code="ok")

        result = run_with_recovery(attempt, budget=self.budget, circuit=circuit, clock=clock)
        if not result.ok and result.stop_reason == "fatal" and "error" in failure:
            raise failure["error"]
        return result, box.get("response")


def bedrock_runtime_client(region: str, *, max_attempts: int = 1) -> Any:
    """A ``bedrock-runtime`` client that leaves retries to the caller."""
    import boto3
    from botocore.config import Config

    config = Config(read_timeout=120, connect_timeout=10, retries={"max_attempts": max_attempts, "mode": "standard"})
    return boto3.client("bedrock-runtime", region_name=region, config=config)


def adaptive_config(max_retries: int) -> Any:
    """botocore config for framework model clients that keep their own retry loop."""
    from botocore.config import Config

    return Config(
        read_timeout=120,
        connect_timeout=10,
        retries={"max_attempts": max(1, max_retries + 1), "mode": "adaptive"},
    )
