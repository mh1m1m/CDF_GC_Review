"""An independently operable, loopback-only public demo, or isolated CI check."""
import os
from pathlib import Path
import secrets
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    if (Path(__file__).resolve().parents[1]/'private').exists():
        raise RuntimeError('PUBLIC_CONTAINER_HAS_PRIVATE_STORAGE')
    if any(k.startswith(('CDF_INSTITUTIONAL_','CDF_PRODUCTION_')) for k in os.environ):
        raise RuntimeError('PUBLIC_CONTAINER_HAS_INSTITUTIONAL_CONFIGURATION')
    os.environ.setdefault('CDF_CALIBRATION_DEV_TOKEN',secrets.token_urlsafe(36))
    from tools.seed_visual_demo import seed
    seed(Path(os.environ['CDF_CALIBRATION_DB']))
    from apps.api.main import app
    if '--check' in sys.argv:
        from fastapi.testclient import TestClient
        from cdf_gco_crms.institutional.providers import PublicSyntheticProvider
        assert PublicSyntheticProvider().catalog()['synthetic']
        with TestClient(app) as client:
            headers={'Authorization':'Bearer '+os.environ['CDF_CALIBRATION_DEV_TOKEN']}
            mode=client.get('/api/operating-mode').json()
            assert mode['private_production_activation']=='DISABLED'
            assert client.get('/').status_code==200
            references=client.get('/api/reference-candidates',headers=headers).json()
            assert references['synthetic'] and all(s['id'].startswith('SYN-') for s in references['sources'])
            assert client.get('/api/cases/SYN-COMMAND-001/intelligence/export/xlsx',headers=headers).status_code==200
            assert client.get('/private/candidates.json',headers=headers).status_code==404
        print('PUBLIC_MODE_ISOLATED_ACCEPTANCE: PASSED (no private mount, fictional references, UI/API/export)')
    else:
        import uvicorn
        uvicorn.run(app,host='127.0.0.1',port=8765)


if __name__=='__main__':main()
