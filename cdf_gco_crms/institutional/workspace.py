"""In-process private workspace adapter, intentionally not exposed by the demo API.

An institution must supply its trusted identity/resource authorizer. The default
provider denies every operation. Even authorized reads/exports never confer issue
permission; the existing central release gate remains mandatory.
"""
from ..calibration.service import CalibrationService
from ..calibration.store import ReviewerContext
from ..intelligence.service import IntelligenceService
from .contracts import AccessContext, InstitutionalAccessDenied
from .providers import PrivateInstitutionalProvider


class PrivateWorkspace:
    def __init__(self, calibration: CalibrationService, references: PrivateInstitutionalProvider):
        self.calibration=calibration
        self.references=references
        self.intelligence=IntelligenceService(calibration)

    def _principal(self, case_id: str, context: AccessContext, permission: str):
        if context.case_id!=case_id:
            raise InstitutionalAccessDenied('PRIVATE_CASE_SCOPE_MISMATCH')
        user=self.references.authorize(context,permission,'case:'+case_id)
        if not isinstance(user,ReviewerContext) or not user.authenticated:
            raise InstitutionalAccessDenied('TRUSTED_PRINCIPAL_NOT_RESOLVED')
        from .isolation import bind_private_database
        bind_private_database(self.calibration.store)
        return user

    def import_case(self, case_id, source_hash, observations, context):
        user=self._principal(case_id,context,'case.import')
        return self.calibration.import_case(case_id,source_hash,observations,user)

    def calibrate(self, case_id, observation_id, payload, context):
        user=self._principal(case_id,context,'case.calibrate')
        return self.calibration.decision(case_id,observation_id,payload,user)

    def capture(self, case_id, execution, trace_records, context, *, gate_dir, trust_store=None):
        user=self._principal(case_id,context,'case.capture')
        return self.intelligence.capture(case_id,execution,trace_records,user,gate_dir=gate_dir,trust_store=trust_store)

    def dashboard(self, case_id, context):
        user=self._principal(case_id,context,'case.read')
        self.calibration.authorize(case_id,user)
        observations=self.calibration.store.observations(case_id,user)
        events=self.calibration.store.events(case_id,user)
        snapshot=self.intelligence._snapshot(case_id)
        return self.intelligence._project(case_id,observations,events,snapshot,user,
                                         synthetic=snapshot.synthetic if snapshot else False)

    def export(self, case_id, kind, context, *, brand_asset_id):
        self._principal(case_id,context,'case.export')
        data=self.dashboard(case_id,context)
        data['reference_catalog']=self.references.catalog(context)
        logo=self.references.asset(brand_asset_id,context)
        from ..intelligence.exports import _render_dashboard
        return _render_dashboard(data,kind,logo=logo)

    def retrieve_into_evidence(self, observation_id, query, registry, context, *, limit=4):
        """Purpose-limited reference occurrence evidence for existing role contexts.

        Unknown source approval/applicability stays UNVERIFIED/NOT_ESTABLISHED.
        No model is called and no external processing permission is inferred.
        """
        if context.case_id is None:raise InstitutionalAccessDenied('PRIVATE_CASE_SCOPE_REQUIRED')
        self._principal(context.case_id,context,'reference.attach')
        self.calibration.authorize(context.case_id,self._principal(context.case_id,context,'case.read'))
        if observation_id not in {o['observation_id'] for o in self.calibration.store.observations(
                context.case_id,self._principal(context.case_id,context,'case.read'))}:
            raise InstitutionalAccessDenied('OBSERVATION_OUTSIDE_PRIVATE_CASE')
        from ..intelligence.references import attach_verified_occurrence, SourceRecord
        from ..references.textnorm import match_key
        data=self.references.catalog(context);sources={s['id']:s for s in data['sources']}
        key=match_key(query)
        if len(key)<3:return []
        matches=[a for a in data['authorities'] if key in match_key(a['title'])]
        matches += [dict(u,title=u['name']) for u in data['units']
                    if key in match_key(u['name']+' '+' '.join(u['tasks']))]
        attached=[]
        for item in matches[:max(0,min(limit,8))]:
            raw=sources[item['source_id']]
            source=SourceRecord.model_validate({k:v for k,v in raw.items() if k in SourceRecord.model_fields})
            attached.append(attach_verified_occurrence(registry,observation_id,item,source,
                              self.references.source_path(source.id,context)).id)
        return attached

    def execute_review(self, state, document, context, *, index, reference_queries, runner=None,
                       mat_profile=None, gate_dir, draft=False):
        """Existing orchestrator plus scoped occurrence retrieval, before any role runs.

        Provider processing requires a separate trusted authorization decision. It
        is never implied by access to the references or a developer mode flag.
        """
        import hashlib
        from pathlib import Path
        from ..agents.orchestrator import ReviewOrchestrator
        principal=self._principal(context.case_id,context,'case.run')
        self.calibration.authorize(context.case_id,principal)
        if getattr(state.document,'is_demo',False):
            # A caller flag must never relabel institutional content as synthetic and skip data authorization.
            raise InstitutionalAccessDenied('PRIVATE_REVIEW_CANNOT_BE_LABELLED_SYNTHETIC')
        case=self.calibration.store._case(context.case_id)
        if hashlib.sha256(Path(document).read_bytes()).hexdigest()!=case['source_hash']:
            raise InstitutionalAccessDenied('PRIVATE_REVIEW_SOURCE_VERSION_MISMATCH')
        expected_ids={o['observation_id'] for o in self.calibration.store.observations(context.case_id,principal)}
        if {o.internal_id for o in state.observations}!=expected_ids:
            raise InstitutionalAccessDenied('PRIVATE_REVIEW_OBSERVATION_BINDING_MISMATCH')
        if runner is not None:
            self._principal(context.case_id,context,'provider.process')
        def enrich(review_state,registry):
            for observation in review_state.observations:
                query=reference_queries.get(observation.internal_id)
                if query:self.retrieve_into_evidence(observation.internal_id,query,registry,context)
        engine=ReviewOrchestrator(index,runner=runner,mat_profile=mat_profile,gate_dir=gate_dir,reference_enricher=enrich)
        return engine.execute(state,document,draft=draft)
