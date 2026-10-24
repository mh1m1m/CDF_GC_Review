# Dual-mode security verification

Public mode has a fixed fixture provider, separate database mode/namespace, public-only bundle/context packaging, explicit public branding and no private reference route. Private mode defaults to deny-all and has no production HTTP activation. A trusted institutional authorizer is an integration port, not an implemented organizational identity provider.

Meaningful negative/positive tests cover:

- Default denial before reading any private source file.
- Public requests cannot select a private provider, private source IDs, restricted logos or private organizational records, even when institutional-path environment variables exist.
- Public HTTP activation cannot be switched to PRIVATE_INSTITUTIONAL by an environment flag, and refuses before creating/opening a case database.
- Public database paths cannot be in a private namespace; database mode tagging prevents cross-mode reuse, including fictional-looking case IDs in a private database.
- Private case grants, resolved principal, case scope, export permission and brand permission are all enforced.
- Source hash/registry/version integrity, path containment, conflicting versions and future/superseded source states fail closed.
- Verified occurrence evidence reaches the actual existing orchestrator without granting approval; provider processing requires a separate permission.
- No shared provider cache exists; private projection adds no source content to telemetry.
- Public packages contain only allowlisted tracked code, synthetic fixtures, authorized assets and built UI; private originals, credentials and databases are not mounted/copied.
- Backend institutional environment values are not client configuration. Vite rejects private/secret/token/password institutional client-prefixed variables rather than embedding them.

The container acceptance uses a nonroot runtime, no private mount, no network, dropped capabilities and no-new-privileges. This establishes isolation for that packaged execution. Host development under the user's filesystem account is not an operating-system sandbox; production must provision separate principals, mounts, credentials and storage ACLs. Content labelled synthetic by a caller is not automatically a DLP-classified document.

Scoped Bandit, runtime npm/PyPI advisory checks and the tracked-file guard supplement these tests. They are not a penetration test, exhaustive Gitleaks/history audit or institutional security acceptance. Historical explicitly public material is not retroactively hidden by removing it from the current distribution.
