"""Actual resource-server crypto/HTTP checks; local issuer fixture, not client registration."""

import json
import secrets
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

from cdf_gco_crms.execution.service import ApplicationService
from cdf_gco_crms.execution.contracts import Request
from cdf_gco_crms.interfaces.remote_auth import RemoteConfig, OAuthVerifier
from cdf_gco_crms.interfaces.remote_mcp import remote_app


@pytest.fixture
def remote(tmp_path, monkeypatch):
    monkeypatch.setenv("CDF_OPERATION_MODE", "PUBLIC_SYNTHETIC_DEMO")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="local-test-key", use="sig", alg="RS256")
    path = tmp_path / "jwks.json"
    path.write_text(json.dumps({"keys": [jwk]}))
    config = RemoteConfig(
        resource="https://mcp.example.test/mcp",
        issuer="https://issuer.example.test",
        jwks_file=path,
        enable_public_synthetic_remote=True,
        bindings=[
            {
                "subject": "local-fixture-subject",
                "client_id": "local-fixture-client",
                "principal_id": "SYN-REMOTE-REVIEWER",
                "roles": ["CALIBRATION_REVIEWER"],
            }
        ],
    )
    bootstrap = secrets.token_urlsafe(36)
    app = ApplicationService(tmp_path / "synthetic.sqlite", token=bootstrap)
    yield app, config, key, bootstrap
    app.close()


def token(remote, **changes):
    now = int(time.time())
    claims = {
        "iss": remote[1].issuer,
        "aud": remote[1].resource,
        "sub": "local-fixture-subject",
        "client_id": "local-fixture-client",
        "scope": "cdf:tools",
        "jti": secrets.token_hex(16),
        "iat": now,
        "exp": now + 300,
        **changes,
    }
    return jwt.encode(
        claims,
        remote[2],
        algorithm="RS256",
        headers={"kid": "local-test-key", "typ": "at+jwt"},
    )


def rpc(client, bearer, method, params=None, identifier=1):
    return client.post(
        "/mcp",
        headers={
            "Authorization": "Bearer " + bearer,
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": identifier,
            "method": method,
            "params": params or {},
        },
    )


def test_metadata_401_crypto_discovery_and_no_development_bearer(remote):
    app, config, _, bootstrap = remote
    with TestClient(remote_app(app, config), base_url="https://mcp.example.test") as c:
        meta = c.get("/.well-known/oauth-protected-resource/mcp")
        assert meta.status_code == 200 and meta.json()["resource"] == config.resource
        assert meta.json()["authorization_servers"] == [config.issuer]
        r = c.post("/mcp", json={})
        assert (
            r.status_code == 401
            and config.metadata_url in r.headers["www-authenticate"]
        )
        assert rpc(c, bootstrap, "tools/list").status_code == 401
        t = token(remote)
        r = rpc(
            c,
            t,
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "INDEPENDENT_LOCAL_TEST", "version": "1"},
            },
        )
        assert (
            r.status_code == 200
            and r.json()["result"]["serverInfo"]["name"]
            == "CDF Governance Intelligence"
        )
        r = rpc(c, t, "tools/list")
        assert len(r.json()["result"]["tools"]) == 24
        assert t not in str(
            [tuple(x) for x in app.store.db.execute("SELECT * FROM app_sessions")]
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "https://other.example.test"},
        {"aud": "https://other.example.test/mcp"},
        {"aud": ["https://mcp.example.test/mcp"]},
        {"exp": 0},
        {"iat": int(time.time()) + 300},
        {"exp": int(time.time()) + 7200},
        {"scope": "openid profile"},
        {"sub": "unprovisioned"},
        {"client_id": "forged-client"},
        {"azp": "different-client"},
        {"exp": True},
    ],
)
def test_invalid_claims_are_denied(remote, changes):
    with TestClient(
        remote_app(remote[0], remote[1]), base_url="https://mcp.example.test"
    ) as c:
        assert rpc(c, token(remote, **changes), "tools/list").status_code == 401


def test_signed_roles_never_grant_admin_and_foreign_cases_denied(remote):
    app, config, _, bootstrap = remote
    app.invoke(
        "cdf_create_case",
        Request(case_id="SYN-OAUTH-001", idempotency_key="oauth-case-001"),
        app.authenticate(bootstrap),
    )
    with TestClient(remote_app(app, config), base_url="https://mcp.example.test") as c:
        t = token(remote, roles=["CALIBRATION_ADMIN"], case_ids=["SYN-OAUTH-001"])
        r = rpc(
            c,
            t,
            "tools/call",
            {
                "name": "cdf_create_case",
                "arguments": {
                    "request": {
                        "case_id": "SYN-FORGED-001",
                        "idempotency_key": "forged-create-001",
                    }
                },
            },
        ).json()
        assert r["result"]["isError"] is True
        r = rpc(
            c,
            t,
            "tools/call",
            {
                "name": "cdf_get_case_status",
                "arguments": {"request": {"case_id": "SYN-OAUTH-001"}},
            },
        ).json()
        assert r["result"]["isError"] is True
        assert not app.store.db.execute(
            "SELECT 1 FROM app_cases WHERE case_id='SYN-FORGED-001'"
        ).fetchone()
        with app.store.transaction():
            app.store.db.execute(
                "UPDATE app_sessions SET revoked=1 WHERE principal_id='SYN-REMOTE-REVIEWER'"
            )
        assert rpc(c, t, "tools/list").status_code == 401


def test_transport_host_origin_body_limits_and_token_type(remote):
    app, config, key, _ = remote
    with TestClient(remote_app(app, config), base_url="https://mcp.example.test") as c:
        assert (
            c.get("/health", headers={"Host": "attacker.example.test"}).status_code
            == 400
        )
        assert (
            c.get(
                "/health", headers={"Origin": "https://attacker.example.test"}
            ).status_code
            == 403
        )
        assert (
            c.post("/mcp", content=iter([b"x" * 70000, b"y" * 70000])).status_code
            == 413
        )
        payload = jwt.decode(token(remote), options={"verify_signature": False})
        for h in (
            {"kid": "local-test-key", "typ": "JWT"},
            {"kid": "unknown", "typ": "at+jwt"},
            {
                "kid": "local-test-key",
                "typ": "at+jwt",
                "jku": "https://attacker.example.test/jwks",
            },
        ):
            assert (
                rpc(
                    c,
                    jwt.encode(payload, key, algorithm="RS256", headers=h),
                    "tools/list",
                ).status_code
                == 401
            )
    with TestClient(remote_app(app, config), base_url="http://mcp.example.test") as c:
        assert (
            c.get("/health", headers={"X-Forwarded-Proto": "https"}).status_code == 403
        )


def test_private_mode_and_unsafe_configuration_fail_before_activation(
    remote, monkeypatch, tmp_path
):
    data = remote[1].model_dump()
    for resource in (
        "http://mcp.example.test/mcp",
        "https://user:password@mcp.example.test/mcp",
        "https://mcp.example.test/wrong",
    ):
        with pytest.raises(ValueError):
            RemoteConfig.model_validate({**data, "resource": resource})
    with pytest.raises(ValueError):
        RemoteConfig.model_validate({**data, "enable_public_synthetic_remote": False})
    monkeypatch.setenv("CDF_OPERATION_MODE", "PRIVATE_INSTITUTIONAL")
    with pytest.raises(Exception, match="PRIVATE_HTTP_ACTIVATION_DISABLED"):
        ApplicationService(tmp_path / "other.sqlite")
