# Institutional reference integration

The accepted baseline is PR #8 at b30dc5f01b5573d707c1ece77b42c1a3e690a0ae. React/TypeScript, ECharts, React Flow, FastAPI, SQLite, the orchestrator, MAT, evidence/provenance contracts and release authorization are retained.

## Two operating modes

| Mode | Data and permissions | Activation |
|---|---|---|
| PUBLIC_SYNTHETIC_DEMO | Fixed fictional reference provider, synthetic case database, explicitly publication-authorized original logo assets | Independently operable; loopback developer authentication only |
| PRIVATE_INSTITUTIONAL | Protected original copies, source/version/brand registries, scoped case permissions, actual review executions and draft exports | In-process implementation; default deny-all authorizer; production HTTP activation disabled |

`PublicSyntheticProvider` accepts no storage-root/configuration parameter. It loads only shared/demo-reference-fixtures.json and registered public branding. Institutional source configuration cannot change its dataset. `PrivateInstitutionalProvider` authorizes each read before touching storage, validates content hashes, registry binding, version conflicts and path containment, and keeps no shared cache. A trusted institutional identity/resource adapter must implement `InstitutionalAuthorizer`. A caller-supplied role, mode flag or frontend token is not an institutional grant. Synthetic authorizers exist only in tests.

`PrivateWorkspace` binds the resolved authenticated reviewer to the exact case, existing calibration grants and a separate database mode. It supports case import, execution capture, dashboard projection, reference retrieval, actual existing-orchestrator review and draft exports. Provider processing requires its own permission. No institutionally authenticated HTTP service is enabled by this work.

## Sources and original preservation

The five supplied Drive IDs were re-read through the connected Google Drive service; fresh raw copies matched all five preserved originals. Original PDFs/images, hashes, metadata, extraction outputs and revalidation evidence live under ignored authorized private storage. The DoA title page was visually checked: 30 April 2024. Source approval, effective date, approving authority and supersession remain unverified. The organizational proposal remains PROPOSED_NOT_APPROVED. Access and byte identity do not establish approval or currency.

The previous user explicitly declared source copies and extraction candidates public. That historical authorization is recorded in PR #8; its commits are preserved. This follow-up removes real reference datasets/hashes from the current shared distribution and uses fictional demo fixtures to meet the new mode-isolation requirement. It does not rewrite previously published history or imply historical copies became secret. Original logos remain available only because publication was explicitly authorized; future restricted variants belong exclusively in private storage.

## Reproduce private ingestion

Prepare an authorized private source manifest; no source is downloaded automatically:

```sh
python tools/ingest_institutional_references.py \
  --source-directory private/institutional_sources \
  --manifest private/reference-registry/sources.json \
  --output private/reference-registry
```

The tool hashes inputs, preserves immutable copies by digest, reuses existing PDF geometry/layout parsers and records inactive source versions. It refuses public output directories inside this repository. The old ingest_public_references.py name remains as a compatibility entry point with private defaults and the same output restriction. Updating a version never activates authority.

## Reference-to-agent path

PrivateWorkspace.execute_review checks case/source version and uses a small optional reference_enricher hook before existing role contexts are built. Human-provided observation queries retrieve candidates, verify original hash/page occurrence and attach UNVERIFIED/NOT_ESTABLISHED evidence through the existing registry. Drafting, MAT, Black Team, Red Advocate, adjudicator and final reviewer receive the existing purpose-limited contexts. The hook does not give MAT adjudication authority, change cycle limits, approve applicability or permit external processing. The existing central gate remains mandatory for official issuance.

Production prerequisites remain PENDING_AUTHORIZATION: real identity/tenancy and session verification, role provisioning, storage ACLs/encryption/backups, data-processing permission, source/brand approval verification, operational/security assessment and human institutional acceptance. No developer test supplies that approval.
