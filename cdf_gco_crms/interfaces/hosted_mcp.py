"""Hosted MCP endpoint (/mcp) for the synthetic demo, authenticated by Supabase Auth.

Same tools and refusals as the local server (mcp_server.build_server): a model can read, run synthetic jobs and
save DRAFT calibration only; human decisions, submissions, checkpoint closure and issuance stay refused.
The bearer is a Supabase access token of a listed reviewer (hosted_auth). Serverless hosts may not run ASGI
lifespan, so each request gets its own stateless MCP server inside its own session manager.
OAuth discovery: /.well-known/oauth-protected-resource names Supabase Auth as the authorization server; an OAuth
client (for example a Claude connector) completes sign-in only if that Supabase project has its OAuth server enabled.
"""
from __future__ import annotations

from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.provider import AccessToken
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from ..calibration.store import AccessDenied
from . import hosted_auth
from .mcp_server import build_server


class HostedVerifier:
    def __init__(self, application, verifier, lock):
        self.application, self.verifier, self.lock = application, verifier, lock

    async def verify_token(self, token):
        try:
            with self.lock:
                p = hosted_auth.authenticate(self.application, self.verifier, token)
        except AccessDenied:
            return None
        return AccessToken(token=token, client_id=p.client_id, subject=p.reviewer.reviewer_id,
                           scopes=["cdf:tools"], expires_at=p.expires_at)


def _origin(scope) -> str:
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    host = headers.get("x-forwarded-host") or headers.get("host", "")
    return "https://" + host


def hosted_mcp(application, verifier, lock):
    def metadata(request):
        origin = _origin(request.scope)
        return JSONResponse({"resource": origin + "/mcp", "authorization_servers": [verifier.issuer],
                             "scopes_supported": ["cdf:tools"], "bearer_methods_supported": ["header"],
                             "resource_documentation": "Synthetic demo only; MAT is advisory; no issuance."})

    async def app(scope, receive, send):
        if scope["type"] == "lifespan":
            message = await receive()
            while message["type"] != "lifespan.shutdown":
                await send({"type": message["type"] + ".complete"})
                message = await receive()
            await send({"type": "lifespan.shutdown.complete"})
            return
        if scope["type"] != "http":
            return
        if scope.get("path") in ("/api/mcp", "/api/mcp/"):         # reached through the platform rewrite
            scope = {**scope, "path": "/mcp", "raw_path": b"/mcp"}
        server = build_server(application, security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
        protocol = server.streamable_http_app()
        starlette = Starlette(
            routes=[Route("/.well-known/oauth-protected-resource", metadata),
                    Route("/.well-known/oauth-protected-resource/mcp", metadata),
                    Mount("/", app=RequireAuthMiddleware(protocol, ["cdf:tools"],
                                                         resource_metadata_url=_origin(scope) + "/.well-known/oauth-protected-resource/mcp"))],
            middleware=[Middleware(AuthenticationMiddleware, backend=BearerAuthBackend(HostedVerifier(application, verifier, lock))),
                        Middleware(AuthContextMiddleware)])
        async with server.session_manager.run():
            await starlette(scope, receive, send)

    return app
