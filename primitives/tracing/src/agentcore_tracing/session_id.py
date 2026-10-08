"""Session identifiers on spans are hashed so raw ids stay out of trace backends."""

import hashlib


def hash_session_id(session_id: str) -> str:
    """Stable prefix of the SHA-256 of a runtime session id."""
    if not session_id:
        raise ValueError("session_id is required")
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return digest[:32]
