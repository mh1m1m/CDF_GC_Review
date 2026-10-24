"""Public extraction candidates and a fail-closed adapter to the existing evidence registry.

Publication was explicitly authorized by the user. Publication is not institutional
approval, currency, applicability or authorization for external-provider processing.
"""
import hashlib
import json
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from ..references.textnorm import match_key

ROOT = Path(__file__).resolve().parents[2]


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    url: HttpUrl
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    version: str
    approval_status: str
    effective_date: str
    supersession_checked: bool
    current_authority_confirmed: bool
    publication_status: str
    extraction_status: str
    original_filename: str | None = None
    mime_type: str = 'application/pdf'
    drive_file_id: str | None = None
    document_title: str | None = None
    approval_date: str | None = None
    approving_authority: str | None = None
    document_owner: str | None = None
    supersedes: str | None = None
    last_verified_date: str | None = None
    source_confidence: str = 'NOT_ESTABLISHED'
    storage_location: str | None = None
    document_date: str | None = None
    document_date_status: str = 'NOT_VERIFIED'
    permission_for_use: str = 'NOT_VERIFIED'
    authenticity_status: str = 'NOT_VERIFIED'
    accessibility_status: str = 'NOT_VERIFIED'


def reference_candidates():
    from ..institutional.providers import PublicSyntheticProvider
    return candidate_graph(PublicSyntheticProvider().catalog())


def candidate_graph(data):
    # Providers establish classification before this shared graph projection.
    nodes = {"SOURCE-"+s['id']: {'id':"SOURCE-"+s['id'], 'label':s['id'], 'kind':'SOURCE'} for s in data['sources']}
    edges = []
    for entry in data['authorities']:
        nodes[entry['id']] = {'id':entry['id'],'label':entry['title'],'kind':'AUTHORITY_CANDIDATE'}
        edges.append({'source':'SOURCE-'+entry['source_id'],'target':entry['id'],'relation':'OCCURS_ON_PAGE',
                      'page':entry['page'],'approval_status':'UNKNOWN'})
        for body,role in entry['roles'].items():
            bid='BODY-'+hashlib.sha256(body.encode()).hexdigest()[:12]
            nodes[bid]={'id':bid,'label':body,'kind':'BODY_NAMED_IN_SOURCE'}
            edges.append({'source':bid,'target':entry['id'],'relation':role,'page':entry['page'],'approval_status':'UNKNOWN'})
    for unit in data['units']:
        nodes[unit['id']]={'id':unit['id'],'label':unit['name'],'kind':'UNIT_CANDIDATE'}
        sid='SECTOR-'+hashlib.sha256(unit['sector'].encode()).hexdigest()[:12]
        nodes[sid]={'id':sid,'label':unit['sector'],'kind':'SECTOR_CANDIDATE'}
        edges.append({'source':sid,'target':unit['id'],'relation':'DOCUMENT_GROUPS_UNIT','page':unit['page'],
                      'approval_status':'PROPOSED_NOT_APPROVED'})
    data['graph']={'nodes':list(nodes.values()),'edges':edges,'status':'EXTRACTION_NOT_APPROVED_AUTHORITY'}
    return data


def retrieve_candidates(query: str, *, limit: int = 8):
    key=match_key(query)
    if len(key)<3:return []
    data=reference_candidates()
    return [{**item,'kind':kind} for kind,items in [('AUTHORITY',data['authorities']),('RESPONSIBILITY',data['units'])]
            for item in items if key in match_key(item.get('title') or (item.get('name','')+' '+' '.join(item.get('tasks',[]))))][:limit]


def attach_verified_occurrence(registry, observation_id, candidate, source: SourceRecord, path: Path):
    """Only a matching source hash + actual page text may enter role evidence.

    The existing agent context builder will carry UNVERIFIED/NOT_ESTABLISHED
    status through its normal purpose-limited evidence payloads. No private
    adjudicator instructions or external calls are introduced.
    """
    import pymupdf
    if hashlib.sha256(path.read_bytes()).hexdigest()!=source.sha256:
        raise ValueError('REFERENCE_SOURCE_INTEGRITY_FAILED')
    if candidate.get('source_id')!=source.id:
        raise ValueError('REFERENCE_SOURCE_BINDING_MISMATCH')
    with pymupdf.open(path) as document:
        page=int(candidate['page'])
        if page<1 or page>len(document):raise ValueError('REFERENCE_PAGE_INVALID')
        text=candidate.get('title') or candidate.get('name','')
        if not text or match_key(text) not in match_key(document[page-1].get_text()):
            raise ValueError('REFERENCE_OCCURRENCE_NOT_VERIFIED')
    item=registry.add_policy(source.id,text,approval_status='UNVERIFIED',applicability='NOT_ESTABLISHED',
        file=path.name,sha256=source.sha256,location=f'page {page}',version=source.version)
    registry.attach_basis(observation_id,item.id)
    return item


def change_impact(previous: dict, current: dict):
    """Candidate diff only; never activates a new reference version."""
    old={x['id']:x for x in previous.get('authorities',[])+previous.get('units',[])}
    new={x['id']:x for x in current.get('authorities',[])+current.get('units',[])}
    return {'added':sorted(new.keys()-old.keys()),'removed':sorted(old.keys()-new.keys()),
            'modified':sorted(k for k in old.keys()&new.keys() if old[k]!=new[k]),
            'activation':'REQUIRES_AUTHORIZED_HUMAN_RECONCILIATION'}
