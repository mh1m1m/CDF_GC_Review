"""Synthetic API integration exercise; never tests on institutional documents."""
import importlib
import os
import sys
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("CDF_CALIBRATION_MODE", "SYNTHETIC_LOCAL_DEV")
    monkeypatch.setenv("CDF_CALIBRATION_DEV_TOKEN", "a" * 48)
    monkeypatch.setenv("CDF_CALIBRATION_DB", str(tmp_path / "public-demo" / "pilot.sqlite"))
    sys.modules.pop("apps.api.main", None)
    mod = importlib.import_module("apps.api.main")
    with TestClient(mod.app) as client:
        yield client, mod
    mod.store.close()
    sys.modules.pop("apps.api.main", None)


def headers():
    return {"Authorization": "Bearer " + "a" * 48}


def make_case(client):
    response = client.post("/api/cases", headers=headers(), json={
        "case_id": "SYN-API-001", "source_hash": "a" * 64,
        "observations": [{"observation_id": "SYN-OBS-001",
                          "original_text": "Fictional original",
                          "reviewed_text": None,
                          "observed_change": "REMOVED_FROM_VERSION",
                          "material_categories": ["AML"]}]})
    assert response.status_code == 201, response.text
    return response.json()["evidence_hash"]


def test_api_anonymous_refused_and_health_is_labelled(app_client):
    client, _ = app_client
    h=client.get("/api/health")
    assert h.status_code == 200 and h.json()["institutional_auth"] == "NOT_CONFIGURED"
    assert client.get("/api/cases").status_code == 401
    assert client.get("/api/cases", headers={"Authorization":"Bearer bad"}).status_code == 403


def test_api_persist_calibration_and_materiality(app_client):
    client, _ = app_client
    digest=make_case(client)
    body={"decision":"WITHDRAW","rationale":"An adequate synthetic control exists.",
          "expected_evidence_hash":digest,"status":"SUBMITTED","reasons":["W12"]}
    url="/api/cases/SYN-API-001/observations/SYN-OBS-001/decisions"
    invalid=client.post(url,headers=headers(),json=body)
    assert invalid.status_code == 422 and "MATERIAL_WITHDRAWAL" in invalid.text
    body["evidence_refs"]=["EVIDENCE_GAP:synthetic"]
    response=client.post(url,headers=headers(),json=body)
    assert response.status_code == 200, response.text
    case=client.get("/api/cases/SYN-API-001",headers=headers()).json()
    assert case["statistics"]["submitted_observations"]==1
    assert case["statistics"]["heightened_review"]==1
    events=client.get("/api/cases/SYN-API-001/events",headers=headers())
    assert events.status_code==200 and len(events.json())==2


def test_api_rejects_unmarked_case(app_client):
    client, _ = app_client
    r=client.post("/api/cases",headers=headers(),json={"case_id":"NOT-SYN","source_hash":"a"*64,
                "observations":[{"observation_id":"SYN-001"}]})
    assert r.status_code==422


def test_case_permissions_deny_ungranted_identity(app_client):
    client,mod=app_client
    make_case(client)
    from cdf_gco_crms.calibration.store import ReviewerContext,AccessDenied
    impersonator=ReviewerContext("SYNTHETIC_UNGRANTED",frozenset({"CALIBRATION_REVIEWER"}),True)
    with pytest.raises(AccessDenied,match="CASE_ACCESS_DENIED"):
        mod.service.case("SYN-API-001",impersonator)
