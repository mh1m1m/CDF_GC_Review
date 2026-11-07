# Public synthetic remote MCP resource server

This deployment is **not deployed or externally verified** in the authoring environment. It cannot enable private institutional mode. `remote.example.json` deliberately refuses startup until an operator supplies a real configuration and explicitly enables public synthetic remote access.

Use an approved public DNS hostname, trusted TLS chain/key, external OAuth authorization server, public JWKS and actual registered client IDs. The OAuth server must support authorization-code + PKCE S256 and the client's supported registration method. Login/consent/redirect validation/state/PKCE/token issuance belong to that server; this repository does not implement or advertise a fabricated authorization server.

Supported access-token profile: RFC 9068 `typ=at+jwt`, RS256, exact resource audience, exact issuer, `sub`, `client_id`, `jti`, `iat`, `exp` and `scope=cdf:tools`. ID tokens, opaque tokens, HS256, token-selected key URLs, unknown keys and multiple audiences are rejected. An existing issuer with a different token profile needs a separately reviewed adapter. The fixed public JWKS is provisioned through the operator's trusted issuer channel; key rotation requires replacing the pinned file and restarting. No arbitrary token-supplied network lookup occurs.

Prepare these operator-owned directories outside the public repository:

- A tracked source archive (`git archive <reviewed-commit> | tar -x -C <empty-source-directory>`). Do not mount a whole working directory containing ignored/private files.
- Configuration containing `remote.json` and public `jwks.json`, read only.
- Trusted TLS `fullchain.pem` and protected `privkey.pem`, read only and readable by UID 10001. Certificate acquisition/renewal is an external operational prerequisite.
- Protected public synthetic state owned by UID/GID 10001, mode 0700. Case grants must be provisioned through a trusted operator workflow; JWT claims never grant cases or roles.

Set the five path/bind variables required by `compose.yaml`, validate with `docker compose -f deploy/remote-mcp/compose.yaml config -q`, build the pinned existing stable runtime, then start only in the approved deployment environment. Host port 443 maps to the unprivileged TLS listener on 8443. The container is read only, runs as UID 10001, drops all capabilities and uses an internal network. No provider credentials, development bearer or private data are mounted; provider and consumer CLI execution are disabled by default. The image is built locally, never published automatically.

Remote entry point:

```sh
python -m cdf_gco_crms.interfaces.remote_mcp \
  --config /run/cdf-config/remote.json --db /var/lib/cdf/public-demo.sqlite \
  --tls-certfile /run/cdf-tls/fullchain.pem --tls-keyfile /run/cdf-tls/privkey.pem
```

The server validates Host, HTTPS, Origin, streamed body bounds, IP rate, JWT signature/profile/issuer/audience/scope/expiry, server-provisioned subject/client mapping and existing session/case permissions. It ignores forwarded headers, accepts no development bearer, advertises RFC 9728 metadata and returns an authentication challenge containing its exact metadata URL. Tokens are stored only as hashes in existing expiring/revocable sessions. Roles and case grants never come from token claims. Public mapped identities are synthetic users, not verified institutional reviewers.

Verify the deployed endpoint with `python -m cdf_gco_crms.acceptance.connectivity --config <operator-config> --probe-remote --output <protected-report.json>`. Preserve the inherited proxy and CA trust; the helper requires explicit permitted destinations in the environment network policy. Provision a resource-scoped `CDF_REMOTE_MCP_ACCESS_TOKEN` through the environment secret store for the independent SDK probe. Do not paste tokens into command arguments, logs or the repository.

The probe checks real HTTPS metadata and OAuth code/PKCE capabilities, then initializes an independent MCP SDK client when a token is available. Even a successful external SDK result does **not** prove ChatGPT or Claude registration. Each actual client still requires its account's connector configuration/consent and a correlated authenticated tool invocation. A client name in `clientInfo`, a JWT client ID, configuration files or local tests alone cannot prove the calling product.

After a real executor is authorized and working, run one controlled fictional task through the existing application executor, audit its persisted receipts, then reconcile the resulting case across CLI/MCP/React and native Word/Excel/PDF. No mock fallback may fill a missing live receipt. The central release gate and human authorization remain mandatory.
