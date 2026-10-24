# Source register and candidate authority governance

The supplied source copies and extraction candidates were explicitly declared public by the user. `shared/reference-source-manifest.json` records original URLs, exact source hashes, unknown versions/effective dates and publication basis. A source labelled final is not automatically current or approved. The organization document's proposals remain PROPOSED_NOT_APPROVED; authority records remain UNKNOWN, with current_authority_confirmed=false and supersession_checked=false.

`tools/ingest_public_references.py` reproduces candidates from local authorized PDFs named doa.pdf, organization.pdf and identity.pdf. It verifies all manifest hashes first, reuses the existing geometry-aware authority parser and layout-aware organization parser, and writes candidates without activating them:

```sh
python tools/ingest_public_references.py --source-directory private/institutional_sources --output build/reference-candidates.json
```

No hidden download or external model processing occurs. Reconcile generated changes against `shared/institutional-candidates.json` before publication. `change_impact` reports added/modified/removed IDs but never activates a version. Updating source hashes or asserting approval/currency requires explicit supporting records, not a filename or model opinion.

Observed extraction: 141 authority entries, 81 units, 15 sectors. Page-linked roles, qualifiers, tasks and source grouping are candidates for human reconciliation, not reviewed institutional facts. Financial thresholds are marked REQUIRES_HUMAN_RECONCILIATION rather than invented or silently treated as unspecified. Role distinctions such as recommendation, review, preparation, approval and execution are retained. Recorded grouping is not relabelled as an approved reporting relationship.

The API provides an authenticated reference explorer, candidate source/role graph and proposed responsibility map, separately labelled from synthetic review-case data. Relation edges preserve page and approval status. Possible source conflicts are not automatically resolved toward the most permissive authority. No currently binding authority claim is made by these views.

`attach_verified_occurrence` is a bounded adapter to the existing EvidenceRegistry: it requires exact source hash, source identity, valid page and matching page text before attaching a candidate as UNVERIFIED/NOT_ESTABLISHED. Existing purpose-limited role context builders then carry that evidence status. It does not replace reference retrieval, grant applicability, or transmit institutional data to a provider. Unauthorized external processing remains blocked by existing runtime policy. The synthetic review seed intentionally uses the existing fictional reference index rather than the public real-source candidates, preventing an accidental authority upgrade.
