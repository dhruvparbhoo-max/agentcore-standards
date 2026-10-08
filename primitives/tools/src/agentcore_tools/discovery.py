"""Progressive tool disclosure.

The index is name plus a one-line summary. The schema is loaded only for the
cards the caller asks for. Disclosure does not permit a tool and does not
invoke it.
"""

from __future__ import annotations

from collections.abc import Sequence

from agentcore_tools.registry import ToolRegistry

_SUMMARY = 120


class ToolCard:
    """A catalog row without an input schema."""

    def __init__(self, *, name: str, summary: str, side_effecting: bool) -> None:
        self.name = name
        self.summary = summary
        self.side_effecting = side_effecting


class ToolCatalog:
    """Index and load against one registry."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def index(self) -> tuple[ToolCard, ...]:
        """Every registered tool, without its schema."""
        cards: list[ToolCard] = []
        for item in self._registry.list_tools():
            cards.append(
                ToolCard(
                    name=str(item["name"]),
                    summary=_summary(str(item["description"])),
                    side_effecting=bool(item["side_effecting"]),
                )
            )
        return tuple(cards)

    def load(self, name: str) -> dict[str, object]:
        """The full definition for ``name``. Unknown names raise."""
        return self._registry.load_tool(name)

    def disclose(self, query: str, *, limit: int = 3) -> tuple[ToolCard, ...]:
        """Return the index cards that overlap ``query``. Schemas are not included."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be >= 1")
        tokens = _tokens(query)
        if not tokens:
            return ()
        ranked: list[tuple[float, ToolCard]] = []
        for card in self.index():
            score = _overlap(tokens, _tokens(card.name + " " + card.summary))
            if score > 0:
                ranked.append((score, card))
        ranked.sort(key=lambda item: (-item[0], item[1].name))
        return tuple(card for _, card in ranked[:limit])


def _summary(description: str) -> str:
    if len(description) <= _SUMMARY:
        return description
    return description[: _SUMMARY - 3].rstrip() + "..."


def _tokens(text: str) -> set[str]:
    found: set[str] = set()
    for raw in text.casefold().replace("_", " ").split():
        token = "".join(char for char in raw if char.isalnum())
        if len(token) >= 2:
            found.add(token)
    return found


def _overlap(query: set[str], document: set[str]) -> float:
    if not query or not document:
        return 0.0
    shared = query & document
    if not shared:
        return 0.0
    return len(shared) / len(query)


def selected_names(cards: Sequence[ToolCard]) -> tuple[str, ...]:
    """Names from an index or a disclose result, in order."""
    return tuple(card.name for card in cards)
