"""Hosted MCP endpoint: Supabase-token bearer, OAuth discovery metadata, same refusals as the local server."""
import json
import threading
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from starlette.testclient import TestClient

from cdf_gco_crms.execution.contracts import Request
from cdf_gco_crms.execution.service import ApplicationService
from cdf_gco_crms.interfaces import hosted_auth
from cdf_gco_crms.interfaces.hosted_mcp import hosted_mcp

URL = "https://example-project.supabase.co"
KEY = ec.generate_private_key(ec.SECP256R1())
ACCEPT = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


class StubJwks:
    def get_signing_key_from_jwt(self, token):
        return type("K", (), {"key": KEY.public_key()})()


def bearer(email="owner@example.invalid"):
    now = int(time.time())
    return jwt.encode({"sub": "u1", "aud": "authenticated", "iss": URL + "/auth/v1", "iat": now, "exp": now + 600,
                       "email": email}, KEY, algorithm="ES256", headers={"kid": "k"})


def rpc(client, method, params, token, ident=1):
    body = {"jsonrpc": "2.0", "id": ident, "method": method, "params": params}
    return client.post("/mcp", headers={**ACCEPT, "Authorization": "Bearer " + token}, content=json.dumps(body))


def test_hosted_mcp_discovery_auth_tools_and_refusals(tmp_path, monkeypatch):
    monkeypatch.setenv("CDF_CALIBRATION_DEV_TOKEN", "")
    app = ApplicationService(tmp_path / "synthetic.sqlite", token="")
    reviewers = hosted_auth.load_reviewers(json.dumps([{"email": "owner@example.invalid", "principal_id": "SYN-HOSTED-OWNER",
                                                        "roles": ["CALIBRATION_ADMIN", "CALIBRATION_REVIEWER"]}]))
    verifier = hosted_auth.SupabaseVerifier(URL, reviewers, jwks_client=StubJwks())
    client = TestClient(hosted_mcp(app, verifier, threading.RLock()), base_url="https://demo.example.invalid")
    try:
        meta = client.get("/.well-known/oauth-protected-resource/mcp").json()
        assert meta["authorization_servers"] == [URL + "/auth/v1"] and meta["resource"].endswith("/mcp")
        unauth = client.post("/mcp", headers=ACCEPT, content="{}")
        assert unauth.status_code == 401 and "resource_metadata" in unauth.headers.get("www-authenticate", "")
        assert rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                          "clientInfo": {"name": "test", "version": "1"}}, bearer("stranger@example.invalid")).status_code == 401
        token = bearer()
        init = rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                          "clientInfo": {"name": "test", "version": "1"}}, token)
        assert init.status_code == 200 and init.json()["result"]["serverInfo"]["name"] == "CDF Governance Intelligence"
        tools = rpc(client, "tools/list", {}, token, 2).json()["result"]["tools"]
        assert {"cdf_get_case_status", "cdf_calibrate_observation", "cdf_governance_copilot"} <= {t["name"] for t in tools}
        p = app.authenticate(token)
        app.invoke("cdf_create_case", Request(case_id="SYN-MCP-HOSTED-001", idempotency_key="hosted-mcp-create-001"), p)
        status = rpc(client, "tools/call", {"name": "cdf_get_case_status", "arguments": {"request": {"case_id": "SYN-MCP-HOSTED-001"}}}, token, 3)
        assert status.json()["result"]["structuredContent"]["ok"] is True
        refused = rpc(client, "tools/call", {"name": "cdf_governance_copilot", "arguments": {
            "operation": "decision", "request": {"case_id": "SYN-MCP-HOSTED-001", "observation_id": "SYN-MCP-HOSTED-001-O01", "action": "ACCEPT", "idempotency_key": "hosted-mcp-decision-001",
                                                 "expected_evidence_hash": "0" * 64, "rationale": "AI attempt"}}}, token, 4).json()
        assert refused["result"]["isError"] and "HUMAN_DECISION_REQUIRES_DIRECT_HUMAN_INTERFACE" in json.dumps(refused)
    finally:
        app.close()
