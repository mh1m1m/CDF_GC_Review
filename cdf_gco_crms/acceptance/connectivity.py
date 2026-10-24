"""Collect connectivity readiness; blocked external work never becomes acceptance PASS."""

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import anyio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from ..interfaces.remote_auth import RemoteConfig, https_url
from ..execution.receipt_audit import verify


def permitted(url, policy):
    http = policy.get("http_network_policy", {})
    return http.get("type") == "unrestricted" or urlsplit(url).hostname in {
        r.get("host") for r in http.get("egress_rules", [])
    }


def collect(config=None, *, policy=None, probe=False, database=None, case_id=None):
    report = {
        "schema": "CDF-REAL-CONNECTIVITY-1",
        "milestone": "BLOCKED_EXTERNAL",
        "private_activation": "DISABLED",
        "actual_chatgpt_registration": {
            "status": "BLOCKED_EXTERNAL",
            "reason": "ACCOUNT_PORTAL_REGISTRATION_AND_CORRELATED_CLIENT_CALL_NOT_AVAILABLE",
        },
        "actual_claude_registration": {
            "status": "BLOCKED_EXTERNAL",
            "reason": "ACCOUNT_CLIENT_REGISTRATION_AND_CORRELATED_CALL_NOT_AVAILABLE",
        },
        "provider_credentials": {
            "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
            "anthropic_configured": bool(
                os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")
            ),
        },
        "live_case_cross_interface_and_exports": {
            "status": "BLOCKED_EXTERNAL",
            "reason": "REQUIRES_SUCCESSFUL_REAL_MODEL_CASE; REGRESSION_FIXTURES_ARE_SEPARATE",
        },
    }
    if database and case_id:
        report["provenance"] = verify(database, case_id)
    else:
        report["provenance"] = {
            "status": "BLOCKED_EXTERNAL",
            "reason": "NO_COMPLETION_RECEIPT_SUPPLIED",
        }
    if config is None:
        report["public_mcp_deployment"] = {
            "status": "BLOCKED_EXTERNAL",
            "reason": "APPROVED_PUBLIC_RESOURCE_OAUTH_ISSUER_JWKS_TLS_AND_CLIENT_BINDINGS_NOT_CONFIGURED",
        }
        return report
    report["public_mcp_deployment"] = {
        "status": "CONFIGURATION_VALIDATED_NOT_DEPLOYED",
        "resource": config.resource,
        "issuer": config.issuer,
    }
    if not probe:
        report["external_sdk_probe"] = {
            "status": "NOT_RUN",
            "reason": "NETWORK_PROBE_NOT_REQUESTED",
        }
        return report
    issuer = urlsplit(config.issuer)
    metadata = urlunsplit(
        (
            issuer.scheme,
            issuer.netloc,
            "/.well-known/oauth-authorization-server" + issuer.path.rstrip("/"),
            "",
            "",
        )
    )
    if not policy or not all(permitted(u, policy) for u in (config.resource, metadata)):
        report["external_sdk_probe"] = {
            "status": "BLOCKED_EXTERNAL",
            "reason": "DESTINATION_POLICY_NOT_PERMITTED_OR_UNAVAILABLE",
        }
        return report
    try:
        # Inherited proxy and CA trust are preserved; redirects cannot select a new issuer.
        with httpx.Client(timeout=10, follow_redirects=False) as client:

            def read(url):
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > 65536:
                            raise ValueError("METADATA_SIZE_LIMIT")
                    return json.loads(body)

            resource = read(config.metadata_url)
            if resource.get("resource") != config.resource or resource.get(
                "authorization_servers"
            ) != [config.issuer]:
                raise ValueError("RESOURCE_METADATA_MISMATCH")
            authorization = read(metadata)
            if (
                authorization.get("issuer") != config.issuer
                or "S256"
                not in authorization.get("code_challenge_methods_supported", [])
                or "code" not in authorization.get("response_types_supported", [])
                or "authorization_code"
                not in authorization.get("grant_types_supported", [])
            ):
                raise ValueError("OAUTH_AUTHORIZATION_CODE_PKCE_METADATA_REQUIRED")
            for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
                https_url(authorization[field])
            report["public_mcp_deployment"]["status"] = "EXTERNAL_TLS_METADATA_VERIFIED"
        bearer = os.getenv("CDF_REMOTE_MCP_ACCESS_TOKEN")
        if not bearer:
            report["external_sdk_probe"] = {
                "status": "BLOCKED_EXTERNAL",
                "reason": "RESOURCE_SCOPED_OAUTH_ACCESS_TOKEN_NOT_PROVISIONED",
            }
            return report

        async def sdk():
            async with httpx.AsyncClient(
                headers={"Authorization": "Bearer " + bearer},
                timeout=20,
                follow_redirects=False,
            ) as client:
                async with streamable_http_client(
                    config.resource, http_client=client
                ) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        return len(tools.tools)

        count = anyio.run(sdk)
        report["external_sdk_probe"] = {
            "status": "PASS",
            "scope": "GENERIC_EXTERNAL_SDK_ONLY",
            "tools_discovered": count,
            "actual_chatgpt_or_claude_registration": False,
        }
    except Exception as exc:
        # Exception messages can contain tokens, server bodies or redirects.
        report["external_sdk_probe"] = {
            "status": "BLOCKED_EXTERNAL",
            "reason": "REMOTE_PROBE_FAILED",
            "error_class": type(exc).__name__,
        }
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config")
    p.add_argument("--probe-remote", action="store_true")
    p.add_argument("--network-policy", default="/etc/codex/network-policy.json")
    p.add_argument("--db")
    p.add_argument("--case")
    p.add_argument("--output", required=True)
    p.add_argument("--require-complete-milestone", action="store_true")
    args = p.parse_args()
    policy_path = Path(args.network_policy)
    config = RemoteConfig.load(args.config) if args.config else None
    policy = json.loads(policy_path.read_text()) if policy_path.is_file() else None
    report = collect(
        config,
        policy=policy,
        probe=args.probe_remote,
        database=args.db,
        case_id=args.case,
    )
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if args.require_complete_milestone and report["milestone"] != "PASS":
        raise SystemExit(3)


if __name__ == "__main__":
    main()
