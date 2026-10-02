"""Tool registry, Gateway Lambda targets, and idempotency wrappers.

The demo (``DemoTools``, ``RecordStore``, ``put_record``) lives in
``agentcore_tools.demo``. It is a sample, not the library API.
"""

from typing import Any

from agentcore_tools.compact import CompactedToolOutput, compact_tool_output
from agentcore_tools.discovery import ToolCard, ToolCatalog
from agentcore_tools.errors import (
    ErrorClass,
    FatalToolError,
    GatewayConfigError,
    IdempotencyRequired,
    RetryableToolError,
    SchemaError,
    SchemaVersionError,
    ToolConfigurationError,
    ToolError,
    ToolResult,
    ToolTimeout,
)
from agentcore_tools.gateway import GatewayBinding, LambdaTarget, McpServerTarget
from agentcore_tools.lambda_target import LambdaContext, make_lambda_handler
from agentcore_tools.naming import gateway_tool_name, strip_gateway_tool_name
from agentcore_tools.policy import Policy, PolicyDecision
from agentcore_tools.registry import ToolRegistry
from agentcore_tools.retrieve import Citation, Corpus, Passage
from agentcore_tools.runtime_client import AgentCoreGatewayClient, GatewaySyncResult
from agentcore_tools.schema import assert_schema_evolution, validate_instance

_DEMO_EXPORTS = {
    "DEMO_AGENT_VERSION": "agentcore_tools.demo",
    "LAMBDA_TARGET": "agentcore_tools.demo",
    "PUT_RECORD": "agentcore_tools.demo",
    "DemoTools": "agentcore_tools.demo",
    "RecordStore": "agentcore_tools.demo",
    "build_demo_registry": "agentcore_tools.demo",
    "write_double_invoke_evidence": "agentcore_tools.checks",
}


def __getattr__(name: str) -> Any:
    """Refuse sample imports from the library root."""
    module = _DEMO_EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    raise ImportError(
        f"{name} is the offline demo in {module}, not the tool registry API. Import it from that module."
    )


__all__ = [
    "AgentCoreGatewayClient",
    "Citation",
    "CompactedToolOutput",
    "Corpus",
    "ErrorClass",
    "FatalToolError",
    "GatewayBinding",
    "GatewayConfigError",
    "GatewaySyncResult",
    "IdempotencyRequired",
    "LambdaContext",
    "LambdaTarget",
    "McpServerTarget",
    "Passage",
    "Policy",
    "PolicyDecision",
    "RetryableToolError",
    "SchemaError",
    "SchemaVersionError",
    "ToolCard",
    "ToolCatalog",
    "ToolConfigurationError",
    "ToolError",
    "ToolRegistry",
    "ToolResult",
    "ToolTimeout",
    "assert_schema_evolution",
    "compact_tool_output",
    "gateway_tool_name",
    "make_lambda_handler",
    "strip_gateway_tool_name",
    "validate_instance",
]
