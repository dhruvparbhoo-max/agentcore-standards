"""JSON Schema subset for tool arguments.

The subset matches the fields AgentCore Gateway accepts on a Lambda tool
schema: type, description, properties, required, and items. Object schemas
reject unknown properties unless ``additionalProperties`` is true. Error text
names the path and the expected type. It does not include the rejected value.
"""

import json
from collections.abc import Mapping
from typing import Any

from agentcore_tools.errors import SchemaError, SchemaVersionError
from agentcore_tools.naming import InvalidNameError

_TYPES = frozenset({"string", "number", "integer", "boolean", "array", "object"})
_MAX_DEPTH = 8
_AWS_KEYS = ("type", "description", "properties", "required", "items")


def require_object_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Return a detached copy of an object schema, or raise ``SchemaError``."""
    if not isinstance(schema, dict):
        raise SchemaError("tool schema must be a JSON object")
    try:
        parsed: object = json.loads(json.dumps(schema, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise SchemaError("tool schema must be JSON") from exc
    if not isinstance(parsed, dict) or parsed.get("type") != "object":
        raise SchemaError("tool schema must be a JSON object schema")
    normalized: dict[str, Any] = parsed
    _assert_schema_shape(normalized, path="$", depth=0)
    return normalized


def validate_instance(schema: Mapping[str, Any], instance: object, *, path: str = "$") -> None:
    """Raise ``SchemaError`` when ``instance`` does not match ``schema``."""
    _validate(schema, instance, path=path, depth=0)


def to_gateway_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Project a local schema onto the Gateway Lambda ``inputSchema`` fields.

    ``additionalProperties`` is enforced locally and is not part of the
    control-plane schema, so it is omitted here.
    """
    projected: dict[str, Any] = {}
    for key in _AWS_KEYS:
        if key not in schema:
            continue
        value = schema[key]
        if key == "properties" and isinstance(value, dict):
            projected[key] = {
                name: to_gateway_schema(child) if isinstance(child, dict) else child for name, child in value.items()
            }
        elif key == "items" and isinstance(value, dict):
            projected[key] = to_gateway_schema(value)
        else:
            projected[key] = value
    return projected


def assert_schema_evolution(
    *,
    previous_version: str,
    previous_schema: Mapping[str, Any],
    current_version: str,
    current_schema: Mapping[str, Any],
) -> None:
    """Raise when a breaking change does not increase the major version.

    Compatible changes (description edits, new optional properties, relaxing
    ``additionalProperties``) may keep the same major. Removing a property,
    changing a type, or adding a required property is breaking.
    """
    previous = require_object_schema(previous_schema)
    current = require_object_schema(current_schema)
    previous_major = parse_schema_version(previous_version)[0]
    current_major = parse_schema_version(current_version)[0]
    if is_breaking_change(previous, current) and current_major <= previous_major:
        raise SchemaVersionError("breaking schema change requires a major version bump")


def is_breaking_change(previous: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    """Return whether callers of ``previous`` can fail against ``current``."""
    if previous.get("type") != current.get("type"):
        return True
    schema_type = previous.get("type")
    if schema_type == "object":
        return _object_breaking(previous, current)
    if schema_type == "array":
        previous_items = previous.get("items")
        current_items = current.get("items")
        if isinstance(previous_items, dict) and isinstance(current_items, dict):
            return is_breaking_change(previous_items, current_items)
        return previous_items != current_items
    return False


def _object_breaking(previous: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    previous_properties = _properties(previous)
    current_properties = _properties(current)
    for name, previous_child in previous_properties.items():
        current_child = current_properties.get(name)
        if not isinstance(current_child, dict) or not isinstance(previous_child, dict):
            return True
        if is_breaking_change(previous_child, current_child):
            return True
    previous_required = set(_required(previous))
    current_required = set(_required(current))
    if current_required - previous_required:
        return True
    previous_additional = previous.get("additionalProperties", False)
    current_additional = current.get("additionalProperties", False)
    return previous_additional is True and current_additional is not True


def _properties(schema: Mapping[str, Any]) -> dict[str, Any]:
    value = schema.get("properties", {})
    if isinstance(value, dict):
        return value
    return {}


def _required(schema: Mapping[str, Any]) -> list[str]:
    value = schema.get("required", [])
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def parse_schema_version(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    if len(parts) != 3:
        raise InvalidNameError("schema_version must be major.minor.patch")
    numbers: list[int] = []
    for part in parts:
        if not part.isdigit() or (len(part) > 1 and part.startswith("0")):
            raise InvalidNameError("schema_version must be major.minor.patch")
        numbers.append(int(part))
    return numbers[0], numbers[1], numbers[2]


def _assert_schema_shape(schema: Mapping[str, Any], *, path: str, depth: int) -> None:
    if depth > _MAX_DEPTH:
        raise SchemaError(f"{path} is too deep")
    schema_type = schema.get("type")
    if not isinstance(schema_type, str) or schema_type not in _TYPES:
        raise SchemaError(f"{path} schema type is missing or unsupported")
    if "additionalProperties" in schema and not isinstance(schema["additionalProperties"], bool):
        raise SchemaError(f"{path} additionalProperties must be a boolean")
    if schema_type == "object":
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            raise SchemaError(f"{path} properties must be an object")
        required = schema.get("required", [])
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            raise SchemaError(f"{path} required must be a list of strings")
        for name in required:
            if name not in properties:
                raise SchemaError(f"{path} required property {name} is missing from properties")
        for name, child in properties.items():
            if not isinstance(child, dict):
                raise SchemaError(f"{path}.{name} schema must be an object")
            _assert_schema_shape(child, path=f"{path}.{name}", depth=depth + 1)
    elif schema_type == "array":
        items = schema.get("items")
        if not isinstance(items, dict):
            raise SchemaError(f"{path} array schema requires items")
        _assert_schema_shape(items, path=f"{path}[]", depth=depth + 1)


def _validate(schema: Mapping[str, Any], instance: object, *, path: str, depth: int) -> None:
    if depth > _MAX_DEPTH:
        raise SchemaError(f"{path} is too deep")
    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(instance, dict):
            raise SchemaError(f"{path} must be an object")
        _validate_object(schema, instance, path=path, depth=depth)
        return
    if schema_type == "array":
        if not isinstance(instance, list):
            raise SchemaError(f"{path} must be an array")
        items = schema.get("items")
        if not isinstance(items, dict):
            raise SchemaError(f"{path} array schema requires items")
        for index, item in enumerate(instance):
            _validate(items, item, path=f"{path}[{index}]", depth=depth + 1)
        return
    if schema_type == "string":
        if not isinstance(instance, str):
            raise SchemaError(f"{path} must be a string")
        return
    if schema_type == "boolean":
        if not isinstance(instance, bool):
            raise SchemaError(f"{path} must be a boolean")
        return
    if schema_type == "integer":
        if isinstance(instance, bool) or not isinstance(instance, int):
            raise SchemaError(f"{path} must be an integer")
        return
    if schema_type == "number":
        if isinstance(instance, bool) or not isinstance(instance, (int, float)):
            raise SchemaError(f"{path} must be a number")
        return
    raise SchemaError(f"{path} schema type is missing or unsupported")


def _validate_object(schema: Mapping[str, Any], instance: dict[str, Any], *, path: str, depth: int) -> None:
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise SchemaError(f"{path} properties must be an object")
    required = schema.get("required", [])
    if isinstance(required, list):
        for name in required:
            if isinstance(name, str) and name not in instance:
                raise SchemaError(f"{path}.{name} is required")
    additional = schema.get("additionalProperties", False)
    for key, value in instance.items():
        child = properties.get(key)
        if isinstance(child, dict):
            _validate(child, value, path=f"{path}.{key}", depth=depth + 1)
        elif additional is not True:
            raise SchemaError(f"{path} has an unexpected property")
