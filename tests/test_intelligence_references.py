import hashlib
from pathlib import Path
import pytest
import pymupdf
from cdf_gco_crms.intelligence.references import SourceRecord,attach_verified_occurrence,change_impact,reference_candidates
from cdf_gco_crms.assurance.evidence import EvidenceRegistry


def test_reference_candidates_do_not_claim_current_authority():
    data=reference_candidates()
    assert all(s['publication_status']=='SYNTHETIC_PUBLIC_FIXTURE' for s in data['sources'])
    assert all(not s['current_authority_confirmed'] for s in data['sources'])
    assert all(item['page']>0 for item in data['authorities']+data['units'])


def test_source_and_page_verification_feed_existing_agent_registry(tmp_path):
    path=tmp_path/'synthetic.pdf';doc=pymupdf.open();page=doc.new_page();page.insert_text((72,72),'Synthetic approval responsibility');doc.save(path);doc.close()
    source=SourceRecord(id='SYN-SOURCE',url='https://example.org/synthetic',sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        version='v1',approval_status='UNKNOWN',effective_date='NOT_VERIFIED',supersession_checked=False,current_authority_confirmed=False,
        publication_status='SYNTHETIC',extraction_status='CANDIDATE')
    candidate={'source_id':source.id,'page':1,'title':'Synthetic approval responsibility'}
    registry=EvidenceRegistry()
    item=attach_verified_occurrence(registry,'SYN-O',candidate,source,path)
    assert registry.basis('SYN-O')==[item]
    assert item.approval_status=='UNVERIFIED' and not item.authority_verified
    with pytest.raises(ValueError,match='OCCURRENCE'):
        attach_verified_occurrence(registry,'SYN-O',{**candidate,'title':'Fabricated authority'},source,path)
    with path.open('ab') as stream:stream.write(b' changed')
    with pytest.raises(ValueError,match='INTEGRITY'):
        attach_verified_occurrence(registry,'SYN-O',candidate,source,path)


def test_reference_refresh_never_activates_candidates():
    result=change_impact({'authorities':[{'id':'a','roles':{'reviewer':'reviews'}}]},
                         {'authorities':[{'id':'a','roles':{'reviewer':'approves'}},{'id':'b'}]})
    assert result['modified']==['a'] and result['added']==['b']
    assert result['activation']=='REQUIRES_AUTHORIZED_HUMAN_RECONCILIATION'
