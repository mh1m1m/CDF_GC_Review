# Security register

## Corrected in this cycle
- AUD-01: original-state signature allowed substitution of proposed revision. Added signed revision_sha256 and challenge_id; old unbound text-changing signatures rejected.
- AUD-02: ACTIVE release-attestor keys ignored validity windows. Enforce expired, future, malformed and inverted configured windows.
- AUD-03/04: stale rule approval and duplicate profile compilation. Latest nonapproval removes eligibility; identical compilation preserves immutable snapshot.

## Boundaries and residual risks
Public repository: fictional source fixtures only. Local heuristic file scanner is not exhaustive DLP or secret-history verification. Local SQLite hash chains are not externally anchored and do not prove human identity. The token API is synthetic/loopback only, not production authentication. Real provider access and institutional data handling remain unverified/unauthorized. Trust stores and credentials require authorized provisioning. No private profile or source document was imported in this cycle.

No live-provider execution, deployment, merge or institutional issuance is authorized by these fixes. See OPEN_ISSUES.md for remaining work.
