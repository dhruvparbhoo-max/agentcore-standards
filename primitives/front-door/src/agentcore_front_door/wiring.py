"""Build a ``FrontDoor`` from the Lambda environment the FrontDoor construct sets.

Names only arrive here: table names, the binding secret's name, the issuer.
Values (the secret itself, resource ids) are read at run time.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Mapping
from typing import Any

from agentcore_front_door.caller import ClaimMap, JwtVerifier
from agentcore_front_door.door import FrontDoor
from agentcore_front_door.obo import OboExchanger
from agentcore_front_door.policy import policies_from_env, settings_from_env
from agentcore_front_door.runtime import RuntimeInvoker
from agentcore_front_door.store import DynamoStore, MemoryStore, Store

STATE_TABLE = "FRONT_DOOR_STATE_TABLE"
AUDIT_TABLE = "FRONT_DOOR_AUDIT_TABLE"
BINDING_SECRET = "FRONT_DOOR_BINDING_SECRET_NAME"
LOCAL_BINDING_SECRET = "FRONT_DOOR_LOCAL_BINDING_SECRET"
ISSUER = "FRONT_DOOR_ISSUER"
AUDIENCE = "FRONT_DOOR_AUDIENCE"
TOKEN_USE = "FRONT_DOOR_TOKEN_USE"
JWKS_URL = "FRONT_DOOR_JWKS_URL"

_TTL_S = 600
_lock = threading.Lock()
_door: tuple[FrontDoor, float] | None = None
_verifier: JwtVerifier | None = None


def store_from_env(env: Mapping[str, str]) -> Store:
    state, audit = env.get(STATE_TABLE, ""), env.get(AUDIT_TABLE, "")
    if not state or not audit:
        return MemoryStore()
    return DynamoStore.from_names(state, audit, endpoint_url=env.get("DYNAMODB_ENDPOINT") or None)


def binding_secret(env: Mapping[str, str], *, client: Any | None = None) -> bytes:
    name = env.get(BINDING_SECRET, "")
    if not name:
        local = env.get(LOCAL_BINDING_SECRET, "")
        if not local:
            raise RuntimeError(f"set {BINDING_SECRET} (or {LOCAL_BINDING_SECRET} for make local)")
        return local.encode("utf-8")
    if client is None:
        import boto3

        client = boto3.client("secretsmanager")
    return str(client.get_secret_value(SecretId=name)["SecretString"]).encode("utf-8")


def build_door(env: Mapping[str, str] | None = None) -> FrontDoor:
    source = dict(os.environ if env is None else env)
    import boto3

    data_plane = boto3.client("bedrock-agentcore")
    return FrontDoor(
        policies=policies_from_env(source),
        settings=settings_from_env(source),
        store=store_from_env(source),
        binding_secret=binding_secret(source),
        invoker=RuntimeInvoker(data_plane),
        exchanger=OboExchanger(data_plane),
    )


def door() -> FrontDoor:
    """One door per warm Lambda, rebuilt every 10 minutes so a rotated binding secret is picked up."""
    global _door
    with _lock:
        if _door is None or time.monotonic() - _door[1] > _TTL_S:
            _door = (build_door(), time.monotonic())
        return _door[0]


def verifier() -> JwtVerifier:
    global _verifier
    with _lock:
        if _verifier is None:
            _verifier = JwtVerifier(
                issuer=os.environ[ISSUER],
                audience=os.environ.get(AUDIENCE, ""),
                jwks_url=os.environ.get(JWKS_URL, ""),
                token_use=os.environ.get(TOKEN_USE, ""),
                claims=ClaimMap(
                    user=os.environ.get("FRONT_DOOR_CLAIM_USER", "sub"),
                    team=os.environ.get("FRONT_DOOR_CLAIM_TEAM", "custom:team"),
                    tenant=os.environ.get("FRONT_DOOR_CLAIM_TENANT", "custom:tenant"),
                    roles=os.environ.get("FRONT_DOOR_CLAIM_ROLES", "cognito:groups"),
                ),
            )
        return _verifier


def reset() -> None:
    global _door, _verifier
    with _lock:
        _door = None
        _verifier = None
