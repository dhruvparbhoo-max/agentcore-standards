"""Tool registry. Tools stay denied until a Gateway binding's policy permits them.

``invoke_tool`` is the agent-side call. It checks policy, schema, and the
idempotency key, then runs the handler. ``dispatch_target`` is the Lambda-side
call Gateway makes after policy has already allowed the request.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from agentcore_tracing import (
    ATTR_AGENT_VERSION,
    ATTR_RUNTIME_SESSION_ID,
    SPAN_GATEWAY_CALL,
    TurnLog,
    emit_turn_log,
    get_tracer,
    hash_session_id,
    tool_span_name,
)
from opentelemetry.trace import Span, Status, StatusCode

from agentcore_tools.errors import (
    FatalToolError,
    IdempotencyRequired,
    RetryableToolError,
    SchemaError,
    ToolConfigurationError,
    ToolResult,
    fatal_result,
    retryable_result,
)
from agentcore_tools.gateway import GatewayBinding, LambdaTarget, McpServerTarget
from agentcore_tools.idempotency import IdempotencyClaim, IdempotencyConflict, IdempotencyStore, args_hash
from agentcore_tools.naming import (
    InvalidNameError,
    require_agent_version,
    require_idempotency_key,
    require_log_field,
    require_resource_id,
    require_target_name,
    require_tool_name,
)
from agentcore_tools.policy import Policy, PolicyDecision
from agentcore_tools.schema import parse_schema_version, require_object_schema, to_gateway_schema, validate_instance

ToolHandler = Callable[[Mapping[str, Any]], Mapping[str, Any]]

_DEFAULT_TIMEOUT_MS = 10_000
_DEFAULT_BACKOFF_MS = 200
_MAX_TIMEOUT_MS = 120_000


class ToolRegistry:
    """Registers tools, binds a Gateway, and invokes them under policy."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tools: dict[str, _Tool] = {}
        self._targets: list[LambdaTarget] = []
        self._mcp: list[McpServerTarget] = []
        self._binding: GatewayBinding | None = None
        self._store = IdempotencyStore()

    def tool(
        self,
        *,
        name: str,
        schema: Mapping[str, Any],
        description: str,
        idempotent: bool = True,
        side_effecting: bool = False,
        schema_version: str = "1.0.0",
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> Callable[[ToolHandler], ToolHandler]:
        """Register ``handler`` as a tool. Side-effecting tools must be idempotent."""
        checked_name = require_tool_name(name)
        if side_effecting and not idempotent:
            raise IdempotencyRequired(f"{checked_name} is side-effecting and needs an idempotency strategy")
        checked_schema = require_object_schema(schema)
        parse_schema_version(schema_version)
        checked_description = _require_description(description)
        checked_timeout = _require_timeout(timeout_ms)

        def decorate(handler: ToolHandler) -> ToolHandler:
            spec = _Tool(
                name=checked_name,
                schema=checked_schema,
                description=checked_description,
                idempotent=idempotent,
                side_effecting=side_effecting,
                schema_version=schema_version,
                timeout_ms=checked_timeout,
                handler=handler,
            )
            with self._lock:
                if checked_name in self._tools:
                    raise ToolConfigurationError("tool is already registered")
                self._tools[checked_name] = spec
            return handler

        return decorate

    def add_lambda_target(self, name: str, *, tools: Sequence[str]) -> LambdaTarget:
        """Map registered tools onto a Gateway Lambda target. This is the default path."""
        target_name = require_target_name(name)
        chosen = tuple(require_tool_name(tool) for tool in tools)
        if not chosen:
            raise ToolConfigurationError("Lambda target requires at least one tool")
        if len(set(chosen)) != len(chosen):
            raise ToolConfigurationError("duplicate tool on Lambda target")
        with self._lock:
            self._require_free_target_name(target_name)
            unknown = [tool for tool in chosen if tool not in self._tools]
            if unknown:
                raise ToolConfigurationError("unknown tools: " + ", ".join(unknown))
            mapped = {tool for target in self._targets for tool in target.tool_names}
            overlap = [tool for tool in chosen if tool in mapped]
            if overlap:
                raise ToolConfigurationError("tool is already mapped to a Lambda target")
            target = LambdaTarget(name=target_name, tool_names=chosen)
            self._targets.append(target)
        return target

    def add_mcp_server_target(self, *, name: str, server_name: str) -> McpServerTarget:
        """Record an MCP server target. It cannot be synced or bound as the default path."""
        target = McpServerTarget(name=name, server_name=server_name)
        with self._lock:
            self._require_free_target_name(target.name)
            self._mcp.append(target)
        return target

    def bind_gateway(self, gateway_id: str, *, policy: Policy | None = None) -> GatewayBinding:
        """Attach a deny-by-default policy. Every registered tool must sit on a Lambda target."""
        checked_id = require_resource_id(gateway_id)
        with self._lock:
            if not self._targets:
                raise ToolConfigurationError(
                    "Gateway binding requires a Lambda target; MCP server targets are not the default path"
                )
            mapped = {tool for target in self._targets for tool in target.tool_names}
            missing = sorted(name for name in self._tools if name not in mapped)
            if missing:
                raise ToolConfigurationError("tools are not on a Lambda target: " + ", ".join(missing))
            binding = GatewayBinding(
                gateway_id=checked_id,
                policy=policy if policy is not None else Policy(),
                targets=tuple(self._targets),
            )
            self._binding = binding
        return binding

    @property
    def binding(self) -> GatewayBinding | None:
        return self._binding

    def lambda_definitions(self, target_name: str) -> tuple[dict[str, Any], ...]:
        """Inline tool schemas for ``create_gateway_target``."""
        target = self._target(target_name)
        definitions: list[dict[str, Any]] = []
        for name in target.tool_names:
            spec = self._spec(name)
            if spec is None:
                raise ToolConfigurationError("unknown tools")
            definitions.append(
                {
                    "description": spec.description,
                    "inputSchema": to_gateway_schema(spec.schema),
                    "name": spec.name,
                }
            )
        return tuple(definitions)

    def invoke_tool(
        self,
        name: str,
        args: Mapping[str, Any],
        *,
        agent_version: str,
        idempotency_key: str | None = None,
        actor_id: str = "actor-default",
        runtime_session_id: str = "session-local",
        request_id: str | None = None,
    ) -> ToolResult:
        """Validate, authorize, and run ``name``. Denied calls do not run the handler."""
        version = require_agent_version(agent_version)
        actor = require_log_field(actor_id, "actor id")
        session = require_log_field(runtime_session_id, "runtime session id")
        request = _request_id(request_id)
        started = time.perf_counter()
        result: ToolResult | None = None
        span_tool = _span_tool(name)
        with get_tracer().start_as_current_span(tool_span_name(span_tool)) as span:
            span.set_attribute(ATTR_AGENT_VERSION, version)
            span.set_attribute(ATTR_RUNTIME_SESSION_ID, hash_session_id(session))
            span.set_attribute("tool.name", span_tool)
            try:
                result = self._invoke(
                    name,
                    args,
                    agent_version=version,
                    idempotency_key=idempotency_key,
                )
            finally:
                if result is not None:
                    _annotate(span, result)
                    _log(
                        result,
                        tool_name=span_tool,
                        actor_id=actor,
                        agent_version=version,
                        runtime_session_id=session,
                        request_id=request,
                        started=started,
                    )
        if result is None:
            return fatal_result("unexpected", "tool failed")
        return result.detached()

    def dispatch_target(
        self,
        name: str,
        args: Mapping[str, Any],
        *,
        agent_version: str,
        actor_id: str = "actor-default",
        runtime_session_id: str = "session-local",
        request_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ToolResult:
        """Run a tool the way the Lambda target does: schema and handler, no policy check.

        Gateway Policy is the authorization boundary. Do not call this from the
        agent. Use ``invoke_tool``. Without ``idempotency_key`` this method does
        not consult the idempotency cache. Gateway's default Lambda event is the
        tool arguments only, so the durable guard stays inside the handler.
        """
        version = require_agent_version(agent_version)
        actor = require_log_field(actor_id, "actor id")
        session = require_log_field(runtime_session_id, "runtime session id")
        request = _request_id(request_id)
        started = time.perf_counter()
        result: ToolResult | None = None
        span_tool = _span_tool(name)
        with get_tracer().start_as_current_span(tool_span_name(span_tool)) as span:
            span.set_attribute(ATTR_AGENT_VERSION, version)
            span.set_attribute(ATTR_RUNTIME_SESSION_ID, hash_session_id(session))
            span.set_attribute("tool.name", span_tool)
            try:
                result = self._dispatch(name, args, idempotency_key=idempotency_key)
            finally:
                if result is not None:
                    _annotate(span, result)
                    _log(
                        result,
                        tool_name=span_tool,
                        actor_id=actor,
                        agent_version=version,
                        runtime_session_id=session,
                        request_id=request,
                        started=started,
                    )
        if result is None:
            return fatal_result("unexpected", "tool failed")
        return result.detached()

    def _invoke(
        self,
        name: str,
        args: Mapping[str, Any],
        *,
        agent_version: str,
        idempotency_key: str | None,
    ) -> ToolResult:
        try:
            tool_name = require_tool_name(name)
        except InvalidNameError:
            return fatal_result("unknown_tool", "unknown tool")
        binding = self._binding
        if binding is None:
            return fatal_result("policy_denied", "gateway is not bound")
        spec = self._spec(tool_name)
        if spec is None:
            return fatal_result("unknown_tool", "unknown tool")
        if binding.policy.decision(agent_version, tool_name) is not PolicyDecision.ALLOW:
            return fatal_result("policy_denied", f"tool {tool_name} is not allowed for this agent version")
        rejected = _reject_schema(spec.schema, args)
        if rejected is not None:
            return rejected
        normalized = _normalize_args(args)
        if normalized is None:
            return fatal_result("schema_rejected", "arguments must be an object")
        if binding.target_for_tool(tool_name) is None:
            return fatal_result("unmapped_tool", "tool is not on a Lambda target")
        key, key_error = _idempotency_key(spec, idempotency_key)
        if key_error is not None:
            return key_error
        if key is not None and spec.idempotent:
            try:
                return self._run_claimed(spec, tool_name, normalized, key)
            except IdempotencyConflict:
                return fatal_result("idempotency_conflict", "idempotency key was reused with different arguments")
        result, _late = self._execute(spec, normalized)
        return result

    def _dispatch(self, name: str, args: Mapping[str, Any], *, idempotency_key: str | None = None) -> ToolResult:
        try:
            tool_name = require_tool_name(name)
        except InvalidNameError:
            return fatal_result("unknown_tool", "unknown tool")
        spec = self._spec(tool_name)
        if spec is None:
            return fatal_result("unknown_tool", "unknown tool")
        rejected = _reject_schema(spec.schema, args)
        if rejected is not None:
            return rejected
        normalized = _normalize_args(args)
        if normalized is None:
            return fatal_result("schema_rejected", "arguments must be an object")
        key = _optional_idempotency_key(idempotency_key)
        if key is None and idempotency_key:
            return fatal_result("idempotency_key_invalid", "idempotency key is invalid")
        if key is not None and spec.idempotent:
            try:
                return self._run_claimed(spec, tool_name, normalized, key)
            except IdempotencyConflict:
                return fatal_result("idempotency_conflict", "idempotency key was reused with different arguments")
        result, _late = self._execute(spec, normalized)
        return result

    def _run_claimed(self, spec: _Tool, tool_name: str, args: dict[str, Any], key: str) -> ToolResult:
        begun = self._store.begin(tool_name, key, args_hash(args))
        if not isinstance(begun, IdempotencyClaim):
            return begun
        result, late = self._execute(spec, args)
        if late is None:
            self._store.finish(begun, result)
            return result

        def complete(final: ToolResult, claim: IdempotencyClaim = begun) -> None:
            self._store.finish(claim, final)

        late(complete)
        return result

    def _execute(
        self,
        spec: _Tool,
        args: dict[str, Any],
    ) -> tuple[ToolResult, Callable[[Callable[[ToolResult], None]], None] | None]:
        """Run ``spec.handler``. A deadline does not stop the handler thread.

        The second value is set only on deadline. Call it with a callback to
        receive the handler's eventual result. Python cannot cancel the thread.
        The gateway span covers this attempt, including a deadline that returns
        before the thread ends.
        """
        with get_tracer().start_as_current_span(SPAN_GATEWAY_CALL):
            return self._execute_handler(spec, args)

    def _execute_handler(
        self,
        spec: _Tool,
        args: dict[str, Any],
    ) -> tuple[ToolResult, Callable[[Callable[[ToolResult], None]], None] | None]:
        done = threading.Event()
        box: dict[str, ToolResult] = {}

        def run() -> None:
            try:
                box["result"] = _result_from_output(spec.handler(args))
            except RetryableToolError as exc:
                box["result"] = retryable_result(exc.code, str(exc) or exc.code, exc.backoff_ms)
            except FatalToolError as exc:
                box["result"] = fatal_result(exc.code, str(exc) or exc.code)
            except Exception:
                box["result"] = fatal_result("unexpected", "unexpected tool failure")
            finally:
                done.set()

        thread = threading.Thread(target=run, name="agentcore-tool", daemon=True)
        thread.start()
        if done.wait(spec.timeout_ms / 1000):
            return box["result"], None

        def late(callback: Callable[[ToolResult], None]) -> None:
            def watch() -> None:
                done.wait()
                callback(box["result"])

            threading.Thread(target=watch, name="agentcore-tool-late", daemon=True).start()

        return retryable_result("timeout", "tool timed out", _DEFAULT_BACKOFF_MS), late

    def _spec(self, name: str) -> _Tool | None:
        with self._lock:
            return self._tools.get(name)

    def _target(self, name: str) -> LambdaTarget:
        checked = require_target_name(name)
        binding = self._binding
        if binding is not None:
            return binding.target(checked)
        for item in self._targets:
            if item.name == checked:
                return item
        raise ToolConfigurationError("unknown Lambda target")

    def _require_free_target_name(self, name: str) -> None:
        if any(item.name == name for item in self._targets) or any(item.name == name for item in self._mcp):
            raise ToolConfigurationError("target name is already registered")


class _Tool:
    def __init__(
        self,
        *,
        name: str,
        schema: dict[str, Any],
        description: str,
        idempotent: bool,
        side_effecting: bool,
        schema_version: str,
        timeout_ms: int,
        handler: ToolHandler,
    ) -> None:
        self.name = name
        self.schema = schema
        self.description = description
        self.idempotent = idempotent
        self.side_effecting = side_effecting
        self.schema_version = schema_version
        self.timeout_ms = timeout_ms
        self.handler = handler


def _require_description(description: str) -> str:
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        raise ValueError("description is required")
    if any(ord(char) < 32 for char in description):
        raise ValueError("description must be a single-line string")
    return description.strip()


def _require_timeout(timeout_ms: int) -> int:
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int):
        raise ValueError("timeout_ms must be between 1 and 120000")
    if timeout_ms < 1 or timeout_ms > _MAX_TIMEOUT_MS:
        raise ValueError("timeout_ms must be between 1 and 120000")
    return timeout_ms


def _reject_schema(schema: Mapping[str, Any], args: Mapping[str, Any]) -> ToolResult | None:
    try:
        validate_instance(schema, args)
    except SchemaError as exc:
        return fatal_result("schema_rejected", str(exc) or "schema rejected")
    return None


def _normalize_args(args: Mapping[str, Any]) -> dict[str, Any] | None:
    if not isinstance(args, dict):
        return None
    try:
        parsed: object = json.loads(json.dumps(args, sort_keys=True))
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    normalized: dict[str, Any] = {}
    for key, value in parsed.items():
        if not isinstance(key, str):
            return None
        normalized[key] = value
    return normalized


def _optional_idempotency_key(key: str | None) -> str | None:
    """Return a valid key, or ``None`` when the caller omitted it.

    An invalid non-empty key returns ``None`` and the caller treats that as
    ``idempotency_key_invalid`` when the original value was set.
    """
    if not key:
        return None
    try:
        return require_idempotency_key(key)
    except InvalidNameError:
        return None


def _idempotency_key(spec: _Tool, key: str | None) -> tuple[str | None, ToolResult | None]:
    if spec.side_effecting and not key:
        return None, fatal_result("idempotency_key_required", "side-effecting tools require an idempotency key")
    if key is None:
        return None, None
    try:
        return require_idempotency_key(key), None
    except InvalidNameError:
        return None, fatal_result("idempotency_key_invalid", "idempotency key is invalid")


def _result_from_output(output: object) -> ToolResult:
    if not isinstance(output, dict):
        return fatal_result("invalid_result", "tool result must be an object")
    try:
        parsed: object = json.loads(json.dumps(output, sort_keys=True))
    except (TypeError, ValueError):
        return fatal_result("invalid_result", "tool result must be JSON")
    if not isinstance(parsed, dict):
        return fatal_result("invalid_result", "tool result must be an object")
    normalized: dict[str, Any] = {}
    for key, value in parsed.items():
        if not isinstance(key, str):
            return fatal_result("invalid_result", "tool result must be an object")
        normalized[key] = value
    return ToolResult(output=normalized, error=None, replayed=False)


def _span_tool(name: str) -> str:
    try:
        return require_tool_name(name)
    except InvalidNameError:
        return "invalid"


def _request_id(request_id: str | None) -> str:
    if request_id is None:
        return str(uuid.uuid4())
    try:
        return require_log_field(request_id, "request id")
    except InvalidNameError:
        return str(uuid.uuid4())


def _annotate(span: Span, result: ToolResult) -> None:
    span.set_attribute("tool.replayed", result.replayed)
    if result.error is None:
        return
    span.set_attribute("tool.error_class", result.error.error_class.value)
    span.set_attribute("tool.error_code", result.error.code)
    span.set_status(Status(StatusCode.ERROR))


def _log(
    result: ToolResult,
    *,
    tool_name: str,
    actor_id: str,
    agent_version: str,
    runtime_session_id: str,
    request_id: str,
    started: float,
) -> None:
    error_class = None if result.error is None else result.error.error_class.value
    emit_turn_log(
        TurnLog(
            runtime_session_id=runtime_session_id,
            actor_id=actor_id,
            agent_version=agent_version,
            request_id=request_id,
            latency_ms=(time.perf_counter() - started) * 1000,
            tool_name=tool_name,
            error_class=error_class,
        )
    )
