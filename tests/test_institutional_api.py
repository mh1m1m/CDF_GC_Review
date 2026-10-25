import os
from pathlib import Path
import secrets
import subprocess
import sys
from test_mat_calibration_api import app_client,headers


def test_public_api_uses_only_synthetic_lookups_and_reports_disabled_private_mode(app_client,monkeypatch,tmp_path):
    client,_=app_client
    private=tmp_path/'restricted';private.mkdir();(private/'secret.json').write_text('FICTIONAL_PRIVATE_SENTINEL')
    monkeypatch.setenv('CDF_INSTITUTIONAL_STORAGE',str(private))
    mode=client.get('/api/operating-mode').json()
    assert mode['mode']=='PUBLIC_SYNTHETIC_DEMO' and mode['private_production_activation']=='DISABLED'
    response=client.get('/api/reference-candidates',headers=headers());assert response.json()['synthetic']
    assert 'FICTIONAL_PRIVATE_SENTINEL' not in response.text
    url='/api/reference-candidates/lookup?role=الاعتماد'
    assert client.get(url).status_code==401
    records=client.get(url,headers=headers()).json()
    assert records and all(r['synthetic'] and r['approver'] for r in records)
    assert client.get('/api/reference-candidates/lookup?source_id=PRIVATE-SOURCE',headers=headers()).json()==[]
    assert client.get('/api/reference-candidates/lookup?kind=private',headers=headers()).status_code==422
    assert client.get('/private/secret.json',headers=headers()).status_code==404


def test_private_http_mode_is_rejected_before_database_creation(tmp_path):
    database=tmp_path/'forbidden.sqlite'
    env={**os.environ,'CDF_OPERATION_MODE':'PRIVATE_INSTITUTIONAL','CDF_CALIBRATION_MODE':'SYNTHETIC_LOCAL_DEV',
         'CDF_CALIBRATION_DEV_TOKEN':secrets.token_urlsafe(36),'CDF_CALIBRATION_DB':str(database)}
    result=subprocess.run([sys.executable,'-c','import apps.api.main'],env=env,capture_output=True,text=True,timeout=15)
    assert result.returncode!=0 and 'ACTIVATION_DISABLED' in result.stderr
    assert not database.exists()
