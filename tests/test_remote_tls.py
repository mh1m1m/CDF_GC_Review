"""Actual TLS socket and independent SDK; entirely local test identity/issuer."""

import datetime as dt
import ipaddress
import json
import os
import socket
import subprocess
import sys
import time

import anyio
import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from test_remote_mcp import remote, token


def test_actual_tls_and_oauth_with_independent_local_sdk(remote, tmp_path):
    app, config, key, _ = remote
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = config.model_copy(
        update={"resource": f"https://mcp.example.test:{port}/mcp"}
    )
    remote = (app, config, key, remote[3])
    bearer = token(remote)
    subject = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "LOCAL TEST MCP ONLY")]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1))
        .not_valid_after(dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA256())
    )
    certfile = tmp_path / "local-cert.pem"
    keyfile = tmp_path / "local-key.pem"
    configfile = tmp_path / "remote.json"
    certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    keyfile.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    keyfile.chmod(0o600)
    configfile.write_text(config.model_dump_json())
    env = {**os.environ, "CDF_CALIBRATION_DEV_TOKEN": ""}
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "cdf_gco_crms.interfaces.remote_mcp",
            "--config",
            str(configfile),
            "--db",
            str(app.store.path),
            "--port",
            str(port),
            "--tls-certfile",
            str(certfile),
            "--tls-keyfile",
            str(keyfile),
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    import ssl

    context = ssl.create_default_context(cafile=str(certfile))
    origin = f"https://127.0.0.1:{port}"
    try:
        with httpx.Client(
            verify=context,
            trust_env=False,
            headers={"Host": f"mcp.example.test:{port}"},
            timeout=1,
        ) as client:
            for _ in range(80):
                try:
                    if client.get(origin + "/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                assert process.poll() is None, "TLS test server exited"
                time.sleep(0.1)
            else:
                raise AssertionError("TLS test server not ready")
            assert (
                client.get(origin + "/.well-known/oauth-protected-resource/mcp").json()[
                    "resource"
                ]
                == config.resource
            )
            assert client.post(origin + "/mcp", json={}).status_code == 401
            with __import__("pytest").raises(httpx.TransportError):
                httpx.get(
                    origin + "/health", trust_env=False, timeout=1
                )  # Untrusted test CA must fail.

        async def sdk():
            async with httpx.AsyncClient(
                verify=context,
                trust_env=False,
                headers={
                    "Host": f"mcp.example.test:{port}",
                    "Authorization": "Bearer " + bearer,
                },
            ) as client:
                async with streamable_http_client(
                    origin + "/mcp", http_client=client
                ) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        assert len(tools.tools) == 24

        anyio.run(sdk)
    finally:
        process.terminate()
        process.wait(timeout=10)
