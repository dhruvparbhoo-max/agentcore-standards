"""Span attribute keys required on a production turn."""

from collections.abc import Mapping

ATTR_AGENT_VERSION = "agent.version"
ATTR_RUNTIME_SESSION_ID = "runtime.session_id"
ATTR_COST_TOKENS = "cost.tokens"
ATTR_COST_USD_ESTIMATE = "cost.usd_estimate"

REQUIRED_TURN_ATTRIBUTES: tuple[str, ...] = (
    ATTR_AGENT_VERSION,
    ATTR_RUNTIME_SESSION_ID,
    ATTR_COST_TOKENS,
    ATTR_COST_USD_ESTIMATE,
)


def missing_required_attributes(attributes: Mapping[str, object]) -> tuple[str, ...]:
    """Return required turn attributes that are absent.

    A present numeric zero counts as present. Callers fail CI when this is non-empty.
    """
    missing: list[str] = []
    for key in REQUIRED_TURN_ATTRIBUTES:
        if key not in attributes:
            missing.append(key)
            continue
        value = attributes[key]
        if value is None or value == "":
            missing.append(key)
    return tuple(missing)
