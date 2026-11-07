"""Generate only fictional draft samples and independent render/recalculation evidence."""
from pathlib import Path
from tempfile import TemporaryDirectory
from io import BytesIO
import argparse
import hashlib
import json
import math
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pymupdf
from openpyxl import load_workbook
from cdf_gco_crms.calibration.service import CalibrationService
from cdf_gco_crms.calibration.store import CalibrationStore,ReviewerContext
from cdf_gco_crms.intelligence.service import IntelligenceService
from cdf_gco_crms.intelligence.exports import export_dashboard
from cdf_gco_crms.qa import lo_engine
from tools.seed_visual_demo import seed


def generate(output:Path):
    if not lo_engine.available() or 'Dev' in lo_engine.version():raise RuntimeError('STABLE_DOCUMENT_ENGINE_REQUIRED')
    output.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix='cdf-visual-export-') as temp:
        db=Path(temp)/'fictional.sqlite';case=seed(db);store=CalibrationStore(db)
        user=ReviewerContext('SYNTHETIC_ADMIN',frozenset({'CALIBRATION_ADMIN','CALIBRATION_REVIEWER'}),True)
        data=IntelligenceService(CalibrationService(store)).dashboard(case,user)
        assert data['synthetic'] and data['actual_live_inference_count']==0
        (output/'SYNTHETIC-dashboard.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
        for kind in ('docx','xlsx','pdf'):(output/('INTERNAL_DRAFT__executive.'+kind)).write_bytes(export_dashboard(data,kind))
        path=output/'INTERNAL_DRAFT__executive.xlsx';before=hashlib.sha256(path.read_bytes()).hexdigest()
        rendered=lo_engine.to_pdf(path,Path(temp)/'calc',timeout=120)
        if rendered is None:raise RuntimeError('CALC_PREVIEW_FAILED')
        (output/'INTERNAL_DRAFT__excel-preview.pdf').write_bytes(rendered.read_bytes())
        for source,name in [(output/'INTERNAL_DRAFT__executive.pdf','word-report-preview'),(rendered,'excel-dashboard-preview')]:
            with pymupdf.open(source) as document:
                document[0].get_pixmap(matrix=pymupdf.Matrix(1.5,1.5)).save(output/(name+'.png'))
        recalc=Path(temp)/'recalculated.xlsx';recalc.write_bytes(path.read_bytes())
        if not lo_engine.recalc(recalc,timeout=120).ok:raise RuntimeError('CALC_RECONCILIATION_FAILED')
        workbook=load_workbook(recalc,data_only=True)
        values=[]
        for index,metric in enumerate(data['metrics'],3):
            value=workbook['Executive'].cell(index,4).value
            if metric['value'] is None:assert value in ('',None)
            else:assert math.isclose(value,metric['numerator']/metric['denominator'],abs_tol=1e-9)
            values.append({'metric_id':metric['id'],'recalculated_fraction':value,'status':'PASSED'})
        assert hashlib.sha256(path.read_bytes()).hexdigest()==before
        (output/'cross-format-evidence.json').write_text(json.dumps({'synthetic':True,'source_unchanged':True,
            'engine':lo_engine.version(),'metrics':values,'sparkline_limit':'Excel x14 present in original; other editors may drop extension'},indent=2))
        store.close()
    print('VISUAL_EXPORT_ACCEPTANCE: PASSED (synthetic Word/PDF/Calc previews and all metric fractions)')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);generate(parser.parse_args().output)
