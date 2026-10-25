# Shared-state proof

The generated `interface-matrix.json` contains actual CLI output, official MCP SDK results and independently read React DOM fields for one case. It compares case ID, all observation IDs, run ID, ordered agent stage/status/source, evidence reference IDs, calibration event version, recorded release gate, each metric numerator/denominator and artifact IDs. No illustrative matrix values are committed as execution evidence.

The MCP client replays the original CLI review with the same actor/key and verifies the original job ID, attempt count and result. It also writes a draft calibration decision through MCP, then refreshes all interfaces before comparison. Submitted metric coverage and draft event versions remain distinct. Reports preserve the fingerprint of the state that produced them and may correctly display as earlier snapshots after later events.

Display translations and number formatting may differ. The comparison uses DOM identifiers and numeric data attributes rather than rounded Arabic display labels. Metric timestamps are excluded because the projection legitimately recalculates presentation metadata on read. A missing metric is NULL, never an invented confidence score.

`react-interface.json` is written from DOM reads, not a copy of the HTTP response. Actual screenshots and browser-downloaded bytes are separate evidence. Failed/missing interface checks fail the harness rather than filling the matrix with expected fixture values.

The MCP phase also enqueues a fresh Excel export under a distinct idempotency key, observes QUEUED/RUNNING/COMPLETED through protocol calls, checks one backend attempt, and retrieves its persisted bytes through CLI and MCP. `mcp-job-lifecycle.json` records that actual asynchronous lifecycle; all interfaces then reconcile the updated artifact list. This is separate from replay of the earlier CLI export and does not invoke a model.
