"""Who is calling. A person with a verified token, or a service acting for a stored job.

The JWKS verifiers are copied from aws-samples/sample-agent-platform-with-agentcore
``backend/app/auth.py`` (MIT-0): PyJWT ``PyJWKClient`` with cached keys, RS256
only, issuer and audience checked, and ``token_use`` checked for Cognito ID
tokens. The Cognito and generic OIDC verifiers are one class here, configured
by issuer. Team, tenant, and roles come from claims, never from the request body.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import jwt
from jwt import PyJWKClient

USER: Literal["user"] = "user"
SERVICE: Literal["service"] = "service"
_MAX_ID = 128


class Unauthenticated(Exception):
    """No caller, a bad token, or a service record without consent."""


@dataclass(frozen=True)
class VerifiedCaller:
    """The identity every later step uses. ``token`` is the raw user token for the on-behalf-of exchange."""

    user_id: str
    kind: Literal["user", "service"]
    team: str = ""
    tenant: str = ""
    roles: tuple[str, ...] = ()
    token: str = field(default="", repr=False)
    consent_ref: str = ""
    on_behalf_of: str = ""

    def __post_init__(self) -> None:
        _check_id(self.user_id, "user_id")
        if self.kind == SERVICE and not self.consent_ref:
            raise Unauthenticated("a service caller must name the stored consent it acts under")


@dataclass(frozen=True)
class ClaimMap:
    """Which claims carry the user id, team, tenant, and roles."""

    user: str = "sub"
    team: str = "custom:team"
    tenant: str = "custom:tenant"
    roles: str = "cognito:groups"


SigningKeyFor = Callable[[str], Any]


class JwtVerifier:
    """Verify a bearer token against one issuer's JWKS."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str = "",
        jwks_url: str = "",
        token_use: str = "",
        claims: ClaimMap | None = None,
        signing_key_for: SigningKeyFor | None = None,
        leeway_s: int = 30,
    ) -> None:
        if not issuer:
            raise ValueError("issuer is required")
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.token_use = token_use
        self.claims = claims or ClaimMap()
        self.leeway_s = leeway_s
        self._jwks_url = jwks_url
        self._client: PyJWKClient | None = None
        self._signing_key_for = signing_key_for

    @classmethod
    def cognito(cls, *, region: str, pool_id: str, client_id: str, claims: ClaimMap | None = None) -> JwtVerifier:
        """Cognito ID tokens. Same issuer, audience, and ``token_use`` checks as the sample."""
        issuer = f"https://cognito-idp.{region}.amazonaws.com/{pool_id}"
        return cls(
            issuer=issuer,
            audience=client_id,
            jwks_url=f"{issuer}/.well-known/jwks.json",
            token_use="id",
            claims=claims,
        )

    def verify(self, token: str) -> VerifiedCaller:
        if not token:
            raise Unauthenticated("a bearer token is required")
        options: Any = {"require": ["exp", "iat", "iss"]}
        kwargs: dict[str, Any] = {"algorithms": ["RS256"], "issuer": self.issuer, "leeway": self.leeway_s}
        if self.audience:
            kwargs["audience"] = self.audience
        else:
            options["verify_aud"] = False
        try:
            key = self._key(token)
            claims = jwt.decode(token, key, options=options, **kwargs)
        except jwt.PyJWTError as exc:
            raise Unauthenticated(f"token rejected: {type(exc).__name__}") from exc
        if self.token_use and claims.get("token_use") != self.token_use:
            raise Unauthenticated(f"expected a {self.token_use} token")
        return VerifiedCaller(
            user_id=_claim_text(claims, self.claims.user),
            kind=USER,
            team=_claim_text(claims, self.claims.team, required=False),
            tenant=_claim_text(claims, self.claims.tenant, required=False),
            roles=_claim_list(claims, self.claims.roles),
            token=token,
        )

    def _key(self, token: str) -> Any:
        if self._signing_key_for is not None:
            return self._signing_key_for(token)
        if self._client is None:
            self._client = PyJWKClient(self._jwks_url or _discover_jwks(self.issuer), cache_keys=True)
        return self._client.get_signing_key_from_jwt(token).key


def bearer(headers: Mapping[str, str] | None) -> str:
    """The token from ``Authorization: Bearer ...``, or empty."""
    for name, value in (headers or {}).items():
        if name.lower() == "authorization" and isinstance(value, str):
            scheme, _, rest = value.strip().partition(" ")
            if scheme.lower() == "bearer":
                return rest.strip()
    return ""


def service_caller(job: Mapping[str, Any]) -> VerifiedCaller:
    """The identity recorded on a job row. A job with no consent record does not run."""
    identity = job.get("service_identity")
    consent = job.get("consent_ref")
    if not isinstance(identity, str) or not identity:
        raise Unauthenticated("job has no service_identity")
    if not isinstance(consent, str) or not consent:
        raise Unauthenticated("job has no consent_ref")
    owner = job.get("on_behalf_of")
    return VerifiedCaller(
        user_id=identity,
        kind=SERVICE,
        team=str(job.get("team", "")),
        tenant=str(job.get("tenant", "")),
        consent_ref=consent,
        on_behalf_of=owner if isinstance(owner, str) else "",
    )


def _discover_jwks(issuer: str) -> str:
    if not issuer.startswith("https://"):
        raise Unauthenticated("issuer must be https")
    with urllib.request.urlopen(f"{issuer}/.well-known/openid-configuration", timeout=5) as resp:
        return str(json.load(resp)["jwks_uri"])


def _claim_text(claims: Mapping[str, Any], name: str, *, required: bool = True) -> str:
    value = claims.get(name)
    if isinstance(value, str) and value:
        return value
    if required:
        raise Unauthenticated(f"token has no {name} claim")
    return ""


def _claim_list(claims: Mapping[str, Any], name: str) -> tuple[str, ...]:
    value = claims.get(name)
    if isinstance(value, str):
        return tuple(part for part in value.replace(",", " ").split() if part)
    if isinstance(value, Sequence):
        return tuple(str(part) for part in value if isinstance(part, str) and part)
    return ()


def _check_id(value: str, label: str) -> None:
    if not value or len(value) > _MAX_ID or any(ord(char) < 33 for char in value):
        raise Unauthenticated(f"invalid {label}")
