"""OAuth resource-server verification for an operator-provisioned public demo.

The external authorization server owns login, consent, PKCE and client
registration. This module never issues tokens or trusts caller roles.
"""

import json
import time
from pathlib import Path
from urllib.parse import urlsplit

import jwt
from pydantic import BaseModel, ConfigDict, Field, model_validator
from mcp.server.auth.provider import AccessToken

from ..calibration.store import AccessDenied, canonical


def https_url(value):
    u = urlsplit(value)
    if (
        u.scheme != "https"
        or not u.hostname
        or u.username
        or u.password
        or any(ord(c) <= 32 or ord(c) >= 127 for c in value)
        or u.query
        or u.fragment
        or u.hostname in ("localhost", "127.0.0.1", "::1")
    ):
        raise ValueError("PUBLIC_HTTPS_URL_REQUIRED")
    return value


class Binding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=1, max_length=240)
    client_id: str = Field(min_length=1, max_length=240)
    principal_id: str = Field(pattern=r"^SYN-REMOTE-[A-Za-z0-9_-]{1,80}$")
    roles: list[str] = Field(min_length=1, max_length=2)
    enabled: bool = True

    @model_validator(mode="after")
    def permitted_roles(self):
        if not set(self.roles) <= {"CALIBRATION_REVIEWER", "CALIBRATION_ADMIN"}:
            raise ValueError("REMOTE_ROLE_NOT_PERMITTED")
        if "CALIBRATION_REVIEWER" not in self.roles:
            raise ValueError("REVIEWER_ROLE_REQUIRED")
        return self


class RemoteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource: str
    issuer: str
    jwks_file: Path
    bindings: list[Binding] = Field(min_length=1, max_length=100)
    allowed_origins: list[str] = Field(default_factory=list, max_length=10)
    max_token_lifetime: int = Field(default=900, ge=60, le=3600)
    enable_public_synthetic_remote: bool = False

    @model_validator(mode="after")
    def validate_boundary(self):
        https_url(self.resource)
        https_url(self.issuer)
        if urlsplit(self.resource).path != "/mcp":
            raise ValueError("EXACT_MCP_RESOURCE_PATH_REQUIRED")
        if not self.enable_public_synthetic_remote:
            raise ValueError("PUBLIC_SYNTHETIC_REMOTE_NOT_ENABLED")
        for origin in self.allowed_origins:
            https_url(origin)
            if urlsplit(origin).path not in ("", "/"):
                raise ValueError("ORIGIN_MUST_NOT_INCLUDE_PATH")
        keys = [(b.subject, b.client_id) for b in self.bindings]
        if len(keys) != len(set(keys)):
            raise ValueError("DUPLICATE_REMOTE_IDENTITY_BINDING")
        return self

    @property
    def origin(self):
        u = urlsplit(self.resource)
        return f"{u.scheme}://{u.netloc}"

    @property
    def metadata_url(self):
        return self.origin + "/.well-known/oauth-protected-resource/mcp"

    @classmethod
    def load(cls, path):
        p = Path(path)
        if p.stat().st_size > 65536:
            raise ValueError("REMOTE_CONFIG_TOO_LARGE")
        return cls.model_validate_json(p.read_bytes())


class OAuthVerifier:
    def __init__(self, application, config):
        self.application, self.config = application, config
        if config.jwks_file.stat().st_size > 65536:
            raise ValueError("JWKS_TOO_LARGE")
        body = json.loads(config.jwks_file.read_bytes())
        self.keys = {}
        for item in body.get("keys", []):
            if (
                item.get("kty") != "RSA"
                or item.get("alg") != "RS256"
                or item.get("use") != "sig"
                or not item.get("kid")
                or set(item) & {"d", "p", "q", "dp", "dq", "qi"}
                or item["kid"] in self.keys
            ):
                raise ValueError("INVALID_PINNED_PUBLIC_JWK")
            key = jwt.PyJWK.from_dict(item).key
            if key.key_size < 2048:
                raise ValueError("RSA_KEY_TOO_SMALL")
            self.keys[item["kid"]] = key
        if not 1 <= len(self.keys) <= 10:
            raise ValueError("PINNED_PUBLIC_JWKS_REQUIRED")

    async def verify_token(self, token):
        if len(token) > 16384:
            return None
        try:
            header = jwt.get_unverified_header(token)
            if (
                header.get("alg") != "RS256"
                or header.get("typ") != "at+jwt"
                or set(header) & {"jku", "jwk", "x5u", "crit"}
            ):
                return None
            key = self.keys.get(header.get("kid"))
            if key is None:
                return None
            c = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self.config.issuer,
                audience=self.config.resource,
                options={
                    "require": [
                        "iss",
                        "aud",
                        "sub",
                        "exp",
                        "iat",
                        "jti",
                        "client_id",
                        "scope",
                    ],
                    "strict_aud": True,
                },
            )
            if (
                type(c["exp"]) is not int
                or type(c["iat"]) is not int
                or c["exp"] - c["iat"] > self.config.max_token_lifetime
                or c["exp"] <= c["iat"]
                or not isinstance(c["scope"], str)
                or "cdf:tools" not in c["scope"].split()
                or (c.get("azp") and c["azp"] != c["client_id"])
            ):
                return None
            binding = next(
                (
                    b
                    for b in self.config.bindings
                    if b.enabled
                    and b.subject == c["sub"]
                    and b.client_id == c["client_id"]
                ),
                None,
            )
            if binding is None:
                return None
            # Store only the bearer hash. Existing app/worker sessions retain expiry,
            # revocation and explicit per-case grants. Claims never grant a case.
            with self.application.lock, self.application.store.transaction():
                digest = self.application.sessions.register(
                    token,
                    principal_id=binding.principal_id,
                    roles=binding.roles,
                    client_id=binding.client_id,
                    ttl=max(1, c["exp"] - int(time.time())),
                )
                self.application.store.db.execute(
                    "UPDATE app_sessions SET expires_at=CASE WHEN expires_at<? THEN expires_at ELSE ? END WHERE session_id=?",
                    (c["exp"], c["exp"], digest),
                )
                p = self.application.sessions.resolve_id(digest)
                if (
                    p.reviewer.reviewer_id != binding.principal_id
                    or p.reviewer.roles != frozenset(binding.roles)
                    or p.client_id != binding.client_id
                ):
                    return None
            return AccessToken(
                token=token,
                client_id=binding.client_id,
                subject=binding.principal_id,
                scopes=["cdf:tools"],
                expires_at=c["exp"],
                resource=self.config.resource,
            )
        except (jwt.PyJWTError, AccessDenied, ValueError, TypeError, KeyError):
            return None
