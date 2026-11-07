"""HTTP boundaries for the shared application, distinct from protocol client tests."""
from test_mat_calibration_api import app_client, headers


def test_http_shared_operation_replay_and_forged_identity(app_client):
    client,mod=app_client
    body={'case_id':'SYN-HTTP-COOP','idempotency_key':'http-create-key-001'}
    url='/api/operations/cdf_create_case'
    assert client.post(url,json=body).status_code==401
    forged=client.post(url,headers=headers(),json={**body,'reviewer_id':'FORGED'})
    assert forged.status_code==422
    created=client.post(url,headers=headers(),json=body)
    assert created.status_code==200 and created.json()['data']['source_imported']
    replay=client.post(url,headers=headers(),json=body)
    assert replay.status_code==200 and replay.json()['data']['replayed']
    state=client.get('/api/cases/SYN-HTTP-COOP/execution',headers=headers())
    assert state.status_code==200 and state.json()['source_hash']==created.json()['data']['source_hash']
    assert client.get('/api/cases/SYN-UNGRANTED/execution',headers=headers()).status_code==403
    assert client.post('/api/operations/cdf_generate_word_report',headers=headers(),json={'case_id':'SYN-HTTP-COOP','issue':True}).status_code==403
    assert mod.store.db.execute("SELECT COUNT(*) FROM app_audit WHERE transport='REACT_HTTP'").fetchone()[0]>=1


def test_http_expired_session_rejected_by_old_and_new_routes(app_client):
    client,mod=app_client
    with mod.store.transaction():mod.store.db.execute('UPDATE app_sessions SET expires_at=0')
    assert client.get('/api/cases',headers=headers()).status_code==403
    assert client.post('/api/operations/cdf_create_case',headers=headers(),json={'case_id':'SYN-EXPIRED'}).status_code==403
    assert client.get('/api/artifacts/ART-'+'a'*32+'/content',headers=headers()).status_code==403
    assert not mod.store.db.execute('SELECT 1 FROM app_cases').fetchone()
