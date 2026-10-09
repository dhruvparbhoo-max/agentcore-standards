"""JSON Schema for ``pattern.yaml``. Field meanings are in docs/design/library.md.

The schema is the shape. ``config.semantic_problems`` holds the rules that
compare two fields, such as idle timeout against maximum lifetime.
"""

from __future__ import annotations

from typing import Any

ACTION_CLASSES = ("send", "spend", "delete", "change")
LOG_RETENTION_DAYS = (30, 90, 180, 365)
SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"
MCP_SESSION_HEADER = "Mcp-Session-Id"
MAX_MICROVM_SECONDS = 28_800

_STR = {"type": "string", "minLength": 1}
_PATH = {"type": "string", "minLength": 1, "pattern": r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$"}
_POS_INT = {"type": "integer", "minimum": 1}


def _obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties) if required is None else required,
    }


PATTERN_SCHEMA: dict[str, Any] = _obj(
    {
        "name": {"type": "string", "pattern": r"^(_template|[a-z][a-z0-9-]{1,40})$"},
        "owner": {"type": "string", "pattern": r"^[^@\s]+@[^@\s]+\.[^@\s]+$"},
        "alert_route": {"type": "string", "pattern": r"^(sns|email|pagerduty|slack):[^\s]+$"},
        "runbook_url": {"type": "string", "pattern": r"^(https://|docs/)[^\s]+$"},
        "autonomy": {"enum": ["observer", "assistant", "autonomous", "orchestrator"]},
        "risk_tier": {"enum": ["low", "medium", "high"]},
        "framework": {"enum": ["create_agent", "strands", "harness"]},
        "deployment": {"enum": ["docker"]},
        "trigger": {"enum": ["none", "event", "schedule"]},
        "prompts": _obj({"system": _PATH}),
        "identity": _obj(
            {
                "acts_as": {"enum": ["user", "service"]},
                "scopes": {"type": "object", "additionalProperties": {"type": "array", "items": _STR}},
            }
        ),
        "model": _obj(
            {
                "primary": _STR,
                "fallback": {"type": "string"},
                "region_profile": {"enum": ["eu", "uk", "us", "apac", "global"]},
                "cache": {"enum": ["off", "auto"]},
                "team_tag": {"type": "string", "pattern": r"^[a-z][a-z0-9-]{1,40}$"},
            }
        ),
        "memory": _obj(
            {
                "enabled": {"type": "boolean"},
                "write_policy": {"enum": ["validated", "off"]},
                "namespace": _STR,
            }
        ),
        "knowledge": _obj(
            {
                "enabled": {"type": "boolean"},
                "gateway_target": {"enum": ["knowledge-base"]},
                "filter_from": {"enum": ["verified-login"]},
            },
            required=["enabled"],
        ),
        "tools": _obj(
            {
                "from_registry": {"type": "array", "items": _STR, "uniqueItems": True},
                "cedar": _PATH,
            }
        ),
        "lifecycle": _obj(
            {
                "idle_timeout_s": {"type": "integer", "minimum": 60, "maximum": MAX_MICROVM_SECONDS},
                "max_lifetime_s": {"type": "integer", "minimum": 60, "maximum": MAX_MICROVM_SECONDS},
                "resumable": {"type": "boolean"},
                "max_turns": _POS_INT,
                "max_steps": _POS_INT,
                "timeout_s": _POS_INT,
                "max_retries": {"type": "integer", "minimum": 0, "maximum": 10},
                "session_id_min": {"type": "integer", "minimum": 33},
            }
        ),
        "context": _obj(
            {
                "token_budget": _POS_INT,
                "compaction_at": _POS_INT,
                "clear_tool_results": {"type": "boolean"},
            }
        ),
        "approval": _obj(
            {
                "required_for": {"type": "array", "items": {"enum": list(ACTION_CLASSES)}, "uniqueItems": True},
                "expire_s": {"type": "integer", "minimum": 60, "maximum": 86_400},
                "reviewers": {"enum": [1, 2]},
            }
        ),
        "output_schema": _PATH,
        "runtime": _obj(
            {
                "protocol": {"enum": ["HTTP", "MCP", "A2A"]},
                "header_allowlist": {"type": "array", "items": _STR, "minItems": 1, "maxItems": 20},
                "session_header": {"enum": [SESSION_HEADER, MCP_SESSION_HEADER]},
            },
            required=["header_allowlist", "session_header"],
        ),
        "data": _obj(
            {
                "classification": {"enum": ["public", "internal", "confidential"]},
                "pii": {"type": "boolean"},
                "region": {"type": "string", "pattern": r"^[a-z]{2}(-[a-z]+)+-\d$"},
                "log_retention_days": {"enum": list(LOG_RETENTION_DAYS)},
                "audit_retention_days": _POS_INT,
            }
        ),
        "eval": _obj(
            {
                "golden_set": _PATH,
                "threshold": {"type": "number", "minimum": 0, "maximum": 1},
                "groundedness": {"type": "number", "minimum": 0, "maximum": 1},
                "runs_per_case": _POS_INT,
            },
            required=["golden_set", "threshold", "runs_per_case"],
        ),
        "cost": _obj(
            {
                "max_usd_per_run": {"type": "number", "exclusiveMinimum": 0},
                "monthly_cap_usd": {"type": "number", "exclusiveMinimum": 0},
                "on_cap": {"enum": ["pause"]},
            }
        ),
        "release": _obj({"id": {"type": "string"}}),
        "endpoint": {"type": "string", "pattern": r"^[A-Z][A-Z0-9_]{0,47}$", "not": {"const": "DEFAULT"}},
    }
)
