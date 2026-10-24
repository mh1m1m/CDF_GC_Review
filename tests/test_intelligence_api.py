from io import BytesIO
from openpyxl import load_workbook
from test_mat_calibration_api import app_client, headers
from tools.seed_visual_demo import seed


def test_intelligence_auth_case_binding_and_draft_exports(app_client):
    client,mod=app_client
    case=seed(mod.store.path)
    url='/api/cases/'+case+'/intelligence'
    assert client.get(url).status_code==401
    data=client.get(url,headers=headers()).json()
    assert data['synthetic'] and data['actual_live_inference_count']==0
    assert not data['release_gate']['authorized']
    response=client.get(url+'/export/xlsx',headers=headers())
    assert response.status_code==200 and 'INTERNAL_DRAFT__' in response.headers['content-disposition']
    workbook=load_workbook(BytesIO(response.content))
    assert workbook['Executive']['C3'].value==data['metrics'][0]['denominator']
    assert client.get(url+'/export/unsupported',headers=headers()).status_code==422
    assert client.get('/api/reference-candidates').status_code==401
    references=client.get('/api/reference-candidates',headers=headers()).json()
    assert len(references['authorities'])>0
    assert not any(s['current_authority_confirmed'] for s in references['sources'])
