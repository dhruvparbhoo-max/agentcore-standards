"""Retrieve passages and return citations. The score is lexical overlap, not an embedding.

A query that shares no tokens returns no citations, so a caller cannot attach
an unrelated passage. Quotes are shortened with the tool-output compactor.
"""

from __future__ import annotations

from agentcore_tools.compact import compact_tool_output


class Passage:
    """One source passage. ``passage_id`` is what a citation must name."""

    def __init__(self, *, passage_id: str, title: str, text: str) -> None:
        self.passage_id = _label(passage_id, "passage id")
        self.title = _label(title, "title")
        self.text = _body(text)


class Citation:
    """A passage the query overlapped, plus a short quote."""

    def __init__(self, *, passage_id: str, title: str, quote: str, score: float) -> None:
        self.passage_id = passage_id
        self.title = title
        self.quote = quote
        self.score = score
        self.method = "lexical"

    def render(self) -> str:
        """One line a prompt can include without the full passage."""
        return f"[{self.passage_id}] {self.title}: {self.quote}"


class Corpus:
    """An in-memory set of passages."""

    def __init__(self) -> None:
        self._passages: list[Passage] = []

    def add(self, passage: Passage) -> None:
        """Store ``passage``. Duplicate ids are rejected."""
        if any(item.passage_id == passage.passage_id for item in self._passages):
            raise ValueError("duplicate passage id")
        self._passages.append(passage)

    def retrieve(self, query: str, *, limit: int = 3) -> tuple[Citation, ...]:
        """Return up to ``limit`` citations with a positive lexical score."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be >= 1")
        tokens = _tokens(query)
        if not tokens:
            return ()
        ranked: list[tuple[float, Passage]] = []
        for passage in self._passages:
            score = _overlap(tokens, _tokens(passage.title + " " + passage.text))
            if score > 0:
                ranked.append((score, passage))
        ranked.sort(key=lambda item: (-item[0], item[1].passage_id))
        citations: list[Citation] = []
        for score, passage in ranked[:limit]:
            quote = compact_tool_output(passage.text, tool_name=passage.passage_id, max_chars=240).text
            citations.append(Citation(passage_id=passage.passage_id, title=passage.title, quote=quote, score=score))
        return tuple(citations)


def _label(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 120:
        raise ValueError(f"invalid {label}")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"invalid {label}")
    return value.strip()


def _body(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("passage text is required")
    return value.strip()


def _tokens(text: str) -> set[str]:
    found: set[str] = set()
    for raw in text.casefold().split():
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
