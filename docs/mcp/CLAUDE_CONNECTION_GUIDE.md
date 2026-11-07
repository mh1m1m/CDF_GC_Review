# Claude MCP and inference connections

Status in this workspace: **BLOCKED_EXTERNAL** for actual Claude web, Desktop and Code client connection tests. The `claude` executable and Claude account/client setup are absent. Official SDK protocol acceptance is independent evidence, not a Claude client receipt.

For an installed, authorized local Claude client supporting stdio MCP, configure its documented MCP-server settings to launch the repository's Python environment with `-m cdf_gco_crms.interfaces.mcp_server --transport stdio`, repository working directory and a scoped synthetic environment. Supply credentials through the client's approved secret mechanism, never committed JSON. Consult the current client-specific configuration format; do not assume Claude web, Desktop and Code share settings or authentication.

The local Streamable HTTP option is `http://127.0.0.1:8766/mcp` with the explicitly provisioned development bearer session. Remote Claude web registration requires a separately approved HTTPS/authentication deployment. The development server stays loopback-only; private HTTP remains disabled. Do not expose it through a tunnel for demonstration.

Record the actual client name/version, discovery response, case/source/run IDs, an authorized tool mutation, backend event and artifact retrieval. Use the same CLI-created SYN-COOPERATION-001 case and compare identifiers with React. The Claude Code CLI inference adapter is a separate feature from a Claude MCP client; installing one does not prove the other. No successful Claude connection or inference is claimed until actual evidence exists.
