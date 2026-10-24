"""TLS-only remote MCP resource server. Public synthetic data only; no OAuth issuer."""

import argparse
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import (
    BearerAuthBackend,
    RequireAuthMiddleware,
)
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .mcp_server import build_server
from .remote_auth import OAuthVerifier, RemoteConfig
from ..execution.service import ApplicationService


class RemoteAdmission:
    def __init__(self, app, origins):
        self.app, self.origins, self.windows = app, set(origins), OrderedDict()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        origin = headers.get(b"origin", b"").decode("latin1")
        if scope.get("scheme") != "https" or (origin and origin not in self.origins):
            return await JSONResponse(
                {"error": "HTTPS_AND_ALLOWED_ORIGIN_REQUIRED"}, status_code=403
            )(scope, receive, send)
        key = (scope.get("client") or ("unknown", 0))[0]
        window = int(time.time() // 60)
        old_window, count = self.windows.get(key, (window, 0))
        count = count + 1 if old_window == window else 1
        self.windows[key] = (window, count)
        self.windows.move_to_end(key)
        if len(self.windows) > 4096:
            self.windows.popitem(last=False)
        if count > 120:
            return await JSONResponse(
                {"error": "RATE_LIMIT_EXCEEDED"},
                status_code=429,
                headers={"Retry-After": "60"},
            )(scope, receive, send)
        # Apply the streamed body limit to /mcp before parsing/authentication too.
        size, chunks = 0, []
        while True:
            frame = await receive()
            if frame["type"] == "http.disconnect":
                return
            size += len(frame.get("body", b""))
            if size > 131072:
                return await JSONResponse(
                    {"error": "REQUEST_BODY_TOO_LARGE"}, status_code=413
                )(scope, receive, send)
            chunks.append(frame)
            if not frame.get("more_body", False):
                break

        async def replay():
            if chunks:
                return chunks.pop(0)
            return await receive()

        await self.app(scope, replay, send)


def remote_app(application, config):
    verifier = OAuthVerifier(application, config)
    host = urlsplit(config.resource).netloc
    origins = [config.origin, *config.allowed_origins]
    server = build_server(
        application,
        transport="remote-oauth",
        security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[host],
            allowed_origins=origins,
        ),
    )
    protocol = server.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app):
        async with server.session_manager.run():
            yield

    async def metadata(request):
        return JSONResponse(
            {
                "resource": config.resource,
                "authorization_servers": [config.issuer],
                "scopes_supported": ["cdf:tools"],
                "bearer_methods_supported": ["header"],
                "resource_name": "CDF public synthetic governance MCP",
            },
            headers={"Cache-Control": "no-store"},
        )

    async def health(request):
        return JSONResponse(
            {
                "mode": "PUBLIC_SYNTHETIC_DEMO",
                "authentication": "EXTERNAL_OAUTH_RESOURCE_SERVER",
                "private_activation": "DISABLED",
                "actual_client_registration": "NOT_ESTABLISHED_BY_HEALTH",
            }
        )

    return Starlette(
        routes=[
            Route("/.well-known/oauth-protected-resource/mcp", metadata),
            Route("/health", health),
            Mount(
                "/",
                app=RequireAuthMiddleware(
                    protocol, ["cdf:tools"], resource_metadata_url=config.metadata_url
                ),
            ),
        ],
        middleware=[
            Middleware(
                TrustedHostMiddleware,
                allowed_hosts=[urlsplit(config.resource).hostname],
            ),
            Middleware(RemoteAdmission, origins=origins),
            Middleware(AuthenticationMiddleware, backend=BearerAuthBackend(verifier)),
            Middleware(AuthContextMiddleware),
        ],
        lifespan=lifespan,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--tls-certfile", required=True)
    p.add_argument("--tls-keyfile", required=True)
    p.add_argument("--db", required=True)
    p.add_argument("--port", type=int, default=8443)
    args = p.parse_args()
    config = RemoteConfig.load(args.config)
    app = ApplicationService(
        args.db, token=""
    )  # nosec B106 - deliberately disables bootstrap bearer registration
    import uvicorn

    # Forwarded headers cannot upgrade plaintext requests or spoof client identity.
    uvicorn.run(
        remote_app(app, config),
        host="0.0.0.0",
        port=args.port,
        ssl_certfile=args.tls_certfile,  # nosec B104 - explicit TLS-only public listener
        ssl_keyfile=args.tls_keyfile,
        ssl_version=__import__("ssl").PROTOCOL_TLS_SERVER,
        proxy_headers=False,
        access_log=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
