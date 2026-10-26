"""Hosted demo sign-in: Supabase access tokens, asymmetric only, listed reviewers only."""
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from cdf_gco_crms.calibration.store import AccessDenied
from cdf_gco_crms.execution.service import ApplicationService
from cdf_gco_crms.interfaces import hosted_auth

URL = "https://example-project.supabase.co"
KEY = ec.generate_private_key(ec.SECP256R1())
REVIEWERS = json.dumps([
    {"email": "Reviewer.One@example.invalid", "principal_id": "SYN-HOSTED-R1",
     "roles": ["CALIBRATION_ADMIN", "CALIBRATION_REVIEWER"]},
    {"email": "reviewer.two@example.invalid", "principal_id": "SYN-HOSTED-R2", "roles": ["CALIBRATION_REVIEWER"]},
])


class StubJwks:
    def get_signing_key_from_jwt(self, token):
        return type("K", (), {"key": KEY.public_key()})()


def token(email="reviewer.one@example.invalid", *, iss=URL + "/auth/v1", alg="ES256", key=KEY, exp=600):
    now = int(time.time())
    claims = {"sub": "00000000-0000-0000-0000-000000000001", "aud": "authenticated", "iss": iss,
              "iat": now, "exp": now + exp, "email": email, "role": "authenticated"}
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": "test"})


def refuse(token):
    raise AccessDenied("INVALID_ACCESS_TOKEN")      # the auth server rejects a token it did not issue


@pytest.fixture
def verifier():
    return hosted_auth.SupabaseVerifier(URL, hosted_auth.load_reviewers(REVIEWERS), jwks_client=StubJwks(),
                                        user_lookup=refuse)


def test_shared_secret_token_is_accepted_only_when_supabase_auth_confirms_it():
    secret = "a-shared-secret-of-sufficient-length-for-hs256"
    t = token(alg="HS256", key=secret)
    confirmed = hosted_auth.SupabaseVerifier(
        URL, hosted_auth.load_reviewers(REVIEWERS), jwks_client=StubJwks(),
        user_lookup=lambda _t: {"id": "00000000-0000-0000-0000-000000000001", "email": "reviewer.one@example.invalid"})
    assert confirmed.verify(t)[0].principal_id == "SYN-HOSTED-R1"
    other_user = hosted_auth.SupabaseVerifier(
        URL, hosted_auth.load_reviewers(REVIEWERS), jwks_client=StubJwks(),
        user_lookup=lambda _t: {"id": "someone-else", "email": "reviewer.one@example.invalid"})
    with pytest.raises(AccessDenied, match="INVALID_ACCESS_TOKEN"):
        other_user.verify(t)


def test_listed_reviewer_is_mapped_case_insensitively(verifier):
    reviewer, exp = verifier.verify(token())
    assert reviewer.principal_id == "SYN-HOSTED-R1" and exp > time.time()


@pytest.mark.parametrize("bad, code", [
    (lambda: token("someone@example.invalid"), "HOSTED_REVIEWER_NOT_LISTED"),
    (lambda: token(iss="https://other.supabase.co/auth/v1"), "INVALID_ACCESS_TOKEN"),
    (lambda: token(alg="HS256", key="a-shared-secret-of-sufficient-length-for-hs256"), "INVALID_ACCESS_TOKEN"),
    (lambda: token(exp=-60), "INVALID_ACCESS_TOKEN"),
    (lambda: "not-a-jwt", "INVALID_ACCESS_TOKEN"),
])
def test_refusals(verifier, bad, code):
    with pytest.raises(AccessDenied, match=code):
        verifier.verify(bad())


def test_verified_token_becomes_an_expiring_session_with_the_listed_roles(verifier, tmp_path):
    app = ApplicationService(tmp_path / "synthetic.sqlite", token="")
    try:
        t = token()
        p = hosted_auth.authenticate(app, verifier, t)
        assert p.reviewer.reviewer_id == "SYN-HOSTED-R1" and p.client_id == "HOSTED_SUPABASE_WEB"
        assert "CALIBRATION_ADMIN" in p.reviewer.roles and p.expires_at <= int(time.time()) + 600
        two = hosted_auth.authenticate(app, verifier, token("reviewer.two@example.invalid"))
        assert two.reviewer.reviewer_id != p.reviewer.reviewer_id, "distinct people stay distinct identities"
    finally:
        app.close()


def test_reviewer_entries_are_validated():
    with pytest.raises(ValueError):
        hosted_auth.load_reviewers(json.dumps([{"email": "a@b.c", "principal_id": "ADMIN", "roles": ["CALIBRATION_ADMIN"]}]))
    with pytest.raises(ValueError):
        hosted_auth.load_reviewers(json.dumps([{"email": "a@b.c", "principal_id": "SYN-HOSTED-1", "roles": ["SUPERUSER"]}]))
