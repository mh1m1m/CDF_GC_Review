# Integration matrix

| From → To | Existing integration | Acceptance and remaining boundary |
|---|---|---|
| CLI → review orchestrator | main.py → agents/orchestrator.py | Synthetic end-to-end tests; real provider not executed |
| Black → Red → adjudicator | agents/debate.py and roles.py | Fresh role contexts, six productive cycles, evidence guards; preserve firewall |
| MAT → drafting/interrogation/reassessment | agents/mat_advisor.py with orchestrator/debate | Advisory turns disclosed; never issue or approve |
| Word/XLSX → calibration | calibration/importer.py and excel_importer.py | Offline import tests, source/evidence binding, ZIP limits |
| UI → API → SQLite | apps/web/src/main.tsx → apps/api/main.py → calibration/service.py/store.py | Synthetic loopback token only; browser persistence/RTL checks |
| Calibration → DNA profile | calibration/profile_compiler.py → store.py → agents/mat_profile.py | Separate latest rule approval, immutable synthetic snapshot, no institutional binding |
| Human signature → register revision | assurance/objection_engine.py → release/dispositions.py | Sign exact challenge/proposal digest; changed proposal rejected |
| Review → official exporter | release/authorization_gate.py, attestation.py → CLI Word/Excel | State/source, trust/expiry and required provenance; no authorized production run |
| Excel → independent recalc | qa/recalc_verify.py → qa/lo_engine.py | Local runtime timeout remains unresolved; do not claim formula reconciliation |
