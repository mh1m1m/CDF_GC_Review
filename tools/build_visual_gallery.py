"""A dedicated visual gate: actual browser captures plus independent document renders."""
from pathlib import Path
import argparse
import hashlib
import html
import json
import shutil
from PIL import Image

REQUIRED={
 'command-center-desktop.png':'Executive Command Center',
 'command-center-iphone.png':'iPhone RTL',
 'liquid-glass-library.png':'Liquid Glass component library',
 'icon-gallery.png':'Premium icon gallery',
 'gauge-gallery.png':'Gauge gallery',
 'debate-theater.png':'AI Debate Theater',
 'debate-objection-tree.png':'Recorded objection tree',
 'authority-explorer-desktop.png':'DoA Authority Explorer',
 'responsibility-map-desktop.png':'Department Responsibility Map',
 'mat-calibration-desktop.png':'MAT Calibration Dashboard',
 'word-report-preview.png':'Actual Word/PDF render',
 'excel-dashboard-preview.png':'Actual Calc/PDF render'}


def build(inputs:list[Path],output:Path):
    output.mkdir(parents=True,exist_ok=True);assets=output/'images';assets.mkdir(exist_ok=True)
    records=[]
    for name,title in REQUIRED.items():
        matches=[p for folder in inputs for p in folder.rglob(name) if assets not in p.parents]
        if not matches:raise FileNotFoundError('Required actual visual evidence missing: '+name)
        source=matches[0];destination=assets/name;shutil.copyfile(source,destination)
        with Image.open(source) as image:width,height=image.size
        records.append({'name':name,'title':title,'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'width':width,'height':height,'classification':'SYNTHETIC_ACTUAL_RENDER'})
    contract={'status':'PASSED','basis':'REQUIRED_ACTUAL_CAPTURES_PRESENT','institutional_design_approval':'PENDING_AUTHORIZATION',
              'manual_accessibility_and_UAT':'NOT_RUN','images':records}
    (output/'visual-acceptance.json').write_text(json.dumps(contract,indent=2))
    cards=''.join(f'<article><h2>{html.escape(r["title"])}</h2><a href="images/{r["name"]}"><img loading="lazy" src="images/{r["name"]}" alt="{html.escape(r["title"])}"></a><p>{r["width"]} × {r["height"]} · actual synthetic render</p></article>' for r in records)
    (output/'index.html').write_text('<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CDF visual acceptance gallery</title><style>body{font-family:Arial,sans-serif;background:#edf1f5;color:#101820;margin:0;padding:30px}header{max-width:1000px;margin:auto}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:24px}article{padding:22px;background:white;border-radius:20px;min-width:0}img{width:100%;height:420px;object-fit:contain;object-position:top}h2{font-size:20px}p{color:#41586a}</style><header><h1>معرض القبول البصري</h1><p>لقطات فعلية من التطبيق والمتصفح ومحركات المستندات، ببيانات افتراضية. لا يمثل المعرض اعتماداً مؤسسياً للتصميم أو التشغيل.</p></header><main>'+cards+'</main></html>')
    print('VISUAL_GALLERY_GATE: PASSED',len(records),'actual captures; institutional approval pending')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',type=Path,action='append',required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();build(args.input,args.output)
