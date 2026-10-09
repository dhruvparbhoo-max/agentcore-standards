from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from agentcore_front_door import ClaimMap, JwtVerifier, Unauthenticated, bearer, service_caller
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "https://issuer.example.invalid/pool"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(key: Any = KEY, **claims: Any) -> str:
    now = int(time.time())
    body = {
        "sub": "alice",
        "iss": ISSUER,
        "aud": "client-1",
        "iat": now,
        "exp": now + 300,
        "token_use": "id",
        "custom:team": "finance",
        "custom:tenant": "acme",
        "cognito:groups": ["staff", "managers"],
    }
    body.update(claims)
    return jwt.encode(body, key, algorithm="RS256")


def _verifier(**kwargs: Any) -> JwtVerifier:
    return JwtVerifier(
        issuer=ISSUER,
        audience="client-1",
        token_use="id",
        signing_key_for=lambda _token: KEY.public_key(),
        **kwargs,
    )


def test_claims_become_the_verified_caller() -> None:
    caller = _verifier().verify(_token())
    assert (caller.user_id, caller.team, caller.tenant, caller.roles) == (
        "alice",
        "finance",
        "acme",
        ("staff", "managers"),
    )
    assert caller.kind == "user"
    assert caller.token and caller.token not in repr(caller)


@pytest.mark.parametrize(
    "token",
    [
        _token(OTHER),
        _token(iss="https://evil.example.invalid"),
        _token(aud="someone-else"),
        _token(exp=int(time.time()) - 3600),
        _token(token_use="access"),
        _token(sub=""),
    ],
    ids=["wrong-key", "issuer", "audience", "expired", "token-use", "no-subject"],
)
def test_bad_tokens_are_refused(token: str) -> None:
    with pytest.raises(Unauthenticated):
        _verifier().verify(token)


def test_hs256_tokens_are_refused() -> None:
    forged = jwt.encode({"sub": "alice", "iss": ISSUER, "iat": 1, "exp": 2**31}, "s" * 32, algorithm="HS256")
    with pytest.raises(Unauthenticated):
        _verifier().verify(forged)


def test_claim_names_are_configurable() -> None:
    verifier = _verifier(claims=ClaimMap(user="email", team="dept", tenant="org", roles="scope"))
    caller = verifier.verify(_token(email="a@example.com", dept="ops", org="acme", scope="read write"))
    assert (caller.user_id, caller.team, caller.roles) == ("a@example.com", "ops", ("read", "write"))


def test_bearer_reads_the_authorization_header() -> None:
    assert bearer({"Authorization": "Bearer abc"}) == "abc"
    assert bearer({"authorization": "bearer xyz"}) == "xyz"
    assert bearer({"authorization": "Basic abc"}) == ""
    assert bearer(None) == ""


def test_service_caller_needs_a_consent_record() -> None:
    caller = service_caller({"service_identity": "ambient-worker", "consent_ref": "consent#42", "team": "ops"})
    assert caller.kind == "service" and caller.consent_ref == "consent#42"
    with pytest.raises(Unauthenticated, match="consent"):
        service_caller({"service_identity": "ambient-worker"})
    with pytest.raises(Unauthenticated, match="service_identity"):
        service_caller({"consent_ref": "c"})
