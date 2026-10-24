"""Persist actual orchestrator executions and project auditable executive measures.

No provider is called here. No HTTP import of execution claims is exposed.
Local checksums/hash chains establish local consistency, not external attestation.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from opentelemetry import trace

from ..assurance.objection_engine import APPROVED
from ..agents import provenance as PV
from ..agents.security import sanitize
from ..calibration.analytics import analyze
from ..calibration.service import CalibrationService
from ..calibration.store import CalibrationError, AccessDenied, canonical, fingerprint
from ..release.authorization_gate import authorize, PURPOSE_INSTITUTIONAL

RENDER_SPEC=json.loads((Path(__file__).resolve().parents[2]/'shared/rendering-specification.json').read_text())
TRACER = trace.get_tracer('cdf.intelligence')
STAGES = ['DRAFTING', 'MAT-01', 'BLACK_TEAM', 'MAT-02', 'RED_ADVOCATE', 'MAT-03', 'ADJUDICATOR', 'FINAL_REVIEWER']


class ExecutionSnapshot(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: str = 'CDF-EXECUTIVE-v1'
    run_id: str = Field(min_length=1, max_length=150)
    evidence_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    source_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    synthetic: bool
    captured_at: str
    execution: dict
    registry: dict
    trace_records: list[dict] = Field(max_length=2000)
    observations: list[dict] = Field(max_length=1000)
    release_check_at_run: dict


def measure(key, title, numerator, denominator, lineage, limitation, *, unit='percent'):
    """A zero/missing denominator is unknown, never a fabricated zero score."""
    value = None
    if numerator is not None and denominator is not None and denominator > 0:
        if not 0 <= numerator <= denominator:
            raise CalibrationError('INVALID_METRIC_FRACTION')
        value = round(100 * numerator / denominator, 1) if unit == 'percent' else numerator
    return {'id': key, 'title': title, 'numerator': numerator, 'denominator': denominator,
            'value': value, 'unit': unit, 'lineage': lineage, 'limitation': limitation,
            'status': 'MEASURED' if value is not None else 'NOT_ESTABLISHED',
            'threshold_source': None, 'confidence': None}


class IntelligenceService:
    def __init__(self, calibration: CalibrationService):
        self.calibration = calibration
        self.store = calibration.store
        self.store.db.execute('''CREATE TABLE IF NOT EXISTS executive_runs (
            case_id TEXT NOT NULL REFERENCES cases(case_id), run_id TEXT NOT NULL,
            snapshot_json TEXT NOT NULL, snapshot_hash TEXT NOT NULL, captured_at TEXT NOT NULL,
            PRIMARY KEY(case_id, run_id))''')
        self.store.db.commit()

    def capture(self, case_id, execution, trace_records, user, *, gate_dir, trust_store=None):
        """Trusted in-process adapter for ReviewExecution; it cannot issue or mutate observations."""
        self.calibration.authorize(case_id, user, 'CALIBRATION_ADMIN')
        case = self.store._case(case_id)
        if case['source_hash'] != execution.document_sha256:
            raise CalibrationError('EXECUTION_SOURCE_VERSION_MISMATCH')
        ids = {o['observation_id'] for o in self.store.observations(case_id, user)}
        if {o.internal_id for o in execution.state.observations} != ids:
            raise CalibrationError('EXECUTION_OBSERVATION_BINDING_MISMATCH')
        gate = authorize(execution.state, gate_dir, trust_store=trust_store,
                         source_document_sha256=execution.document_sha256, purpose=PURPOSE_INSTITUTIONAL)
        snap = ExecutionSnapshot(run_id=execution.run_id, evidence_hash=case['evidence_hash'],
            source_hash=execution.document_sha256, synthetic=bool(execution.state.document.is_demo),
            captured_at=datetime.now(timezone.utc).isoformat(), execution={**execution.to_dict(), "intelligence_dispositions": [
                {"observation_id": entry.internal_id, **o.adjudication}
                for entry in execution.record.entries for o in entry.objections]},
            registry=execution.registry.to_dict(), trace_records=trace_records,
            observations=[{'id': o.internal_id, 'location': str(o.location), 'comment': str(o.comment)}
                          for o in execution.state.ordered()],
            release_check_at_run={'authorized': gate.ok, 'reasons': gate.reasons,
                                  'purpose': PURPOSE_INSTITUTIONAL, 'current_authority': False})
        text = snap.model_dump_json()
        with self.store.db:
            self.store.db.execute('INSERT INTO executive_runs VALUES (?,?,?,?,?)',
                (case_id, snap.run_id, text, hashlib.sha256(text.encode()).hexdigest(), snap.captured_at))
            self.store._append(case_id, None, 'EXECUTION_CAPTURED',
                {'run_id': snap.run_id, 'snapshot_hash': hashlib.sha256(text.encode()).hexdigest()}, user.reviewer_id)
        return snap.run_id

    def _snapshot(self, case_id, run_id=None):
        if run_id:
            row = self.store.db.execute('SELECT * FROM executive_runs WHERE case_id=? AND run_id=? ORDER BY captured_at DESC LIMIT 1', (case_id,run_id)).fetchone()
        else:
            row = self.store.db.execute('SELECT * FROM executive_runs WHERE case_id=? ORDER BY captured_at DESC LIMIT 1',(case_id,)).fetchone()
        if row is None:
            return None
        if hashlib.sha256(row['snapshot_json'].encode()).hexdigest() != row['snapshot_hash']:
            raise CalibrationError('EXECUTION_SNAPSHOT_INTEGRITY_FAILED')
        snap = ExecutionSnapshot.model_validate_json(row['snapshot_json'])
        case = self.store._case(case_id)
        if snap.evidence_hash != case['evidence_hash'] or snap.source_hash != case['source_hash']:
            raise CalibrationError('EXECUTION_CASE_VERSION_MISMATCH')
        return snap

    def dashboard(self, case_id, user):
        self.calibration.authorize(case_id, user)
        with TRACER.start_as_current_span('intelligence.project') as span:
            # No case IDs, reviewer IDs, prompts, excerpts or document names in telemetry.
            observations = self.store.observations(case_id, user)
            events = self.store.events(case_id, user)
            snap = self._snapshot(case_id)
            if snap and not snap.synthetic:
                raise AccessDenied('INSTITUTIONAL_EXECUTION_NOT_ALLOWED_IN_SYNTHETIC_API')
            span.set_attribute('cdf.synthetic', True)
            span.set_attribute('cdf.observation_count', len(observations))
            return self._project(case_id, observations, events, snap, user)

    def _project(self, case_id, observations, events, snap, user, *, synthetic=True):
        latest = {}
        latest_event_ids = {}
        for event in events:
            if event['event_type'] == 'OBSERVATION_CALIBRATION':
                payload = json.loads(event['payload_json'])
                if payload.get('status') == 'SUBMITTED':
                    latest[event['observation_id']] = payload
                    latest_event_ids[event['observation_id']] = event['event_hash']
        raw = snap.execution if snap else {}
        registry = snap.registry if snap else {'items': [], 'basis': {}}
        evidence = {item['id']: item for item in registry.get('items', [])}
        trace_records = snap.trace_records if snap else []
        chain_ok, trace_head, _ = PV.verify_chain(trace_records) if trace_records else (False, '', '')
        chain_ok = bool(chain_ok and trace_head == raw.get('trace_summary', {}).get('trace_head_hash')
                        and all(r.get('Run_ID') == raw.get('run_id') and r.get('Review_State_Fingerprint') == raw.get('fingerprint') for r in trace_records))
        trace_by_id = {r['Execution_ID']: r for r in trace_records}
        mat_states = raw.get('mat_advisor', {}).get('observation_state', {})
        mat_stages = {}
        for state in mat_states.values():
            if state.get('MAT_Drafting_Execution_ID'):
                mat_stages[state['MAT_Drafting_Execution_ID']] = 'MAT-01'
            for eid in state.get('MAT_Interrogation_Execution_ID', []): mat_stages[eid] = 'MAT-02'
            for eid in state.get('MAT_Reassessment_Execution_ID', []): mat_stages[eid] = 'MAT-03'
        invocations = []
        for i, outcome in enumerate(raw.get('role_outcomes', [])):
            eid = outcome.get('execution_id')
            rec = trace_by_id.get(eid, {})
            source = rec.get('Execution_Source') if chain_ok else None
            if not source:
                source = PV.SOURCE_DETERMINISTIC if outcome.get('mode') == 'DETERMINISTIC' else 'UNVERIFIED'
            stage = outcome.get('stage') or mat_stages.get(eid) or outcome['role']
            if stage.startswith('MAT-'): stage=stage[:6]
            invocations.append({'id': eid or f'local-{i}', 'role': outcome['role'], 'stage': stage,
                'status': outcome['status'], 'mode': outcome['mode'], 'source': source,
                'observation_id': outcome.get('observation_id'), 'challenge_id': outcome.get('challenge_id'),
                'context_id': outcome.get('context_id'), 'timestamp': rec.get('Timestamp'),
                'latency_ms': rec.get('Latency_ms'),
                'evidence_refs': [x for x in rec.get('Evidence_References', []) if x in evidence]})
        objections = []
        # Challenge entries are projected directly from persisted execution exchanges.
        for cid, exchange in raw.get('exchanges', {}).items():
            outcome = next((o for o in raw.get('role_outcomes', []) if o.get('challenge_id') == cid), {})
            objections.append({'id': cid, 'observation_id': outcome.get('observation_id'), **exchange})
        # Final dispositions are stored by the capture adapter below.
        dispositions = raw.get('intelligence_dispositions', [])
        for objection in objections:
            adjudication = next((d for d in dispositions if d['challenge_id'] == objection['id']), {})
            objection['disposition'] = adjudication.get('disposition', 'NOT_RECORDED')
            objection['rationale'] = adjudication.get('rationale')
            objection['resolved'] = adjudication.get('disposition') in ('UPHELD_UNCHANGED', 'UPHELD_WITH_REVISION', 'NARROWED_TO_GCO_SCOPE', 'ROUTED_OUTSIDE_GCO')
        supporting = {oid for oid, refs in registry.get('basis', {}).items()
                      if oid in {o['observation_id'] for o in observations} and any(evidence.get(ref, {}).get('kind') != 'DOCUMENT'
                             and evidence.get(ref, {}).get('approval_status') in APPROVED
                             and evidence.get(ref, {}).get('applicability') == 'APPLICABLE' for ref in refs)}
        attempts = sum(sum(t.get('actor')=='BLACK' for t in o.get('turns', [])) +
                       sum(a.get('actor')=='BLACK' for a in o.get('unproductive_attempts', [])) for o in objections)
        repeats = sum(a.get('actor')=='BLACK' and a.get('reason') in ('EXACT_REPEAT', 'NGRAM_REPEAT', 'JACCARD_REPEAT')
                      for o in objections for a in o.get('unproductive_attempts', []))
        reassessments = [x for state in mat_states.values() for x in state.get('MAT_Final_Advisory_Position', [])]
        unresolved_material = [o['observation_id'] for o in observations if o.get('material_categories')
            and (o['observation_id'] not in latest or latest[o['observation_id']]['decision'] in ('WITHDRAW', 'ESCALATE', 'REQUEST_MORE_EVIDENCE'))]
        metrics = [
            measure('evidence_coverage', 'تغطية الأدلة المرجعية', len(supporting), len(observations),
                    ['registry.basis', 'registry.items'], 'مصدر مرجعي معتمد وقابل للتطبيق فقط؛ وجود النص في الوثيقة ليس اعتماداً مرجعياً.'),
            measure('objections_resolved', 'حسم الاعتراضات', sum(o['resolved'] for o in objections), len(objections),
                    ['execution.exchanges', 'adjudicator.disposition'], 'الحسم المسجل لا يساوي موافقة بشرية أو تصريح إصدار.'),
            measure('repeat_objections', 'تكرار اعتراضات الفريق الأسود', repeats, attempts, ['exchange.unproductive_attempts', 'exchange.productive_cycles'],
                    'محاولات التكرار التي رصدتها قواعد المحرك فقط، وليست تقييماً لغوياً مستقلاً.'),
            measure('mat_reversal', 'مراجعة موقف MAT', sum(x.get('position_changed') is True for x in reassessments), len(reassessments),
                    ['mat_advisor.observation_state.MAT_Final_Advisory_Position'], 'تغير الموقف المسجل؛ لا يقيس جودة المنهجية أو تفضيل المراجع.'),
            measure('authorization_readiness', 'جاهزية التصريح المسجلة',
                    0 if snap and not snap.release_check_at_run['authorized'] else None, 1 if snap else None,
                    ['release.authorize.INSTITUTIONAL_ISSUE'], 'فشل شرط إلزامي يحجب الإصدار؛ النجاح المسجل لا يغني عن إعادة التحقق عند الإصدار.'),
            measure('material_open', 'الملاحظات المادية المفتوحة', len(unresolved_material),
                    sum(bool(o.get('material_categories')) for o in observations), ['observations.material_categories', 'events.OBSERVATION_CALIBRATION'],
                    'حصة الملاحظات المادية التي تنتظر تسوية بشرية؛ ليست درجة خطر أو احتمال خسارة.'),
            measure('human_alignment', 'التوافق مع المراجع', None, None, [], 'غير مقاس: لا توجد تسميات بشرية مستقلة متحققة مرتبطة بتنبؤات النموذج.'),
            measure('calibration', 'تغطية المعايرة', len(latest), len(observations), ['events.OBSERVATION_CALIBRATION'],
                    'قرارات مقدمة مميزة لكل ملاحظة؛ هويات التجربة ليست توقيعات مؤسسية.'),
        ]
        metric_records={
            'evidence_coverage': sorted({ref for oid in supporting for ref in registry.get('basis',{}).get(oid,[])}),
            'objections_resolved': [o['id'] for o in objections],
            'repeat_objections': [o['id'] for o in objections],
            'mat_reversal': [i['id'] for i in invocations if i['stage']=='MAT-03'],
            'authorization_readiness': [snap.run_id] if snap else [],
            'material_open': [o['observation_id'] for o in observations if o.get('material_categories')],
            'human_alignment': [], 'calibration': list(latest_event_ids.values())}
        for metric in metrics:
            metric.update(definition=RENDER_SPEC['metric_definitions'][metric['id']],
                          source_records=metric_records[metric['id']],threshold_basis=None,
                          unknown_handling='NULL_WHEN_MISSING_LABELS_OR_ZERO_DENOMINATOR',
                          evidence_status='RECORDED_SOURCE_STATUS_PRESERVED',
                          rendering_spec=RENDER_SPEC['schema'])
            metric.update(synthetic=synthetic, calculated_at=datetime.now(timezone.utc).isoformat(),
                          evidence_hash=self.store._case(case_id)['evidence_hash'])
        heatmap = []
        for category in sorted({c for o in observations for c in o.get('material_categories', [])}):
            ids = [o['observation_id'] for o in observations if category in o.get('material_categories', [])]
            heatmap.append({'category': category, 'pending': sum(i not in latest for i in ids),
                            'submitted': sum(i in latest for i in ids), 'lineage': ids})
        live = sum(i['source'] == PV.SOURCE_PROVIDER_API and i['status'] == 'OK' for i in invocations)
        return {'schema': 'CDF-COMMAND-CENTER-v1', 'case_id': case_id, 'synthetic': synthetic,
            'run_id': snap.run_id if snap else None, 'captured_at': snap.captured_at if snap else None,
            'evidence_hash': self.store._case(case_id)['evidence_hash'], 'metrics': metrics,
            'observation_count': len(observations), 'unresolved_material': unresolved_material,
            'invocations': invocations, 'trace_integrity': chain_ok, 'actual_live_inference_count': live,
            'execution_sources': dict(Counter(i['source'] for i in invocations)),
            'objections': objections, 'stages': STAGES, 'heatmap': heatmap,
            'observations': [{**o, 'calibration': latest.get(o['observation_id'])} for o in observations],
            'evidence': [{**e, 'excerpt': sanitize(e.get('excerpt', ''))} for e in evidence.values()],
            'evidence_links': [{'observation_id': oid, 'evidence_id': ref} for oid, refs in registry.get('basis', {}).items() for ref in refs if ref in evidence],
            'timeline': [{'id': e['event_hash'], 'kind': e['event_type'], 'at': e['created_at'],
                          'observation_id': e['observation_id']} for e in events],
            'release_gate': snap.release_check_at_run if snap else {'authorized': False, 'current_authority': False, 'reasons': ['NO_RECORDED_REVIEW']},
            'calibration_analytics': analyze(self.store, case_id, user),
            'limitations': (['SYNTHETIC_LOCAL_DEV'] if synthetic else ['PRIVATE_INSTITUTIONAL_DRAFT']) + [ 'LOCAL_HASH_CHAIN_NOT_EXTERNAL_ATTESTATION', 'SNAPSHOT_NOT_REALTIME', 'MAT_ADVISORY_ONLY', 'NOT_INSTITUTIONALLY_AUTHORIZED']}
