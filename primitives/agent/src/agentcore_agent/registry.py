"""Agent Registry listing for one Gateway tool, built from its ``tool.yaml``.

A pattern discovers tools by name from Agent Registry. It does not keep a
second list. The MCP server and tool definitions follow
``build_mcp_descriptors`` in awslabs/loom ``backend/app/services/registry.py``
(Apache-2.0), mapped onto the ``CreateRegistryRecord`` fields in boto3
(``descriptorType: MCP``, ``descriptors.mcp.server`` and ``descriptors.mcp.tools``).
The gateway URL and registry id come from the environment at publish time.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml
from jsonschema import Draft202012Validator

from agentcore_agent.schema import ACTION_CLASSES

MCP_SERVER_SCHEMA = "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
MCP_DESCRIPTION_MAX_LENGTH = 100
NAMESPACE = "agentcore-standards"

TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "name",
        "description",
        "version",
        "owner",
        "action",
        "idempotency",
        "handler",
        "input_schema",
        "output_schema",
    ],
    "properties": {
        "name": {"type": "string", "pattern": r"^[a-z][a-z0-9_]{1,63}$"},
        "description": {"type": "string", "minLength": 1, "maxLength": MCP_DESCRIPTION_MAX_LENGTH},
        "version": {"type": "string", "pattern": r"^\d+\.\d+\.\d+$"},
        "owner": {"type": "string", "pattern": r"^[^@\s]+@[^@\s]+\.[^@\s]+$"},
        "action": {"enum": ["read", *ACTION_CLASSES]},
        "idempotency": {"enum": ["required", "not-needed"]},
        "handler": {"type": "string", "pattern": r"^[a-z_][a-z0-9_.]*\.[a-z_][a-z0-9_]*$"},
        "secrets": {"type": "array", "items": {"type": "string", "pattern": r"^[a-z0-9-]+$"}},
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
    },
}


class RegistryClient(Protocol):
    def create_registry_record(self, **kwargs: Any) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class ToolListing:
    raw: Mapping[str, Any]

    @property
    def name(self) -> str:
        return str(self.raw["name"])

    @property
    def action(self) -> str:
        return str(self.raw["action"])


def load_tool(folder: Path) -> ToolListing:
    raw = yaml.safe_load((folder / "tool.yaml").read_text(encoding="utf-8"))
    problems = tool_problems(raw, folder_name=folder.name)
    if problems:
        raise ValueError(f"{folder}/tool.yaml: " + "; ".join(problems))
    return ToolListing(raw=raw)


def tool_problems(raw: Any, *, folder_name: str | None = None) -> list[str]:
    if not isinstance(raw, Mapping):
        return ["tool.yaml must be a mapping"]
    validator = Draft202012Validator(TOOL_SCHEMA)
    problems = [
        f"{'.'.join(str(p) for p in error.absolute_path) or '(top level)'}: {error.message}"
        for error in validator.iter_errors(raw)
    ]
    if problems:
        return problems
    if folder_name is not None and folder_name != "_template" and raw["name"] != folder_name:
        problems.append(f"name: must match the folder name {folder_name!r}")
    if raw["action"] != "read" and raw["idempotency"] != "required":
        problems.append("idempotency: required for a tool that sends, spends, deletes, or changes")
    if raw["idempotency"] == "required" and "idempotency_key" not in raw["input_schema"].get("required", []):
        problems.append("input_schema: idempotency_key must be required when idempotency is required")
    return problems


def mcp_descriptors(listing: ToolListing, *, gateway_url: str) -> dict[str, Any]:
    """``descriptors`` for ``CreateRegistryRecord`` with ``descriptorType: MCP``."""
    namespaced = f"{NAMESPACE}/{listing.name}"
    description = str(listing.raw["description"])[:MCP_DESCRIPTION_MAX_LENGTH]
    server = {
        "$schema": MCP_SERVER_SCHEMA,
        "name": namespaced,
        "description": description,
        "version": str(listing.raw["version"]),
        "capabilities": {"tools": {}},
        "serverInfo": {"name": namespaced, "version": str(listing.raw["version"])},
        "remotes": [{"type": "streamable-http", "url": gateway_url}],
    }
    tool = {
        "name": listing.name,
        "description": description,
        "inputSchema": dict(listing.raw["input_schema"]),
        "outputSchema": dict(listing.raw["output_schema"]),
        "annotations": {
            "readOnlyHint": listing.action == "read",
            "destructiveHint": listing.action in {"delete", "change"},
            "idempotentHint": listing.raw["idempotency"] == "required",
        },
    }
    return {
        "mcp": {
            "server": {"inlineContent": json.dumps(server, sort_keys=True)},
            "tools": {"inlineContent": json.dumps({"tools": [tool]}, sort_keys=True)},
        }
    }


def registry_record(listing: ToolListing, *, registry_id: str, gateway_url: str) -> dict[str, Any]:
    return {
        "registryId": registry_id,
        "name": listing.name,
        "description": str(listing.raw["description"]),
        "descriptorType": "MCP",
        "descriptors": mcp_descriptors(listing, gateway_url=gateway_url),
        "recordVersion": str(listing.raw["version"]),
    }


def publish(listing: ToolListing, client: RegistryClient, *, registry_id: str, gateway_url: str) -> Mapping[str, Any]:
    """Create the record. Approval in the registry is a separate, human step."""
    return client.create_registry_record(**registry_record(listing, registry_id=registry_id, gateway_url=gateway_url))
