"""Bind a Runtime session id to the verified caller.

A ``runtimeSessionId`` routes to one warm microVM, so it is an authorisation
boundary. Copied from aws-samples/sample-agent-platform-with-agentcore
``backend/app/services/session_binding.py`` (MIT-0): an HMAC caller tag inside
the id, a fresh id when none is sent, an owned id returned unchanged, and a
keyed digest for ids built server-side from a channel conversation.

Two rules are stricter than the sample, because docs/design/library.md says so:
an id carrying another caller's tag is refused instead of re-namespaced, and a
raw id shorter than the pattern's ``session_id_min`` is refused.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

PREFIX = "s"
_CHARSET = re.compile(r"^[A-Za-z0-9_-]+$")
_MAX = 256
_TAG = 12


class SessionRejected(Exception):
    """The id is too short, malformed, or belongs to someone else."""


class SessionBinder:
    """``resolve`` maps a requested id onto one this caller owns. Ids are 47 characters."""

    def __init__(self, secret: bytes, *, min_length: int = 33) -> None:
        if len(secret) < 32:
            raise ValueError("the binding secret must be at least 32 bytes")
        if min_length < 33:
            raise ValueError("min_length must be >= 33")
        self._secret = secret
        self.min_length = min_length

    def caller_tag(self, user: str) -> str:
        return self._hmac(b"utag", user.encode("utf-8"))[:_TAG]

    def resolve(self, user: str, requested: str | None) -> str:
        tag = self.caller_tag(user)
        if not requested:
            return f"{PREFIX}-{tag}-{secrets.token_hex(16)}"
        if len(requested) > _MAX or not _CHARSET.match(requested):
            raise SessionRejected("session id has characters Runtime does not accept")
        if len(requested) < self.min_length:
            raise SessionRejected(f"session id must be at least {self.min_length} characters")
        parts = requested.split("-", 2)
        if len(parts) == 3 and parts[0] == PREFIX and len(parts[1]) == _TAG:
            if hmac.compare_digest(parts[1], tag):
                return requested
            raise SessionRejected("session id belongs to another caller")
        body = self._hmac(b"sid", user.encode("utf-8") + b"|" + requested.encode("utf-8"))[:32]
        return f"{PREFIX}-{tag}-{body}"

    def owns(self, user: str, session_id: str) -> bool:
        parts = session_id.split("-", 2)
        return len(parts) == 3 and parts[0] == PREFIX and hmac.compare_digest(parts[1], self.caller_tag(user))

    def channel_session(self, channel_id: str, conversation_id: str) -> str:
        """Stable id for a channel conversation. Keyed, so it cannot be guessed from the public channel id."""
        digest = self._hmac(b"chn", f"{channel_id}\x00{conversation_id}".encode())
        return f"chn-{digest[:44]}"

    def _hmac(self, label: bytes, message: bytes) -> str:
        return hmac.new(self._secret, label + b"\x00" + message, hashlib.sha256).hexdigest()
