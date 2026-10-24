"""Official MCP SDK: authenticated Streamable HTTP and isolated stdio.

Development bearer sessions are pre-provisioned, scoped and expiring. No fake
OAuth issuer is advertised. Remote ChatGPT OAuth/HTTPS registration remains an
external deployment prerequisite; private institutional HTTP is never enabled.
"""

from __future__ import annotations
import argparse
from copy import deepcopy
from contextlib import asynccontextmanager
import json
import os

from pydantic import create_model, ValidationError
from pydantic_core import PydanticUndefined
from mcp.server.fastmcp import FastMCP, Context
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.middleware.bearer_auth import (
    BearerAuthBackend,
    RequireAuthMiddleware,
)
from mcp.server.auth.middleware.auth_context import (
    AuthContextMiddleware,
    get_access_token,
)
from mcp.types import ToolAnnotations, CallToolResult, TextContent
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from ..execution.service import ApplicationService, Conflict
from ..execution.contracts import Request, Result, TOOLS
from ..calibration.store import AccessDenied, CalibrationError

FIELDS = {
    "recover": {"case_id", "idempotency_key"},
    "create": {"case_id", "source", "idempotency_key"},
    "review": {"case_id", "executor", "timeout", "idempotency_key"},
    "debate": {"case_id", "executor", "timeout", "idempotency_key"},
    "probe": {"case_id", "executor", "timeout", "idempotency_key"},
    "case": {"case_id"},
    "observations": {"case_id", "cursor", "limit"},
    "trace": {"case_id", "cursor", "limit"},
    "job": {"case_id", "job_id"},
    "job_result": {"case_id", "job_id"},
    "cancel": {"case_id", "job_id", "idempotency_key"},
    "authority": {"case_id", "query", "limit"},
    "organization": {"case_id", "query", "limit"},
    "references": {"case_id"},
    "history": {"case_id", "cursor", "limit"},
    "calibrate": {
        "case_id",
        "observation_id",
        "decision",
        "rationale",
        "expected_evidence_hash",
        "status",
        "reasons",
        "evidence_refs",
        "idempotency_key",
    },
    "metrics": {"case_id"},
    "gate": {"case_id"},
    "docx": {"case_id", "timeout", "idempotency_key", "issue"},
    "xlsx": {"case_id", "timeout", "idempotency_key", "issue"},
    "pdf": {"case_id", "timeout", "idempotency_key", "issue"},
    "artifact": {"case_id", "artifact_id", "cursor"},
    "artifact_status": {"case_id", "artifact_id"},
}


class SessionVerifier:
    def __init__(self, application):
        self.application = application

    async def verify_token(self, token):
        try:
            p = self.application.authenticate(token)
        except AccessDenied:
            return None
        return AccessToken(
            token=token,
            client_id=p.client_id,
            subject=p.reviewer.reviewer_id,
            scopes=["cdf:tools"],
            expires_at=p.expires_at,
        )


def build_server(
    application: ApplicationService, *, port=8766, transport="streamable-http"
):
    server = FastMCP(
        "CDF Governance Intelligence",
        host="127.0.0.1",
        port=port,
        json_response=True,
        stateless_http=True,
        max_request_body_size=131072,
        instructions="Synthetic development only. MAT is advisory. Tools never authorize institutional issuance.",
    )
    for name, (action, role, mutation) in TOOLS.items():
        fields = {}
        for key in FIELDS[action]:
            field = deepcopy(Request.model_fields[key])
            if key == "case_id" and action not in (
                "job",
                "job_result",
                "cancel",
                "artifact",
                "artifact_status",
            ):
                field.default = PydanticUndefined
            if key in (
                "job_id",
                "artifact_id",
                "observation_id",
                "expected_evidence_hash",
            ):
                field.default = PydanticUndefined
            fields[key] = (field.annotation, field)
        args_model = create_model(
            name + "_Arguments",
            __config__={"extra": "forbid", "hide_input_in_errors": True},
            **fields,
        )

        def register(tool_name, arg_type, operation, required_role, is_mutation):
            async def handler(request, ctx: Context) -> Result:
                try:
                    if transport == "stdio":
                        token = os.getenv("CDF_CALIBRATION_DEV_TOKEN", "")
                    else:
                        access = get_access_token()
                        if access is None:
                            raise AccessDenied("MCP_AUTHENTICATION_REQUIRED")
                        token = access.token
                    principal = application.authenticate(token)
                    result = application.invoke(
                        tool_name,
                        Request.model_validate(request.model_dump()),
                        principal,
                        transport="MCP_" + transport.upper(),
                    )
                    if operation in (
                        "review",
                        "debate",
                        "probe",
                        "docx",
                        "xlsx",
                        "pdf",
                    ):
                        from ..execution.jobs import launch

                        launch(application, result["data"]["job_id"], principal)
                    if len(json.dumps(result, ensure_ascii=False).encode()) > 524288:
                        raise CalibrationError("OUTPUT_LIMIT_USE_PAGINATION")
                    return Result.model_validate(result)
                except (AccessDenied, CalibrationError, ValidationError) as exc:
                    error = Result(
                        ok=False,
                        operation=tool_name,
                        error={
                            "code": (
                                "INPUT_VALIDATION_FAILED"
                                if isinstance(exc, ValidationError)
                                else str(exc)
                            ),
                            "type": type(exc).__name__,
                            "retryable": False,
                        },
                    ).model_dump()
                    return CallToolResult(
                        isError=True,
                        content=[TextContent(type="text", text=json.dumps(error))],
                        structuredContent=error,
                    )

            handler.__name__ = tool_name
            handler.__annotations__["request"] = arg_type
            server.tool(
                name=tool_name,
                description=f"{operation}: real shared application service. Permission: {required_role}. Private activation and official issue are disabled.",
                annotations=ToolAnnotations(
                    readOnlyHint=not is_mutation,
                    destructiveHint=operation == "cancel",
                    idempotentHint=not is_mutation,
                    openWorldHint=operation in ("review", "debate", "probe"),
                ),
                structured_output=True,
            )(handler)

        register(name, args_model, action, role, mutation)
    from ..copilot.service import CopilotService
    from ..copilot.contracts import Input as CopilotInput, Operation as CopilotOperation
    copilot=CopilotService(application)
    async def conversation(operation: CopilotOperation, request: CopilotInput, ctx: Context)->Result:
        try:
            access=get_access_token() if transport!='stdio' else None
            token=os.getenv('CDF_CALIBRATION_DEV_TOKEN','') if transport=='stdio' else (access.token if access else '')
            result=copilot.execute(operation,request.model_dump(),application.authenticate(token),transport='MCP_COPILOT_'+transport.upper())
            if len(json.dumps(result,ensure_ascii=False).encode())>524288:raise CalibrationError('OUTPUT_LIMIT_USE_PAGINATION')
            return Result.model_validate(result)
        except (CalibrationError,AccessDenied,ValidationError) as exc:
            data=Result(ok=False,operation='cdf_governance_copilot',error={'code':'INPUT_VALIDATION_FAILED' if isinstance(exc,ValidationError) else str(exc),'type':type(exc).__name__,'retryable':False}).model_dump()
            return CallToolResult(isError=True,structuredContent=data,content=[TextContent(type='text',text=json.dumps(data))])
    conversation.__annotations__['operation']=CopilotOperation
    conversation.__annotations__['request']=CopilotInput
    server.tool(name='cdf_governance_copilot',description='Bounded Arabic/English intent plans, durable synthetic workflows, grounded knowledge, versioned human decisions and admin health. Human actions require explicit structured input. No institutional activation or issuance.',
        annotations=ToolAnnotations(readOnlyHint=False,destructiveHint=True,openWorldHint=True,idempotentHint=False),structured_output=True)(conversation)
    return server


def http_app(application, *, port=8766):
    server = build_server(application, port=port)
    protocol_app = server.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app):
        async with server.session_manager.run():
            yield

    async def health(request):
        return JSONResponse(
            {
                "mode": "PUBLIC_SYNTHETIC_DEMO",
                "transport": "streamable-http",
                "authentication": "SCOPED_DEVELOPMENT_BEARER",
                "private_activation": "DISABLED",
                "oauth_issuer": "NOT_CONFIGURED",
            }
        )

    from starlette.middleware.base import BaseHTTPMiddleware

    class LoopbackOnly(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if not request.client or request.client.host not in (
                "127.0.0.1",
                "::1",
                "testclient",
            ):
                return JSONResponse({"error": "LOOPBACK_ONLY"}, status_code=403)
            return await call_next(request)

    app = Starlette(
        routes=[
            Route("/health", health),
            Mount("/", app=RequireAuthMiddleware(protocol_app, ["cdf:tools"])),
        ],
        middleware=[
            Middleware(LoopbackOnly),
            Middleware(
                AuthenticationMiddleware,
                backend=BearerAuthBackend(SessionVerifier(application)),
            ),
            Middleware(AuthContextMiddleware),
        ],
        lifespan=lifespan,
    )
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--transport", choices=["streamable-http", "stdio"], default="streamable-http"
    )
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    token = os.getenv("CDF_CALIBRATION_DEV_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError("SCOPED_DEVELOPMENT_CREDENTIAL_REQUIRED")
    application = ApplicationService(token=token)
    if args.transport == "stdio":
        build_server(application, transport="stdio").run(transport="stdio")
    else:
        import uvicorn

        uvicorn.run(
            http_app(application, port=args.port),
            host="127.0.0.1",
            port=args.port,
            log_level="warning",
            access_log=False,
        )


if __name__ == "__main__":
    main()
