"""Stand-ins for ``make local``: an agent container instead of AgentCore Runtime, and a local signing key.

``LocalRuntimeClient`` POSTs to a ``BedrockAgentCoreApp`` container the way
Runtime does: the payload on ``/invocations``, the session on
``X-Amzn-Bedrock-AgentCore-Runtime-Session-Id``, and the custom headers the
front door adds. ``scripts/local_token.py`` makes the key pair under ``build/``
(outside git) and mints tokens for it. Nothing here is used in a deploy.
"""

from __future__ import annotations

import io
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization

SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"
LOCAL_ISSUER = "https://front-door.local"


class LocalRuntimeError(Exception):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"agent returned {status}")
        self.response = {"Error": {"Code": f"Http{status}", "Message": body[:200]}}


class LocalRuntimeClient:
    def __init__(self, url: str, *, timeout_s: float = 60) -> None:
        self.url = url.rstrip("/")
        self.timeout_s = timeout_s

    def invoke_agent_runtime(self, **kwargs: Any) -> Mapping[str, Any]:
        headers = {"Content-Type": "application/json", SESSION_HEADER: str(kwargs["runtimeSessionId"])}
        headers.update(kwargs.get("_headers") or {})
        request = urllib.request.Request(
            f"{self.url}/invocations", data=kwargs["payload"], headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                body = response.read()
                return {
                    "statusCode": response.status,
                    "contentType": response.headers.get("content-type", "application/json"),
                    "response": io.BytesIO(body),
                }
        except urllib.error.HTTPError as exc:
            raise LocalRuntimeError(exc.code, exc.read().decode("utf-8", "replace")) from exc

    def stop_runtime_session(self, **kwargs: Any) -> Mapping[str, Any]:
        return {}


def public_key(path: Path) -> Any:
    return serialization.load_pem_public_key(path.read_bytes())


def write_key_pair(folder: Path) -> tuple[Path, Path]:
    from cryptography.hazmat.primitives.asymmetric import rsa

    folder.mkdir(parents=True, exist_ok=True)
    private, public = folder / "local-signing.pem", folder / "local-signing.pub.pem"
    if not private.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
        private.chmod(0o600)
        public.write_bytes(
            key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        )
    return private, public


def mint(private: Path, claims: Mapping[str, Any], *, lifetime_s: int = 900) -> str:
    import time

    import jwt

    key = serialization.load_pem_private_key(private.read_bytes(), password=None)
    now = int(time.time())
    body = {"iss": LOCAL_ISSUER, "iat": now, "exp": now + lifetime_s, **claims}
    return jwt.encode(body, key, algorithm="RS256")  # type: ignore[arg-type]
