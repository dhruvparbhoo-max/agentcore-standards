"""Turn the usage an agent reports into a cost record.

The agent returns ``usage`` (model calls, input and output tokens, model id)
from its loop. Tokens come from the Converse response, as in
aws-samples/sample-eval-first-building-enterprise-agents-with-agentcore
``evaluators/mtg_eval/shared/llm_client.py`` (MIT-0). Prices are configured per
environment. A model with no price, or a reply with no usage, is recorded with
that ``source`` and zero USD, so the gap is visible rather than guessed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from agentcore_front_door.policy import Price

REPORTED = "reported"
UNPRICED = "unpriced"
UNREPORTED = "unreported"


@dataclass(frozen=True)
class Usage:
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    reported: bool = False

    @classmethod
    def from_reply(cls, body: Mapping[str, Any]) -> Usage:
        raw = body.get("usage")
        if not isinstance(raw, Mapping):
            return cls()
        return cls(
            model_calls=_count(raw.get("model_calls")),
            input_tokens=_count(raw.get("input_tokens")),
            output_tokens=_count(raw.get("output_tokens")),
            model=str(raw.get("model", "")),
            reported=True,
        )


@dataclass(frozen=True)
class Cost:
    usd: float
    source: str


def price_usage(usage: Usage, prices: Mapping[str, Price], *, aliases: Mapping[str, str] | None = None) -> Cost:
    """``aliases`` maps an agent's application inference profile ARN to the geographic id it copies."""
    if not usage.reported:
        return Cost(0.0, UNREPORTED)
    price = prices.get(usage.model) or prices.get((aliases or {}).get(usage.model, ""))
    if price is None:
        return Cost(0.0, UNPRICED)
    usd = (usage.input_tokens * price.input_per_million + usage.output_tokens * price.output_per_million) / 1_000_000
    return Cost(round(usd, 6), REPORTED)


def _count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return 0
    return int(value)
