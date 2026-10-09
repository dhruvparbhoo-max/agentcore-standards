"""Secrets from Secrets Manager and plain config from SSM, by name.

``get_secret`` is copied from aws-samples/sample-social-intelligence-agents
(``src/social_intelligence/tools/_secrets.py``, MIT-0): a 10 minute TTL so a
rotated value is picked up, the value is never logged, and errors are never
cached. ``get_ssm_parameter`` is copied from awslabs/fullstack-solution-template-
for-agentcore (``patterns/utils/ssm.py``, Apache-2.0). Names come from
``config/environments/<env>.yaml``; values never sit in git.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

_CACHE_TTL = int(os.environ.get("SECRET_CACHE_TTL_SECONDS", "600"))

_cache: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()
_client: Any = None
_client_lock = threading.Lock()


def _get_client() -> Any:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                import boto3

                _client = boto3.client("secretsmanager")
    return _client


def set_client(client: Any) -> None:
    """Swap the Secrets Manager client (tests, or a client with a custom config)."""
    global _client
    with _client_lock:
        _client = client
    clear_cache()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def get_secret(secret_id: str) -> str:
    """Return a secret string, cached for ``SECRET_CACHE_TTL_SECONDS``.

    Phase 1 checks the cache under the lock. Phase 2 calls Secrets Manager
    without the lock. Phase 3 writes the value back. Two concurrent misses may
    both fetch; the last writer wins with an equivalent value.
    """
    with _lock:
        entry = _cache.get(secret_id)
        if entry and (time.monotonic() - entry[1]) < _CACHE_TTL:
            return entry[0]
    response = _get_client().get_secret_value(SecretId=secret_id)
    value = str(response["SecretString"])
    with _lock:
        _cache[secret_id] = (value, time.monotonic())
    return value


def secret_name(prefix: str, name: str) -> str:
    """``<environment secrets prefix>/<name>``, the only shape a pattern reads."""
    if not name or "/" in name:
        raise ValueError("secret name is one path segment under the environment prefix")
    return f"{prefix.rstrip('/')}/{name}"


def get_ssm_parameter(parameter_name: str, *, client: Any | None = None) -> str:
    """Fetch a non-secret value (a gateway URL, a table name) published at deploy time."""
    if client is None:
        import boto3

        region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION"))
        client = boto3.client("ssm", region_name=region)
    try:
        response = client.get_parameter(Name=parameter_name)
        return str(response["Parameter"]["Value"])
    except client.exceptions.ParameterNotFound as exc:
        raise ValueError(f"SSM parameter not found: {parameter_name}") from exc
    except Exception as exc:
        raise ValueError(f"Failed to retrieve SSM parameter {parameter_name}: {type(exc).__name__}") from exc
