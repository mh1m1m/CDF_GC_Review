"""Provider-independent lookups with no shared caches, credentials or telemetry.

Public construction has no path/configuration parameter. Private construction does
not touch storage until a trusted authorizer approves each operation. The supplied
production adapter is deny-all: an environment flag never grants access.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Protocol

from ..references.textnorm import match_key
from .contracts import (AccessContext, BrandAsset, DenyAllAuthorizer, DoARecord,
                        InstitutionalAccessDenied, InstitutionalAuthorizer,
                        OperatingMode, ResponsibilityRecord)

ROOT = Path(__file__).resolve().parents[2]


class ReferenceProvider(Protocol):
    mode: OperatingMode
    def catalog(self, context: AccessContext | None = None) -> dict: ...


def currency(source: dict) -> dict:
    reasons=[]
    if source.get('approval_status') not in ('APPROVED_CURRENT','EXTERNAL_BINDING'):
        reasons.append('APPROVAL_NOT_VERIFIED')
    if source.get('effective_date') in (None,'NOT_VERIFIED','UNKNOWN'):
        reasons.append('EFFECTIVE_DATE_NOT_VERIFIED')
    if not source.get('supersession_checked'): reasons.append('SUPERSESSION_NOT_VERIFIED')
    if source.get('superseded_by'): reasons.append('SOURCE_SUPERSEDED')
    effective=source.get('effective_date')
    if effective not in (None,'NOT_VERIFIED','UNKNOWN','NOT_APPLICABLE'):
        try:
            if date.fromisoformat(effective)>date.today():reasons.append('SOURCE_NOT_YET_EFFECTIVE')
        except ValueError:reasons.append('EFFECTIVE_DATE_INVALID')
    # Source declarations alone do not authenticate the approving institution.
    if source.get('source_confidence') != 'INSTITUTIONALLY_VERIFIED_RECORD':
        reasons.append('INSTITUTIONAL_VERIFICATION_NOT_ESTABLISHED')
    return {'source_id':source['id'],'version':source['version'],
            'status':'NOT_ESTABLISHED' if reasons else 'RECORDED_VERIFIED_REQUIRES_ISSUE_TIME_CHECK',
            'reasons':reasons,'binding_authority_granted':False}


class VersionRegistry:
    """Compare observed versions; never silently select the permissive record."""
    @staticmethod
    def active(records: list[dict]) -> list[dict]:
        return [r for r in records if not (r.get('supersession_verified') is True and r.get('superseded_by'))]

    @staticmethod
    def conflicts(records: list[dict]) -> list[dict]:
        result=[]
        by_source={}
        for record in records: by_source.setdefault(record['id'],[]).append(record)
        for source_id, versions in by_source.items():
            hashes={r['sha256'] for r in versions}
            active_hashes={r['sha256'] for r in VersionRegistry.active(versions)}
            if len(hashes)>1:
                same_version=len({r['version'] for r in versions})<len(hashes)
                if not same_version and len(active_hashes)<=1:continue
                result.append({'source_id':source_id,'kind':'SAME_VERSION_DIFFERENT_CONTENT' if same_version else 'MULTIPLE_VERSIONS_REQUIRE_RECONCILIATION',
                               'activation':'BLOCKED_PENDING_HUMAN_RECONCILIATION'})
        return result


class PublicSyntheticProvider:
    mode=OperatingMode.PUBLIC_SYNTHETIC_DEMO

    def catalog(self, context: AccessContext | None = None) -> dict:
        data=json.loads((ROOT/'shared/demo-reference-fixtures.json').read_text())
        if data.get('synthetic') is not True or any(not r['id'].startswith('SYN-')
                for r in data['sources']+data['authorities']+data['units']):
            raise InstitutionalAccessDenied('PUBLIC_FIXTURE_CLASSIFICATION_INVALID')
        return deepcopy(data)

    def private_record(self, *args, **kwargs):
        raise InstitutionalAccessDenied('PUBLIC_MODE_CANNOT_READ_PRIVATE_RECORDS')

    def asset(self, asset_id: str, context=None) -> bytes:
        # Only explicitly publication-authorized assets in the public manifest.
        data=json.loads((ROOT/'shared/logo-registry.json').read_text())
        asset=next((x for x in data['assets'] if x['variant_id']==asset_id),None)
        if asset is None or asset['publication_status']!='USER_DECLARED_PUBLIC':
            raise InstitutionalAccessDenied('PUBLIC_BRAND_NOT_AUTHORIZED')
        path=ROOT/'apps/web/public'/asset['public_filename']
        if path.parent != ROOT/'apps/web/public':
            raise InstitutionalAccessDenied('PUBLIC_ASSET_PATH_INVALID')
        content=path.read_bytes()
        if hashlib.sha256(content).hexdigest()!=asset['integrity_sha256']:
            raise InstitutionalAccessDenied('PUBLIC_ASSET_INTEGRITY_FAILED')
        return content


class PrivateInstitutionalProvider:
    mode=OperatingMode.PRIVATE_INSTITUTIONAL

    def __init__(self, storage_root: Path, authorizer: InstitutionalAuthorizer | None = None):
        self.root=Path(storage_root)  # no read/resolve until authorization
        self.authorizer=authorizer or DenyAllAuthorizer()

    def authorize(self, context: AccessContext | None, permission: str, resource: str):
        if context is None:raise InstitutionalAccessDenied('PRIVATE_SESSION_REQUIRED')
        self.authorizer.authorize(context,permission,resource)

    def _path(self, relative: str) -> Path:
        root=self.root.resolve(strict=True)
        if Path(relative).is_absolute():
            raise InstitutionalAccessDenied('PRIVATE_STORAGE_ESCAPE')
        path=(root/relative).resolve()
        if not path.is_relative_to(root):
            raise InstitutionalAccessDenied('PRIVATE_STORAGE_ESCAPE')
        return path.resolve(strict=True)

    def _json(self, name):
        return json.loads(self._path(name).read_text())

    def catalog(self, context: AccessContext | None = None) -> dict:
        self.authorize(context,'reference.read','institutional-references')
        data=self._json('candidates.json')
        records=self._json('sources.json')['sources']
        versions=self._json('versions.json').get('versions',records)
        if VersionRegistry.conflicts(versions):
            raise InstitutionalAccessDenied('SOURCE_VERSION_CONFLICT')
        active={(r['id'],r['version'],r['sha256']) for r in VersionRegistry.active(versions)}
        if any((r['id'],r['version'],r['sha256']) not in active for r in records):
            raise InstitutionalAccessDenied('SOURCE_VERSION_NOT_ACTIVE_IN_REGISTRY')
        if data['sources']!=records:
            raise InstitutionalAccessDenied('SOURCE_REGISTRY_BINDING_MISMATCH')
        for source in records:
            content=self._path(source['storage_location']).read_bytes()
            if hashlib.sha256(content).hexdigest()!=source['sha256']:
                raise InstitutionalAccessDenied('SOURCE_CONTENT_INTEGRITY_FAILED')
        data['synthetic']=False
        data['mode']=self.mode.value
        data['currency']=[currency(s) for s in records]
        return data

    def source_path(self, source_id: str, context: AccessContext) -> Path:
        data=self.catalog(context)
        source=next(s for s in data['sources'] if s['id']==source_id)
        return self._path(source['storage_location'])

    def asset(self, asset_id: str, context: AccessContext | None = None) -> bytes:
        self.authorize(context,'brand.read','brand:'+asset_id)
        records=self._json('brands.json')['assets']
        raw=next((x for x in records if x['variant_id']==asset_id),None)
        if raw is None:raise InstitutionalAccessDenied('BRAND_ASSET_NOT_REGISTERED')
        asset=BrandAsset.model_validate(raw)
        if asset.intended_use not in ('AUTHORIZED_DEVELOPMENT','INSTITUTIONAL_REPORT'):
            raise InstitutionalAccessDenied('BRAND_USE_NOT_AUTHORIZED')
        content=self._path(asset.storage_location).read_bytes()
        if hashlib.sha256(content).hexdigest()!=asset.integrity_sha256:
            raise InstitutionalAccessDenied('BRAND_ASSET_INTEGRITY_FAILED')
        return content


class ReferenceLookupService:
    def __init__(self, provider: ReferenceProvider):self.provider=provider

    def authorities(self, query='', context=None, *, role=None, source_id=None, limit=30):
        data=self.provider.catalog(context);sources={s['id']:s for s in data['sources']}
        result=[];key=match_key(query)
        for item in data['authorities']:
            if source_id and item['source_id']!=source_id:continue
            roles=item['roles']
            if role and role not in roles.values():continue
            if key and key not in match_key(' '.join([item['title'],item.get('category',''),*roles.keys(),*roles.values()])):continue
            assigned=lambda label:[body for body,value in roles.items() if value==label] or None
            record=DoARecord(id=item['id'],source_id=item['source_id'],source_version=sources[item['source_id']]['version'],
                page=item['page'],provision=item.get('number',item['id']),business_activity=item['title'],
                authority_category=item.get('category'),preparer=assigned('الإعداد'),reviewer=assigned('المراجعة'),
                recommender=assigned('التوصية'),approver=assigned('الاعتماد'),executor=assigned('التنفيذ'),
                other_roles={b:r for b,r in roles.items() if r not in ('الإعداد','المراجعة','التوصية','الاعتماد','التنفيذ')},
                delegation_conditions=item.get('qualifiers',{}),approval_status=item['approval_status'],synthetic=data.get('synthetic',False))
            result.append(record.model_dump())
        return result[:max(0,min(limit,100))]

    def responsibilities(self, query='', context=None, *, source_id=None, limit=30):
        data=self.provider.catalog(context);sources={s['id']:s for s in data['sources']}
        key=match_key(query);result=[]
        for item in data['units']:
            if source_id and item['source_id']!=source_id:continue
            hay=' '.join([item['name'],item['sector'],*item['tasks'],*item.get('internal_contacts',[])])
            if key and key not in match_key(hay):continue
            result.append(ResponsibilityRecord(id=item['id'],source_id=item['source_id'],source_version=sources[item['source_id']]['version'],
                page=item['page'],name=item['name'],sector=item['sector'],responsibilities=item['tasks'],
                documented_internal_interfaces=item.get('internal_contacts',[]),documented_external_interfaces=item.get('external_contacts',[]),
                approval_status=item['approval_status'],synthetic=data.get('synthetic',False)).model_dump())
        return result[:max(0,min(limit,100))]
