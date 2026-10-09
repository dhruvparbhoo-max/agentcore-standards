"""Tools this agent may call. Every name must be in ``tools.from_registry`` and permitted in the Cedar file.

The template has none. A pattern adds a Gateway tool from
``primitives/gateway-tools/<name>``, lists it in ``pattern.yaml``, permits it in
``policies/tools.cedar``, and builds a ``ToolSpec`` here whose handler calls
Gateway. A send, spend, delete, or change tool sets ``action`` so it pauses.
"""

from agentcore_agent import ToolSpec

TOOLS: tuple[ToolSpec, ...] = ()
