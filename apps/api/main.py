"""MAT calibration API: synthetic data only, in one of two modes.

* SYNTHETIC_LOCAL_DEV (default): loopback only, ephemeral developer bearer token.
* HOSTED_SYNTHETIC_DEMO: served from a host (Vercel); sign-in through Supabase Auth, limited to the reviewers
  listed in CDF_HOSTED_REVIEWERS (cdf_gco_crms.interfaces.hosted_auth); data in Postgres (CDF_DATABASE_URL).
  The public-synthetic guards still apply: only SYN- cases, no institutional activation, no issuance.

Neither mode is organizational SSO or production authorization.
"""
from __future__ import annotations
import hmac
import json
import os
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ConfigDict

from cdf_gco_crms.calibration.service import CalibrationService
from cdf_gco_crms.calibration.analytics import analyze
from cdf_gco_crms.calibration.store import CalibrationStore, ReviewerContext, CalibrationError, AccessDenied, StaleCase, StaleDecision

MODE = os.getenv("CDF_CALIBRATION_MODE", "")
if MODE not in ("SYNTHETIC_LOCAL_DEV", "HOSTED_SYNTHETIC_DEMO"):
    raise RuntimeError("CALIBRATION_API_NOT_AUTHORIZED: set CDF_CALIBRATION_MODE=SYNTHETIC_LOCAL_DEV for local synthetic data only")
HOSTED = MODE == "HOSTED_SYNTHETIC_DEMO"
TOKEN = os.getenv("CDF_CALIBRATION_DEV_TOKEN", "")
if HOSTED:
    from cdf_gco_crms.interfaces import hosted_auth
    if not os.getenv("CDF_DATABASE_URL") or not os.getenv("CDF_SUPABASE_URL"):
        raise RuntimeError("HOSTED_MODE_REQUIRES_CDF_DATABASE_URL_AND_CDF_SUPABASE_URL")
    VERIFIER = hosted_auth.SupabaseVerifier(os.environ["CDF_SUPABASE_URL"], hosted_auth.load_reviewers())
    TOKEN = None          # no developer bearer is ever accepted by a hosted deployment
elif len(TOKEN) < 32 or TOKEN.lower() in ("changeme", "password"):
    raise RuntimeError("Set a random CDF_CALIBRATION_DEV_TOKEN of at least 32 characters")
DB_PATH = Path(os.getenv("CDF_CALIBRATION_DB", "build/public-demo/mat-calibration-dev.sqlite")).resolve()
from cdf_gco_crms.institutional.contracts import activation_status
from cdf_gco_crms.institutional.isolation import require_public_runtime, bind_public_database
require_public_runtime(os.getenv('CDF_OPERATION_MODE', 'PUBLIC_SYNTHETIC_DEMO'), DB_PATH)
store = CalibrationStore(DB_PATH)
bind_public_database(store)
from cdf_gco_crms.execution.service import ApplicationService, Conflict
from cdf_gco_crms.execution.contracts import Request as OperationRequest
application = ApplicationService(store=store, token=TOKEN if TOKEN else "")
if HOSTED:
    from cdf_gco_crms.interfaces.hosted_seed import seed_and_grant
    seed_and_grant(DB_PATH, VERIFIER.reviewers)
service = application.calibration
intelligence = application.intelligence
_DB_LOCK = application.lock
app = FastAPI(title="MAT Calibration (SYNTHETIC LOCAL DEV ONLY)", version="0.1.0",
              docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def localhost_only(request: Request, call_next):
    # Local mode: do NOT trust forwarded-for headers; reject non-loopback socket clients.
    # Hosted mode: every data route needs a verified Supabase session instead (see principal()).
    if not HOSTED and (not request.client or request.client.host not in ("127.0.0.1", "::1", "testclient")):
        return JSONResponse({"detail": "LOOPBACK_ONLY"}, status_code=403)
    response = await call_next(request)
    if HOSTED:
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def principal(authorization):
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401,'SIGN_IN_REQUIRED' if HOSTED else 'DEV_TOKEN_REQUIRED')
    try:
        if HOSTED:
            with _DB_LOCK:
                return hosted_auth.authenticate(application, VERIFIER, authorization[7:])
        return application.authenticate(authorization[7:])
    except AccessDenied as exc:raise HTTPException(403,str(exc)) from exc


def identity(authorization: str | None):
    return principal(authorization).reviewer


def call(fn, *args, **kwargs):
    try:
        with _DB_LOCK:
            return fn(*args, **kwargs)
    except AccessDenied as e:
        raise HTTPException(403, str(e)) from e
    except (StaleCase, StaleDecision) as e:
        raise HTTPException(409, str(e)) from e
    except Conflict as e:
        raise HTTPException(409,str(e)) from e
    except CalibrationError as e:
        raise HTTPException(422, str(e)) from e
    except KeyError as e:
        raise HTTPException(422, "MISSING_FIELD") from e


class ImportCase(BaseModel):
    model_config=ConfigDict(extra="forbid",hide_input_in_errors=True)
    case_id: str = Field(min_length=1, max_length=120)
    source_hash: str
    observations: list[dict[str, Any]]


class Decision(BaseModel):
    model_config=ConfigDict(extra="forbid",hide_input_in_errors=True)
    decision: str
    rationale: str = ""
    expected_evidence_hash: str
    status: str = "DRAFT"
    reasons: list[str] = []
    evidence_refs: list[str] = []
    material_categories: list[str] = []
    expected_decision_head: str | None = None     # latest decision hash the client read; null = it saw none


class DecisionReview(BaseModel):
    model_config=ConfigDict(extra="forbid",hide_input_in_errors=True)
    decision_event_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    outcome: str
    rationale: str


class RuleReview(BaseModel):
    model_config=ConfigDict(extra="forbid",hide_input_in_errors=True)
    action: str
    rationale: str
    observation_event_hashes: list[str]
    profile_version: str


@app.get('/api/operating-mode')
def operating_mode():
    return activation_status()


@app.get("/api/health")
def health():
    if HOSTED:
        return {"status": "HOSTED_SYNTHETIC_DEMO", "institutional_auth": "NOT_CONFIGURED",
                "sign_in": "SUPABASE_AUTH_LISTED_REVIEWERS_ONLY", "data": "SYNTHETIC_ONLY"}
    return {"status": "SYNTHETIC_LOCAL_DEV", "institutional_auth": "NOT_CONFIGURED"}


@app.get("/api/cases")
def cases(authorization: str | None = Header(default=None)):
    return call(service.list_cases, identity(authorization))


@app.post("/api/cases", status_code=201)
def import_case(item: ImportCase, authorization: str | None = Header(default=None)):
    # No actual institutional material is accepted in this development mode.
    # Caller must use synthetic cases, which are validated here conservatively.
    if not item.case_id.startswith("SYN-"):
        raise HTTPException(422, "SYNTHETIC_CASE_ID_REQUIRED")
    if any(not str(x.get("observation_id", "")).startswith("SYN-") for x in item.observations):
        raise HTTPException(422, "SYNTHETIC_OBSERVATION_IDS_REQUIRED")
    return call(service.import_case, item.case_id, item.source_hash, item.observations, identity(authorization))


@app.get("/api/cases/{case_id}")
def get_case(case_id: str, authorization: str | None = Header(default=None)):
    return call(service.case, case_id, identity(authorization))


@app.get("/api/cases/{case_id}/events")
def events(case_id: str, authorization: str | None = Header(default=None)):
    return call(service.events, case_id, identity(authorization))


@app.post("/api/cases/{case_id}/observations/{observation_id}/decisions")
def decision(case_id: str, observation_id: str, item: Decision, authorization: str | None = Header(default=None)):
    digest = call(service.decision, case_id, observation_id, item.model_dump(exclude_unset=True), identity(authorization))
    return {"event_hash": digest, "status": item.status}


@app.post("/api/cases/{case_id}/decisions/review")
def decision_review(case_id: str, item: DecisionReview, authorization: str | None = Header(default=None)):
    """Second-human review of a submitted decision (a different identity from the decider)."""
    digest = call(service.review_decision, case_id, item.model_dump(), identity(authorization))
    return {"event_hash": digest, "outcome": item.outcome}


@app.post("/api/cases/{case_id}/rules/{rule_id}/review")
def rule_review(case_id: str, rule_id: str, item: RuleReview, authorization: str | None = Header(default=None)):
    digest = call(service.rule, case_id, rule_id, item.model_dump(), identity(authorization))
    return {"event_hash": digest, "result": item.action}

@app.get("/api/cases/{case_id}/analytics")
def analytics(case_id: str, authorization: str | None = Header(default=None)):
    user = identity(authorization)
    return call(_analyze_authorized, case_id, user)


def _analyze_authorized(case_id, user):
    service.authorize(case_id, user)
    return analyze(store, case_id, user)

@app.post("/api/cases/{case_id}/profiles/compile", status_code=201)
def compile_synthetic_profile(case_id: str, authorization: str | None = Header(default=None)):
    return call(service.compile_profile, case_id, identity(authorization))


@app.get("/api/cases/{case_id}/profiles")
def list_profile_versions(case_id: str, authorization: str | None = Header(default=None)):
    return call(service.profiles, case_id, identity(authorization))


@app.post("/api/cases/{case_id}/profiles/{version}/activate")
def activate_profile_version(case_id: str, version: str, authorization: str | None = Header(default=None)):
    return call(service.activate_profile, case_id, version, identity(authorization))

@app.get("/api/cases/{case_id}/profiles/{version}")
def read_synthetic_profile(case_id: str, version: str, authorization: str | None = Header(default=None)):
    return call(service.profile_document, case_id, version, identity(authorization))


@app.get("/api/cases/{case_id}/intelligence")
def executive_intelligence(case_id: str, authorization: str | None = Header(default=None)):
    return call(intelligence.dashboard, case_id, identity(authorization))


@app.get("/api/cases/{case_id}/intelligence/export/{kind}")
def draft_executive_export(case_id: str, kind: str, authorization: str | None = Header(default=None)):
    from cdf_gco_crms.intelligence.exports import export_dashboard
    from fastapi.responses import Response
    if kind not in ("docx", "xlsx", "pdf"):
        raise HTTPException(422, "UNSUPPORTED_DRAFT_EXPORT")
    data = call(intelligence.dashboard, case_id, identity(authorization))
    try:
        payload = export_dashboard(data, kind)
    except (RuntimeError, TimeoutError) as exc:
        raise HTTPException(503, "DRAFT_RENDERER_UNAVAILABLE") from exc
    media = {"docx":"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             "xlsx":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "pdf":"application/pdf"}
    return Response(payload, media_type=media[kind], headers={"Content-Disposition":
        f'attachment; filename="INTERNAL_DRAFT__executive.{kind}"'})


@app.get('/api/reference-candidates')
def public_reference_candidates(authorization: str | None = Header(default=None)):
    from cdf_gco_crms.intelligence.references import reference_candidates
    identity(authorization).require('CALIBRATION_REVIEWER')
    return reference_candidates()


@app.get('/api/reference-candidates/lookup')
def reference_lookup(query: str = Query(default='',max_length=240), role: str | None = Query(default=None,max_length=80),
                     kind: str = Query(default='authority',pattern='^(authority|responsibility)$'),
                     source_id: str | None = Query(default=None,max_length=100),
                     authorization: str | None = Header(default=None)):
    identity(authorization).require('CALIBRATION_REVIEWER')
    from cdf_gco_crms.institutional.providers import PublicSyntheticProvider, ReferenceLookupService
    lookup=ReferenceLookupService(PublicSyntheticProvider())
    return (lookup.authorities(query,role=role,source_id=source_id) if kind=='authority'
            else lookup.responsibilities(query,source_id=source_id))


@app.post('/api/operations/{tool}')
def execute_operation(tool: str, request: OperationRequest, authorization: str | None=Header(default=None)):
    user=principal(authorization)
    result=call(application.invoke,tool,request,user,transport='HTTP')
    from cdf_gco_crms.execution.contracts import TOOLS
    if tool in TOOLS and TOOLS[tool][0] in ('review','debate','probe','docx','xlsx','pdf'):
        from cdf_gco_crms.execution.jobs import launch
        launch(application,result['data']['job_id'],user)
    return result


@app.get('/api/cases/{case_id}/execution')
def execution_workspace(case_id: str,authorization: str | None=Header(default=None)):
    return call(application.invoke,'cdf_get_case_status',OperationRequest(case_id=case_id),principal(authorization),transport='REACT_HTTP')['data']


@app.get('/api/artifacts/{artifact_id}/content')
def artifact_bytes(artifact_id: str,authorization: str | None=Header(default=None)):
    from fastapi.responses import Response
    user=principal(authorization)
    call(application.invoke,'cdf_get_artifact_status',OperationRequest(artifact_id=artifact_id),user,transport='REACT_HTTP')
    row=call(application._artifact_row,artifact_id,user)
    descriptor=application.artifact_metadata(row)
    import hashlib
    if hashlib.sha256(row['content']).hexdigest()!=descriptor['sha256']:
        raise HTTPException(422,'ARTIFACT_INTEGRITY_FAILED')
    return Response(row['content'],media_type=descriptor['media_type'],headers={
        'Content-Disposition':'attachment; filename="'+descriptor['filename']+'"','X-CDF-Artifact-ID':artifact_id,
        'X-Content-Type-Options':'nosniff','Cache-Control':'no-store'})


# Phase II shares the same authenticated application, case grants and database.
from cdf_gco_crms.copilot.service import CopilotService
from cdf_gco_crms.copilot.contracts import Input as CopilotInput, Operation as CopilotOperation
from cdf_gco_crms.copilot.http import CopilotBodyLimit
copilot=CopilotService(application)
app.add_middleware(CopilotBodyLimit)
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
@app.exception_handler(RequestValidationError)
async def private_validation_errors(request,exc):
    if request.url.path.startswith('/api/copilot/'):
        return JSONResponse({'detail':'COPILOT_INPUT_VALIDATION_FAILED','fields':[list(error['loc']) for error in exc.errors()]},status_code=422)
    return await request_validation_exception_handler(request,exc)


@app.post('/api/copilot/{operation}')
def conversational_operation(operation: CopilotOperation, request: CopilotInput, authorization: str | None=Header(default=None)):
    try:return copilot.execute(operation,request.model_dump(),principal(authorization),transport='REACT_COPILOT')
    except AccessDenied as exc:raise HTTPException(403,str(exc)) from exc
    except CalibrationError as exc:
        if str(exc)=='RATE_LIMIT_EXCEEDED':raise HTTPException(429,'RATE_LIMIT_EXCEEDED') from exc
        if isinstance(exc,Conflict):raise HTTPException(409,str(exc)) from exc
        raise HTTPException(422,str(exc)) from exc


# Optional prebuilt public UI. The demo container supplies this directory; it
# never serves repository/private files or runtime environment values.
if os.getenv('CDF_PUBLIC_UI_DIRECTORY'):
    from fastapi.staticfiles import StaticFiles
    ui_path=Path(os.environ['CDF_PUBLIC_UI_DIRECTORY']).resolve(strict=True)
    require_public_runtime('PUBLIC_SYNTHETIC_DEMO',ui_path)
    app.mount('/',StaticFiles(directory=ui_path,html=True),name='public-ui')
