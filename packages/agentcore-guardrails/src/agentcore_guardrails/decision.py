"""Allow or block. Reasons name the rule. They do not echo the text."""

from __future__ import annotations


class Sanitized:
    """Text that may continue. ``redactions`` names the kinds that were replaced."""

    def __init__(self, text: str, redactions: tuple[str, ...] = ()) -> None:
        self.allowed = True
        self.text = text
        self.redactions = redactions
        self.reason = "allowed"


class Blocked:
    """Text that must not be stored, shown, or sent onward."""

    def __init__(self, reason: str) -> None:
        if not reason or any(ord(char) < 32 for char in reason):
            raise ValueError("block reason is required")
        self.allowed = False
        self.text = ""
        self.redactions: tuple[str, ...] = ()
        self.reason = reason
