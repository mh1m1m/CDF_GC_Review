"""Reproduce public extraction candidates from hash-verified, authorized PDF copies.

No source download, activation, approval upgrade or provider call is performed.
"""
import argparse
from dataclasses import asdict
from datetime import date
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cdf_gco_crms.references.authority_matrix import parse_matrix
from cdf_gco_crms.references.org_structure import parse_org_text


def ingest(folder:Path,manifest:dict):
    for source in manifest['sources']:
        if source['id'] not in ('doa','organization','identity'):raise ValueError('UNKNOWN_SOURCE')
        path=folder/(source['id']+'.pdf')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=source['sha256']:raise ValueError('SOURCE_INTEGRITY_FAILED:'+source['id'])
    matrix=parse_matrix(folder/'doa.pdf')
    with tempfile.TemporaryDirectory(prefix='cdf-reference-extract-') as temp:
        text=Path(temp)/'organization.txt'
        subprocess.run(['pdftotext','-layout',str(folder/'organization.pdf'),str(text)],check=True,timeout=60)
        org=parse_org_text(text)
    authorities=[{**asdict(item),'id':'DOA-'+item.number,'source_id':'doa','approval_status':'UNKNOWN',
        'threshold':'REQUIRES_HUMAN_RECONCILIATION','effective_date':'NOT_VERIFIED','current_authority_confirmed':False,
        'extraction_status':'CANDIDATE_REQUIRES_HUMAN_RECONCILIATION'} for item in matrix.items]
    units=[{**asdict(unit),'id':'ORG-'+str(i+1),'source_id':'organization','approval_status':'PROPOSED_NOT_APPROVED',
            'current_authority_confirmed':False} for i,unit in enumerate(org.units)]
    return {'schema':'CDF-PUBLIC-REFERENCE-CANDIDATES-v1','classification':'USER_DECLARED_PUBLIC','captured_at':date.today().isoformat(),
            'sources':manifest['sources'],'authorities':authorities,'units':units,'sectors':[asdict(s) for s in org.sectors],
            'limitations':['EXTRACTION_IS_NOT_APPROVAL','CURRENT_AUTHORITY_NOT_CONFIRMED','THRESHOLDS_REQUIRE_RECONCILIATION','NO_EXTERNAL_PROVIDER_PROCESSING_AUTHORIZED']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-directory',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,default=Path('shared/reference-source-manifest.json'))
    parser.add_argument('--output',type=Path,default=Path('build/reference-candidates.json'))
    args=parser.parse_args()
    result=ingest(args.source_directory,json.loads(args.manifest.read_text()))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print('Extracted candidates:',len(result['authorities']),len(result['units']))
