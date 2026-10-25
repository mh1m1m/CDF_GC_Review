"""Hosted synthetic demo: Supabase Auth access tokens mapped to explicitly listed reviewer identities.

Supabase owns sign-in. This module only verifies its access tokens and never issues one:

* an asymmetrically signed token (ES256/RS256) is checked locally against the project's published JWKS; a
  shared-secret (HS256) token is never checked with a local secret (none is configured): Supabase Auth itself must
  confirm it (GET /auth/v1/user), so a leaked anon or publishable key cannot mint a session;
* the issuer must be ``<CDF_SUPABASE_URL>/auth/v1``, the audience ``authenticated``, the token unexpired;
* the e-mail in the token must be listed in ``CDF_HOSTED_REVIEWERS`` (an environment variable, never committed),
  which assigns the principal id and roles. Anyone else who signs up gets ``HOSTED_REVIEWER_NOT_LISTED``.

Each token is verified once; it then becomes an ordinary server-side session (``app_sessions``) that expires with the token, so the
rest of the engine (case grants, second review by a different identity, audit) is unchanged.
This is demo access control for synthetic data. It is not institutional SSO.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import jwt

from ..calibration.store import AccessDenied

ALGORITHMS = ["ES256", "RS256"]
ROLES = {"CALIBRATION_REVIEWER", "CALIBRATION_ADMIN", "DNA_RULE_APPROVER"}


@dataclass(frozen=True)
class Reviewer:
    email: str
    principal_id: str
    roles: tuple[str, ...]


def hosted_enabled() -> bool:
    return os.getenv("CDF_CALIBRATION_MODE", "") == "HOSTED_SYNTHETIC_DEMO"


def load_reviewers(raw: str | None = None) -> dict[str, Reviewer]:
    """``CDF_HOSTED_REVIEWERS``: JSON list of {"email", "principal_id", "roles"}."""
    items = json.loads(raw if raw is not None else os.getenv("CDF_HOSTED_REVIEWERS", "[]") or "[]")
    out: dict[str, Reviewer] = {}
    for item in items:
        email = str(item["email"]).strip().lower()
        principal = str(item["principal_id"])
        roles = tuple(sorted(set(item.get("roles") or ["CALIBRATION_REVIEWER"])))
        if not principal.startswith("SYN-HOSTED-") or not set(roles) <= ROLES or "@" not in email:
            raise ValueError("INVALID_HOSTED_REVIEWER_ENTRY")
        if email in out or principal in {r.principal_id for r in out.values()}:
            raise ValueError("DUPLICATE_HOSTED_REVIEWER")
        out[email] = Reviewer(email, principal, roles)
    return out


class SupabaseVerifier:
    def __init__(self, supabase_url: str, reviewers: dict[str, Reviewer], *, jwks_client=None, publishable_key=None,
                 user_lookup=None):
        u = urlsplit(supabase_url.rstrip("/"))
        if u.scheme != "https" or not u.hostname:
            raise ValueError("SUPABASE_HTTPS_URL_REQUIRED")
        self.issuer = supabase_url.rstrip("/") + "/auth/v1"
        self.reviewers = reviewers
        self._jwks = jwks_client or jwt.PyJWKClient(self.issuer + "/.well-known/jwks.json", cache_keys=True,
                                                    lifespan=600, timeout=5)
        self._lock = threading.Lock()
        self.publishable_key = publishable_key if publishable_key is not None else os.getenv("CDF_SUPABASE_PUBLISHABLE_KEY", "")
        self._user_lookup = user_lookup or self._auth_server_user

    def _auth_server_user(self, token: str) -> dict:
        import httpx

        if not self.publishable_key:
            raise AccessDenied("AUTH_SERVER_CHECK_NOT_CONFIGURED")
        response = httpx.get(self.issuer + "/user", timeout=5,
                             headers={"apikey": self.publishable_key, "Authorization": "Bearer " + token})
        if response.status_code != 200:
            raise AccessDenied("INVALID_ACCESS_TOKEN")
        return response.json()

    def verify(self, token: str) -> tuple[Reviewer, int]:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AccessDenied("INVALID_ACCESS_TOKEN") from exc
        if header.get("alg") == "HS256":
            return self._confirmed_by_auth_server(token)
        if header.get("alg") not in ALGORITHMS:
            raise AccessDenied("UNSUPPORTED_TOKEN_ALGORITHM")
        try:
            with self._lock:
                key = self._jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=ALGORITHMS, audience="authenticated", issuer=self.issuer,
                                options={"require": ["exp", "iat", "sub", "aud", "iss"]})
        except jwt.PyJWTError as exc:
            raise AccessDenied("INVALID_ACCESS_TOKEN") from exc
        return self._listed(claims.get("email")), int(claims["exp"])

    def _confirmed_by_auth_server(self, token: str):
        try:
            claims = jwt.decode(token, options={"verify_signature": False})   # read only after the server confirms
        except jwt.PyJWTError as exc:
            raise AccessDenied("INVALID_ACCESS_TOKEN") from exc
        if claims.get("iss") != self.issuer or claims.get("aud") != "authenticated":
            raise AccessDenied("INVALID_ACCESS_TOKEN")
        user = self._user_lookup(token)           # Supabase Auth checks the signature, expiry and revocation
        if str(user.get("id")) != str(claims.get("sub")) or int(claims.get("exp", 0)) <= time.time():
            raise AccessDenied("INVALID_ACCESS_TOKEN")
        return self._listed(user.get("email")), int(claims["exp"])

    def _listed(self, email) -> Reviewer:
        reviewer = self.reviewers.get(str(email or "").strip().lower())
        if reviewer is None:
            raise AccessDenied("HOSTED_REVIEWER_NOT_LISTED")
        return reviewer


def authenticate(application, verifier: SupabaseVerifier, token: str):
    """Resolve an existing session for this token, or verify it once and open one that expires with it."""
    try:
        return application.authenticate(token)
    except AccessDenied:
        pass
    reviewer, exp = verifier.verify(token)
    ttl = exp - int(time.time())
    if ttl <= 0:
        raise AccessDenied("INVALID_ACCESS_TOKEN")
    application.sessions.register(token, principal_id=reviewer.principal_id, roles=list(reviewer.roles),
                                  client_id="HOSTED_SUPABASE_WEB", ttl=min(ttl, 86400))
    return application.authenticate(token)
