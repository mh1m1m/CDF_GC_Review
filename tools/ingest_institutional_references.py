"""Preserve originals and build an inactive private registry; never download/publish.

This local development command is authorized source processing, not runtime access
or institutional approval. Output inside the repository must be under private/.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.ingest_public_references import ingest

ROOT=Path(__file__).resolve().parents[1]


def build_registry(source_directory: Path, manifest: dict, output: Path):
    target=output.resolve()
    if target.is_relative_to(ROOT) and not target.is_relative_to(ROOT/'private'):
        raise PermissionError('INSTITUTIONAL_OUTPUT_REQUIRES_PRIVATE_STORAGE')
    data=ingest(source_directory,manifest)
    target.mkdir(parents=True,exist_ok=True,mode=0o700)
    originals=target/'originals';originals.mkdir(exist_ok=True,mode=0o700)
    sources=[]
    for raw in manifest['sources']:
        record=dict(raw);path=source_directory/(record['id']+'.pdf')
        content=path.read_bytes();digest=hashlib.sha256(content).hexdigest()
        if digest!=record['sha256']:raise ValueError('SOURCE_INTEGRITY_FAILED')
        destination=originals/(digest+'.pdf')
        if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest()!=digest:
            raise ValueError('PRESERVED_ORIGINAL_TAMPERED')
        if not destination.exists():shutil.copyfile(path,destination)
        destination.chmod(0o600)
        record['storage_location']='originals/'+destination.name
        record['current_authority_confirmed']=False
        sources.append(record)
    version_file=target/'versions.json'
    versions=json.loads(version_file.read_text())['versions'] if version_file.exists() else []
    for record in sources:
        if not any((r['id'],r['version'],r['sha256'])==(record['id'],record['version'],record['sha256']) for r in versions):versions.append(record)
    data.update(sources=sources,synthetic=False,mode='PRIVATE_INSTITUTIONAL')
    for filename,payload in [('sources.json',{'sources':sources}),('candidates.json',data),('versions.json',{'versions':versions})]:
        path=target/filename;temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(payload,ensure_ascii=False,indent=2));temporary.chmod(0o600);temporary.replace(path)
    return {'authorities':len(data['authorities']),'units':len(data['units']),'activation':'DISABLED_PENDING_AUTHORIZATION'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-directory',required=True,type=Path)
    parser.add_argument('--manifest',required=True,type=Path)
    parser.add_argument('--output',default=ROOT/'private/reference-registry',type=Path)
    args=parser.parse_args()
    print(json.dumps(build_registry(args.source_directory,json.loads(args.manifest.read_text()),args.output)))
