"""The AgentCore Runtime entrypoint for ambient jobs.

A trigger Lambda writes the job and the worker invokes this runtime through
the front door with the service caller and the stored consent. Local tests
call ``run_job`` instead of HTTP.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agentcore_agent import AgentSession, PatternConfig, build_agent, load_pattern
from agentcore_agent.config import ACTOR_HEADER
from agentcore_agent.logging import get_logger, update_correlation
from agentcore_agent.models import langchain_model, route_for, strands_model
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.runtime.context import RequestContext

from ambient.script import work_script
from ambient.tools import TOOLS

PATTERN_DIR = Path(os.environ.get("AGENTCORE_PATTERN_DIR", Path(__file__).resolve().parents[2]))
SCRIPTED = "scripted"

app = BedrockAgentCoreApp()
log = get_logger("ambient")


def load_config() -> PatternConfig:
    return load_pattern(PATTERN_DIR)


def model_for(config: PatternConfig) -> Any:
    route = route_for(config)
    if config.framework == "strands":
        return strands_model(route)
    return langchain_model(route)


def make_agent(config: PatternConfig | None = None) -> AgentSession:
    config = config if config is not None else load_config()
    environment = os.environ.get("AGENTCORE_ENVIRONMENT", "local")
    if os.environ.get("AGENTCORE_MODEL") == SCRIPTED:
        return build_agent(config, tools=TOOLS, script=work_script(), environment=environment)
    return build_agent(config, tools=TOOLS, model=model_for(config), environment=environment)


_agent: AgentSession | None = None


def agent() -> AgentSession:
    global _agent
    if _agent is None:
        _agent = make_agent()
    return _agent


@app.entrypoint
def invoke(payload: dict[str, Any], context: RequestContext) -> dict[str, Any]:
    session_id = context.session_id or ""
    actor_id = actor_from(context.request_headers)
    update_correlation(log, session_id=session_id, user_id=actor_id)
    resume = payload.get("resume")
    if isinstance(resume, Mapping):
        result = agent().resume(
            session_id=session_id,
            actor_id=actor_id,
            token_id=str(resume["token_id"]),
            approved=bool(resume.get("approved")),
            message=str(resume.get("message", "")),
        )
    else:
        prompt = payload.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        result = agent().run(prompt, session_id=session_id, actor_id=actor_id)
    log.info("turn finished", extra={"status": result.status, "release_id": result.release_id})
    body: dict[str, Any] = {"status": result.status, "result": result.text, "release_id": result.release_id}
    if result.ticket is not None:
        body["approval"] = result.ticket.as_dict()
    if result.usage is not None:
        body["usage"] = result.usage.as_dict()
    if payload.get("job_id"):
        body["job_id"] = payload["job_id"]
    return body


def actor_from(headers: Mapping[str, str] | None) -> str:
    folded = {str(key).lower(): value for key, value in (headers or {}).items() if value}
    return str(folded.get(ACTOR_HEADER.lower(), ""))
