# Inference and dependency decisions

| Executor | Implementation | Canonical source | Required configuration | Evidence limit |
|---|---|---|---|---|
| deterministic | Existing orchestrator and rule/MAT paths | DETERMINISTIC_RULES | None | Workflow integration only |
| mock | Explicit existing MockAdapter; deterministic advisory MAT | MOCK_SCRIPT / DETERMINISTIC_RULES | Explicit executor selection | No model inference |
| codex-cli | Official `codex exec`, JSON events + role schema, temporary read-only workspace; shell and multi-agent tools disabled | SUPERVISED_CLI | Installed authenticated CLI; `CDF_ENABLE_SUPERVISED_CLI=1`; synthetic payload | CLI completion/session/usage receipt, not an API request ID or independently attested model |
| claude-cli | Official noninteractive `claude -p`, structured schema, tools disabled | SUPERVISED_CLI | Installed authenticated CLI and same explicit synthetic policy | Runtime compatibility remains unverified when binary/account absent |
| openai | Official SDK Responses API, strict structured output, `store=False` | PROVIDER_API; injected clients UNTRUSTED | `CDF_ENABLE_PROVIDER_API=1`, `OPENAI_API_KEY`, explicit `CDF_OPENAI_MODEL` | Completed response ID + provider request ID + returned model/usage required |
| anthropic | Existing official SDK adapter | PROVIDER_API; injected clients UNTRUSTED | Explicit API policy and approved API key/auth token | Existing receipt and output validation; no consumer login extraction |

No requested CLI/API executor falls back to mock. Application jobs disable automatic provider retries and record ambiguous interruption as unknown. The existing gate continues to require its own trusted API provenance; supervised CLI calls never inflate API live counters.

## Dependency assessment

| Package | Existing → proposed | Purpose/license | Compatibility/security | Environment/performance | Decision |
|---|---|---|---|---|---|
| MCP Python SDK | environment 1.29.0 → 1.30.0 | Standards HTTP/stdio; MIT | Fixed CVE-2026-59951. Server also uses stateless mode, scoped bearer, loopback and bounded requests. 2.x deferred to avoid unnecessary migration. | Python 3.10+; async HTTP, no second orchestrator | INSTALL |
| OpenAI | absent → 3.37.0 | Official Responses SDK; Apache-2.0 | Injected clients cannot count as trusted inference; errors sanitized; no consumer token reuse | Python SDK; zero requests unless selected and authorized | INSTALL |
| psutil | transitive 7.2.2 → direct 7.2.2 | Process-tree termination; BSD-3-Clause | Fixed executable names, no shell, tested actual child termination | Linux runtime wheel; polling every 150 ms per active supervisor | INSTALL |
| Pydantic/FastAPI/SQLite/React | existing pinned versions retained | Shared contracts/services/UI | Existing authorization, provenance and release contracts reused | No database migration infrastructure or network queue | RETAIN |
| LangGraph/Redis/PostgreSQL/new agent framework | absent → absent | No demonstrated requirement for this single-host pilot | Would duplicate existing orchestration or add operational scope | Distributed production scheduling deferred explicitly | DEFER |
| Node | existing Node 22 target → pinned official Node 22 image digest | Existing frontend and Playwright; MIT | Uses the existing npm lockfile | Acceptance image only | INSTALL IN TEST IMAGE |
| Chromium | host installation → Debian stable package in acceptance image | Actual browser acceptance; mixed open-source licenses | Runtime package inventory recorded; no network in acceptance container | Browser layer is large; not part of production Python runtime | INSTALL IN TEST IMAGE |

`requirements-execution.txt` pins direct additions and uses `requirements-execution-lock.txt` for the entire resolved Python 3.12 closure (66 packages). Existing manifests remain usable for earlier milestones. Stable LibreOffice keeps the pinned Python image digest and Debian LibreOffice 25.2.3 security package. OS transitive packages are recorded by dpkg; they are not claimed to be byte-for-byte reproducible across repository updates. New Node digest is recorded in `Dockerfile.execution-acceptance`; npm dependencies retain `package-lock.json`.

Security acceptance uses the resolved Python advisory scan, frontend npm audit, Bandit of interface/provider boundaries, repository guard and synthetic output leakage scan. The controlled official CLI probe and actual external client connections are reported separately from these installation/compatibility decisions.
