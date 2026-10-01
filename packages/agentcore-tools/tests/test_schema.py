"""Schema validation and version bumps."""

from collections.abc import Mapping
from typing import Any

import pytest
from agentcore_tools import SchemaError, SchemaVersionError, assert_schema_evolution, validate_instance

OBJECT_SCHEMA: dict[str, Any] = {
    "additionalProperties": False,
    "properties": {
        "count": {"type": "integer"},
        "tags": {"items": {"type": "string"}, "type": "array"},
        "value": {"type": "string"},
    },
    "required": ["value"],
    "type": "object",
}


def test_missing_required_property_names_the_path() -> None:
    with pytest.raises(SchemaError, match=r"\$\.value is required"):
        validate_instance(OBJECT_SCHEMA, {})


def test_wrong_type_does_not_echo_the_value() -> None:
    token = "token-should-not-leak"
    with pytest.raises(SchemaError, match=r"\$\.value must be a string") as caught:
        validate_instance(OBJECT_SCHEMA, {"value": {"nested": token}})
    assert token not in str(caught.value)


def test_unexpected_property_does_not_echo_the_name() -> None:
    token = "token-should-not-leak"
    with pytest.raises(SchemaError, match="unexpected property") as caught:
        validate_instance(OBJECT_SCHEMA, {"value": "ok", token: "x"})
    assert token not in str(caught.value)


def test_bool_is_not_an_integer() -> None:
    with pytest.raises(SchemaError, match=r"\$\.count must be an integer"):
        validate_instance(OBJECT_SCHEMA, {"count": True, "value": "ok"})


def test_array_items_must_match() -> None:
    validate_instance(OBJECT_SCHEMA, {"tags": ["a"], "value": "ok"})
    with pytest.raises(SchemaError, match=r"\$\.tags\[0\] must be a string"):
        validate_instance(OBJECT_SCHEMA, {"tags": [1], "value": "ok"})


def test_description_change_is_compatible() -> None:
    previous = {
        "properties": {"value": {"description": "old", "type": "string"}},
        "required": ["value"],
        "type": "object",
    }
    current = {
        "properties": {"value": {"description": "new", "type": "string"}},
        "required": ["value"],
        "type": "object",
    }
    assert_schema_evolution(
        previous_version="1.0.0",
        previous_schema=previous,
        current_version="1.0.1",
        current_schema=current,
    )


def test_optional_property_keeps_the_major_version() -> None:
    previous = {"properties": {"value": {"type": "string"}}, "required": ["value"], "type": "object"}
    current = {
        "properties": {"note": {"type": "string"}, "value": {"type": "string"}},
        "required": ["value"],
        "type": "object",
    }
    assert_schema_evolution(
        previous_version="1.0.0",
        previous_schema=previous,
        current_version="1.1.0",
        current_schema=current,
    )


def test_removing_a_property_requires_a_major_bump() -> None:
    previous = {
        "properties": {"note": {"type": "string"}, "value": {"type": "string"}},
        "required": ["value"],
        "type": "object",
    }
    current = {"properties": {"value": {"type": "string"}}, "required": ["value"], "type": "object"}
    with pytest.raises(SchemaVersionError, match="major"):
        assert_schema_evolution(
            previous_version="1.0.0",
            previous_schema=previous,
            current_version="1.1.0",
            current_schema=current,
        )
    assert_schema_evolution(
        previous_version="1.0.0",
        previous_schema=previous,
        current_version="2.0.0",
        current_schema=current,
    )


def test_new_required_property_is_breaking() -> None:
    previous: Mapping[str, Any] = {"properties": {"value": {"type": "string"}}, "required": ["value"], "type": "object"}
    current: Mapping[str, Any] = {
        "properties": {"note": {"type": "string"}, "value": {"type": "string"}},
        "required": ["note", "value"],
        "type": "object",
    }
    with pytest.raises(SchemaVersionError):
        assert_schema_evolution(
            previous_version="1.0.0",
            previous_schema=previous,
            current_version="1.0.0",
            current_schema=current,
        )
