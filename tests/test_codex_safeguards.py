"""Synthetic negative regressions for the Codex takeover audit findings."""
import base64
import datetime as dt
from dataclasses import replace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cdf_gco_crms.release import attestation as A
from cdf_gco_crms.release.trust import TrustStore
from cdf_gco_crms.release.dispositions import apply_dispositions, revision_digest
from cdf_gco_crms.calibration.store import CalibrationStore, ReviewerContext, CalibrationError
from cdf_gco_crms.calibration.profile_compiler import compile_candidate
from test_release_lifecycle import _state, _revision_execution, Signer, NOW


@pytest.mark.parametrize('start,end,reason', [
    (-3,-1,'ATTESTATION_KEY_EXPIRED'), (1,3,'ATTESTATION_KEY_NOT_YET_VALID'),
    ('bad',3,'ATTESTATION_KEY_VALIDITY_INVALID'),
])
def test_attestor_key_window(start,end,reason):
    key=Ed25519PrivateKey.generate()
    private=key.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption())
    public=key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
    trust=TrustStore.from_raw({'TEST':public}, roles=('RELEASE_ATTESTOR',), synthetic=True)
    # Synthetic key is allowed for a demo; its dates must still be enforced.
    trust.keys['TEST'].valid_from=(NOW+dt.timedelta(days=start)).isoformat() if isinstance(start,int) else start
    trust.keys['TEST'].valid_until=(NOW+dt.timedelta(days=end)).isoformat()
    payload=A.build_payload({'fingerprint':'fp','source_document_sha256':'doc','challenge_record_sha256':'record'},
                            purpose=A.PURPOSE_DEMO, now=NOW)
    att=A.sign(payload, private, 'TEST')
    assert reason in A.verify(att,trust,now=NOW,fingerprint='fp',document_sha256='doc',
                             challenge_record_sha256='record',purpose=A.PURPOSE_DEMO)


@pytest.mark.parametrize('field', ['revised_comment','revised_quote'])
def test_signed_revision_rejects_changed_proposal(tmp_path, field):
    state=_state(demo=False)
    execution,target,_=_revision_execution(tmp_path,state)
    signer=Signer()
    obj=next(o for e in execution.record.entries for o in e.objections if e.internal_id==target.internal_id)
    decision=signer.decision(target.internal_id,'UPHELD_WITH_REVISION',fingerprint=execution.fingerprint)
    decision=replace(decision,challenge_id=obj.challenge_id,
        revision_sha256=revision_digest(obj.challenge_id,obj.advocacy.get('revised_comment'),obj.advocacy.get('revised_quote')))
    decision=replace(decision,signature_b64=base64.b64encode(signer.priv.sign(decision.signature_payload())).decode())
    obj.advocacy[field]='Synthetic substituted proposal'
    result=apply_dispositions(state,execution.record,[decision],signer.store(),expected_fingerprint=execution.fingerprint,now=NOW)
    assert not result.changed and not result.applied
    assert result.rejected[0]['reason']=='SIGNED_REVISION_BINDING_REQUIRED'


@pytest.mark.parametrize('action',['REJECT','DEFER','REQUEST_MORE_EVIDENCE','APPROVE_WITH_CHANGES'])
def test_latest_rule_review_supersedes_old_approval(tmp_path,action):
    with_case(tmp_path,action)


def with_case(tmp_path, action=None):
    store=CalibrationStore(tmp_path/'synthetic.sqlite')
    try:
        user=ReviewerContext('SYN-TEST',frozenset({'CALIBRATION_ADMIN','CALIBRATION_REVIEWER','DNA_RULE_APPROVER'}),True)
        digest=store.import_case('SYN-CASE','a'*64,[{'observation_id':'SYN-1','original_text':'Synthetic fixture'}],user)
        event=store.save_decision('SYN-CASE','SYN-1','KEEP_UNCHANGED','Synthetic rationale',digest,user,status='SUBMITTED')
        store.rule_action('SYN-CASE','SYN-S01','APPROVE','Synthetic approval',user,observation_event_hashes=[event],profile_version='0.1.0-synthetic')
        if action:
            store.rule_action('SYN-CASE','SYN-S01',action,'Synthetic later review',user,observation_event_hashes=[event],profile_version='0.1.0-synthetic')
            with pytest.raises(CalibrationError,match='APPROVED_SYNTHETIC_RULE_REQUIRED'):
                compile_candidate(store,'SYN-CASE',user)
        else:
            first=compile_candidate(store,'SYN-CASE',user)
            before=len(store.events('SYN-CASE',user))
            second=compile_candidate(store,'SYN-CASE',user)
            assert first==second
            assert len(store.profile_versions('SYN-CASE',user))==1
            assert len(store.events('SYN-CASE',user))==before
            assert store.verify_chain('SYN-CASE',user)
    finally:
        store.close()


def test_compile_retry_returns_existing_immutable_snapshot(tmp_path):
    with_case(tmp_path)
