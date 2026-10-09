"""Tag outside text with its source before a model sees it.

User text, retrieved documents, tool results, events, and other agents'
messages are untrusted. The tag names the source. Angle brackets inside are
escaped so the text cannot close the tag and pose as instructions.
"""

from __future__ import annotations

import html
import re

SOURCES = frozenset({"user", "document", "tool", "event", "agent", "email"})
_TAG = re.compile(r'<untrusted source="(?P<source>[a-z]+)">(?P<body>.*?)</untrusted>', re.DOTALL)


def wrap(source: str, text: str) -> str:
    if source not in SOURCES:
        raise ValueError(f"unknown untrusted source {source!r}")
    body = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<untrusted source="{source}">{body}</untrusted>'


def unwrap_last(text: str, *, source: str = "user") -> str:
    """The body of the last tag from ``source``, unescaped. Text with no tag is returned as is."""
    found = [match for match in _TAG.finditer(text) if match.group("source") == source]
    if not found:
        return text
    return html.unescape(found[-1].group("body"))
