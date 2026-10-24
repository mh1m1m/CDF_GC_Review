# External prerequisites and honest status

| Capability | Status before external setup | Exact blocker / required evidence |
|---|---|---|
| Actual ChatGPT remote MCP connection | BLOCKED_EXTERNAL | No approved public HTTPS/OAuth deployment or connector registration capability in this environment; loopback protocol tests do not count |
| Actual Claude web/Desktop/Code MCP connection | BLOCKED_EXTERNAL | No configured Claude account/client integration; CLI binary absent; independently tested MCP SDK does not count as Claude |
| Claude Code inference | BLOCKED_EXTERNAL | Official `claude` executable and authorized login unavailable |
| OpenAI API inference | BLOCKED_EXTERNAL | No explicitly configured API credential/model/policy; do not reuse Codex ChatGPT login tokens |
| Anthropic API inference | BLOCKED_EXTERNAL | No explicitly configured approved API credential/policy |
| Institutional HTTP production | PENDING_AUTHORIZATION | Existing identity, source approval, processing permissions, release authorization and operational prerequisites remain unmet |

The official Codex executable is installed and its normal login status can be checked without reading login files. A single bounded synthetic stage probe is attempted only after full local deterministic acceptance. Its actual outcome and sanitized canonical receipt must be included in the evidence handoff; installation/login alone does not establish successful inference. A failure remains an external limitation and never triggers mock fallback. Native CLI completion evidence remains distinct from provider API provenance required by the release gate.

No network-policy bypass, consumer-token extraction, private endpoint exposure or fabricated remote-client receipt is authorized by this milestone. Local synthetic acceptance can pass while external connectors, API inference and institutional activation remain blocked.

Controlled Codex result (2026-10-24): official CLI 0.163.0 had a normal ChatGPT login, but the single 60-second fictional drafting probe ended `JOB_TIMEOUT_OUTCOME_UNKNOWN`, with one persisted started attempt and no native completion receipt. CODEX_CLI_EXECUTOR=BLOCKED_EXTERNAL; verified inference remains unproven. No retry was attempted because the remote outcome is ambiguous. This observation does not identify a proven network/authentication root cause and does not imply zero remote processing occurred.
