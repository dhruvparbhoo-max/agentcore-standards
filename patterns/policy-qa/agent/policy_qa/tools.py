"""No tools. Retrieve is the trusted wrapper in ``policy_qa.knowledge``, not a model-picked tool."""

from agentcore_agent import ToolSpec

TOOLS: tuple[ToolSpec, ...] = ()
