"""Local MAT calibration API: synthetic development mode ONLY.

Never expose this service beyond localhost. Its ephemeral bearer token is
for developer exercise only, not organizational SSO or production authorization.
"""
from __future__ import annotations
import hmac
import json
import os
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from cdf_gco_crms.calibration.service import CalibrationService
from cdf_gco_crms.calibration.analytics import analyze
from cdf_gco_crms.calibration.store import CalibrationStore, ReviewerContext, CalibrationError, AccessDenied, StaleCase

if os.getenv("CDF_CALIBRATION_MODE") != "SYNTHETIC_LOCAL_DEV":
    raise RuntimeError("CALIBRATION_API_NOT_AUTHORIZED: set CDF_CALIBRATION_MODE=SYNTHETIC_LOCAL_DEV for local synthetic data only")
TOKEN = os.getenv("CDF_CALIBRATION_DEV_TOKEN", "")
if len(TOKEN) < 32 or TOKEN.lower() in ("changeme", "password"):
    raise RuntimeError("Set a random CDF_CALIBRATION_DEV_TOKEN of at least 32 characters")
DB_PATH = Path(os.getenv("CDF_CALIBRATION_DB", "build/private/mat-calibration-dev.sqlite")).resolve()
store = CalibrationStore(DB_PATH)
service = CalibrationService(store)
_DB_LOCK = threading.RLock()  # serialize SQLite operations in this single-process LOCAL DEV API
app = FastAPI(title="MAT Calibration (SYNTHETIC LOCAL DEV ONLY)", version="0.1.0",
              docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def localhost_only(request: Request, call_next):
    # Do NOT trust forwarded-for headers; reject non-loopback socket clients.
    if not request.client or request.client.host not in ("127.0.0.1", "::1", "testclient"):
        return JSONResponse({"detail": "LOOPBACK_ONLY"}, status_code=403)
    return await call_next(request)


def identity(authorization: str | None) -> ReviewerContext:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "DEV_TOKEN_REQUIRED")
    if not hmac.compare_digest(authorization[7:], TOKEN):
        raise HTTPException(403, "INVALID_DEV_TOKEN")
    return ReviewerContext("SYNTHETIC_ADMIN",
                           frozenset({"CALIBRATION_ADMIN", "CALIBRATION_REVIEWER", "DNA_RULE_APPROVER"}),
                           authenticated=True)


def call(fn, *args, **kwargs):
    try:
        with _DB_LOCK:
            return fn(*args, **kwargs)
    except AccessDenied as e:
        raise HTTPException(403, str(e)) from e
    except StaleCase as e:
        raise HTTPException(409, str(e)) from e
    except CalibrationError as e:
        raise HTTPException(422, str(e)) from e
    except KeyError as e:
        raise HTTPException(422, "MISSING_FIELD") from e


class ImportCase(BaseModel):
    case_id: str = Field(min_length=1, max_length=120)
    source_hash: str
    observations: list[dict[str, Any]]


class Decision(BaseModel):
    decision: str
    rationale: str = ""
    expected_evidence_hash: str
    status: str = "DRAFT"
    reasons: list[str] = []
    evidence_refs: list[str] = []
    material_categories: list[str] = []


class RuleReview(BaseModel):
    action: str
    rationale: str
    observation_event_hashes: list[str]
    profile_version: str


@app.get("/api/health")
def health():
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
    digest = call(service.decision, case_id, observation_id, item.model_dump(), identity(authorization))
    return {"event_hash": digest, "status": item.status}


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
