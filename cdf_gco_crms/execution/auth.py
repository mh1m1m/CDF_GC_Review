"""Expiring server-side development sessions; never institutional authentication."""

from dataclasses import dataclass
import hashlib
import hmac
import time
from ..calibration.store import ReviewerContext, AccessDenied, canonical


@dataclass(frozen=True)
class Principal:
    session_id: str
    reviewer: ReviewerContext
    client_id: str
    expires_at: int


class DevelopmentSessions:
    def __init__(self, store):
        self.store = store
        store.db.execute(
            """CREATE TABLE IF NOT EXISTS app_sessions (
          session_id TEXT PRIMARY KEY, principal_id TEXT NOT NULL, roles_json TEXT NOT NULL,
          client_id TEXT NOT NULL, expires_at INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0)"""
        )
        store.db.commit()

    def register(
        self,
        token,
        *,
        principal_id="SYNTHETIC_ADMIN",
        roles=None,
        client_id="SYNTHETIC_LOCAL_OPERATOR",
        ttl=3600
    ):
        if len(token) < 32 or not 1 <= ttl <= 86400:
            raise AccessDenied("INVALID_DEVELOPMENT_SESSION_CONFIGURATION")
        roles = (
            ["CALIBRATION_ADMIN", "CALIBRATION_REVIEWER", "DNA_RULE_APPROVER"]
            if roles is None
            else roles
        )
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.store.transaction():
            self.store.db.execute(
                "INSERT OR IGNORE INTO app_sessions VALUES (?,?,?,?,?,0)",
                (
                    digest,
                    principal_id,
                    canonical(sorted(roles)),
                    client_id,
                    int(time.time()) + ttl,
                ),
            )
        return digest  # never included in client results or public evidence

    def resolve(self, token):
        if not token:
            raise AccessDenied("DEV_TOKEN_REQUIRED")
        return self.resolve_id(hashlib.sha256(token.encode()).hexdigest())

    def resolve_id(self, digest):
        import json

        row = self.store.db.execute(
            "SELECT * FROM app_sessions WHERE session_id=?", (digest,)
        ).fetchone()
        if row is None or row["revoked"] or row["expires_at"] <= int(time.time()):
            raise AccessDenied("INVALID_EXPIRED_OR_REVOKED_SESSION")
        return Principal(
            digest,
            ReviewerContext(
                row["principal_id"], frozenset(json.loads(row["roles_json"])), True
            ),
            row["client_id"],
            row["expires_at"],
        )
