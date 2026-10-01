"""Token and USD estimate attributes recorded on turn and model spans.

USD figures are estimates for eval budgets. They are not a billing export.
Lane A prices text at zero USD until a model client reports usage and a rate.
"""

from opentelemetry.trace import Span

from agentcore_tracing.attributes import ATTR_COST_TOKENS, ATTR_COST_USD_ESTIMATE


class CostEstimate:
    """Cost attributes for one model call or a turn rollup."""

    def __init__(self, *, tokens: int, usd_estimate: float) -> None:
        if tokens < 0:
            raise ValueError("tokens must be >= 0")
        if usd_estimate < 0:
            raise ValueError("usd_estimate must be >= 0")
        self.tokens = tokens
        self.usd_estimate = usd_estimate

    def as_attributes(self) -> dict[str, int | float]:
        return {
            ATTR_COST_TOKENS: self.tokens,
            ATTR_COST_USD_ESTIMATE: self.usd_estimate,
        }


def estimate_turn_cost(
    prompt: str,
    completion: str,
    *,
    usd_per_million_tokens: float = 0.0,
) -> CostEstimate:
    """Estimate tokens from text length until a model client returns usage.

    The heuristic is ``max(1, len(text) // 4)`` per non-empty side. The default
    rate is zero so a span still carries ``cost.usd_estimate`` without inventing a price.
    """
    if usd_per_million_tokens < 0:
        raise ValueError("usd_per_million_tokens must be >= 0")
    tokens = _text_tokens(prompt) + _text_tokens(completion)
    usd = round((tokens / 1_000_000) * usd_per_million_tokens, 8)
    return CostEstimate(tokens=tokens, usd_estimate=usd)


def record_cost(span: Span, cost: CostEstimate) -> None:
    """Write cost attributes onto an open span."""
    span.set_attribute(ATTR_COST_TOKENS, cost.tokens)
    span.set_attribute(ATTR_COST_USD_ESTIMATE, cost.usd_estimate)


def _text_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)
