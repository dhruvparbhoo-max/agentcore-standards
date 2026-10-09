"""Four ways to ask a person. All four call ``pause_for_human`` with the same token rules.

Other patterns do not re-implement the ask. They import one of these and pass
a ``PauseRequest``. The default this agent uses is ``hook``: the loop
interrupts on a risky tool and ``build_agent`` opens the ticket.

The other three are written up so a later pattern can pick them without
inventing a second token. None of them have been run against AWS.
"""

from __future__ import annotations

from agentcore_agent import AgentSession, PauseRequest, PauseTicket

WAYS = ("hook", "tool_context", "step_functions", "mcp_elicitation")


def hook(session: AgentSession, request: PauseRequest) -> PauseTicket:
    """The loop interrupts. ``build_agent`` already does this when a risky tool is selected."""
    return session.pause_for_human(request)


def tool_context(session: AgentSession, request: PauseRequest) -> PauseTicket:
    """The tool's return value tells the model a person must decide. Same pause, same token."""
    return session.pause_for_human(request)


def step_functions(session: AgentSession, request: PauseRequest) -> PauseTicket:
    """A Step Functions wait state holds the job. The wait is the job row, not the microVM.

    When the person decides, a worker starts a new session through the front door,
    loads the checkpoint, and calls ``resume``. This function still opens the same token.
    """
    return session.pause_for_human(request)


def mcp_elicitation(session: AgentSession, request: PauseRequest) -> PauseTicket:
    """MCP elicitation asks the client. The token, the expiry, and ``decide`` stay ours."""
    return session.pause_for_human(request)


ASK = {
    "hook": hook,
    "tool_context": tool_context,
    "step_functions": step_functions,
    "mcp_elicitation": mcp_elicitation,
}


def ask(way: str, session: AgentSession, request: PauseRequest) -> PauseTicket:
    if way not in ASK:
        raise ValueError(f"unknown ask {way!r}; choose one of {WAYS}")
    return ASK[way](session, request)
