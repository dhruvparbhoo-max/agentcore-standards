"""Identifiers for tools, Gateway targets, and Cedar actions.

Gateway's visible tool name is ``{target}___{tool}``. Neither half may contain
that delimiter, so the split is unambiguous.
"""

import re

TARGET_DELIMITER = "___"

_TOOL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_RESOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_AGENT_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_CEDAR_RESOURCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,511}$")
_CEDAR_ACTION = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,200}$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class InvalidNameError(ValueError):
    """A tool, target, gateway, or version identifier was rejected."""


def require_tool_name(value: str) -> str:
    """Accept a logical tool name. Reject the Gateway delimiter."""
    if not isinstance(value, str) or TARGET_DELIMITER in value or _TOOL_NAME.fullmatch(value) is None:
        raise InvalidNameError("invalid tool name")
    return value


def require_target_name(value: str) -> str:
    """Accept a Lambda target name. Reject the Gateway delimiter."""
    if not isinstance(value, str) or TARGET_DELIMITER in value or _TOOL_NAME.fullmatch(value) is None:
        raise InvalidNameError("invalid target name")
    return value


def require_resource_id(value: str) -> str:
    """Accept a gateway id or policy engine id supplied by the caller."""
    if not isinstance(value, str) or _RESOURCE_ID.fullmatch(value) is None:
        raise InvalidNameError("invalid resource id")
    return value


def require_agent_version(value: str) -> str:
    """Accept an agent version label. This is not a git tag check."""
    if not isinstance(value, str) or _AGENT_VERSION.fullmatch(value) is None:
        raise InvalidNameError("invalid agent version")
    return value


def require_cedar_resource(value: str) -> str:
    """Accept the Gateway resource token embedded in a Cedar statement.

    The real identifier is read from the environment at sync time. It is never
    committed. Quotes and control characters are rejected so the token cannot
    break out of the Cedar string.
    """
    if not isinstance(value, str) or _CEDAR_RESOURCE.fullmatch(value) is None:
        raise InvalidNameError("invalid gateway resource")
    return value


def require_cedar_action(value: str) -> str:
    """Accept a Gateway-visible action (``target___tool``)."""
    if not isinstance(value, str) or TARGET_DELIMITER not in value or _CEDAR_ACTION.fullmatch(value) is None:
        raise InvalidNameError("invalid gateway action")
    return value


def require_idempotency_key(value: str) -> str:
    """Accept an idempotency key. The value is not included in errors."""
    if not isinstance(value, str) or _IDEMPOTENCY_KEY.fullmatch(value) is None:
        raise InvalidNameError("invalid idempotency key")
    return value


def require_log_field(value: str, label: str) -> str:
    """Reject empty or control-character log fields. The value is not echoed."""
    if not isinstance(value, str) or not value or len(value) > 256 or any(ord(char) < 32 for char in value):
        raise InvalidNameError(f"invalid {label}")
    return value


def require_server_name(value: str) -> str:
    """Accept an MCP server label. URLs stay outside this package."""
    if not isinstance(value, str) or "://" in value or "@" in value or _RESOURCE_ID.fullmatch(value) is None:
        raise InvalidNameError("invalid MCP server name")
    return value


def gateway_tool_name(target_name: str, tool_name: str) -> str:
    """Return the MCP-visible name Gateway publishes for a Lambda target."""
    return f"{require_target_name(target_name)}{TARGET_DELIMITER}{require_tool_name(tool_name)}"


def strip_gateway_tool_name(visible_name: str) -> str:
    """Return the logical tool name from ``target___tool``."""
    if not isinstance(visible_name, str) or not visible_name or TARGET_DELIMITER not in visible_name:
        raise InvalidNameError("invalid gateway tool name")
    target, tool = visible_name.split(TARGET_DELIMITER, 1)
    require_target_name(target)
    return require_tool_name(tool)
