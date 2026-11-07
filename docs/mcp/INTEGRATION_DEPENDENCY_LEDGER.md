# Unified execution integration ledger

Verified GitHub stack on 2026-10-24 before publication. All existing PRs remain open drafts; no merges, retargeting or history changes.

| PR | Head branch | Exact upstream commit | Integration decision |
|---|---|---|---|
| [#1](https://github.com/mh1m1m/CDF_GC_Review/pull/1) | development/v7.12-production-engineering | `492915ad9d6d2a457b2b60bd30d051dc6a07b546` | Reuse preserved ancestry |
| [#2](https://github.com/mh1m1m/CDF_GC_Review/pull/2) | fix/v712-fail-closed-cli | `e298083cf48d38886ca081005921827f5e34abf2` | Preserve conflicting draft; already incorporated in PR 3 history |
| [#3](https://github.com/mh1m1m/CDF_GC_Review/pull/3) | feature/v712-live-multi-agent-runtime | `7fe744460f07b0f8ef88aa5406e7b79bfacebc89` | Reuse preserved ancestry |
| [#4](https://github.com/mh1m1m/CDF_GC_Review/pull/4) | feature/v712-mat-professional-dna-agent | `50c339b7cd5ffe2df45f68ab84ac60f8c0e2e1ab` | Reuse preserved ancestry |
| [#5](https://github.com/mh1m1m/CDF_GC_Review/pull/5) | feature/v712-mat-human-calibration | `837168c292161e7744e99258879e8653cfea0545` | Reuse preserved ancestry |
| [#6](https://github.com/mh1m1m/CDF_GC_Review/pull/6) | codex/takeover-audit-and-safeguards | `5a20f318b183c2558404a7179f62b1482b3e5d17` | Reuse preserved ancestry |
| [#7](https://github.com/mh1m1m/CDF_GC_Review/pull/7) | codex/stable-libreoffice | `00c4f5b71998fe4a7306ac90aad278b4881ec182` | Reuse preserved ancestry |
| [#8](https://github.com/mh1m1m/CDF_GC_Review/pull/8) | codex/visual-intelligence | `b30dc5f01b5573d707c1ece77b42c1a3e690a0ae` | Reuse preserved ancestry |
| [#9](https://github.com/mh1m1m/CDF_GC_Review/pull/9) | codex/institutional-dual-mode | `71f593acb557899a0aee71098db8777c4eb6a729` | Direct base; six passing jobs verified |

The new `codex/unified-execution` branch is based on PR 9 commit `71f593acb557899a0aee71098db8777c4eb6a729` and targets `codex/institutional-dual-mode`. PR 9's exact-head independent workflow runs 40077127739 and 40077127798 succeeded; reported counts were checked against actual job logs (276 stable passes / 11 skips; 269 public passes / 18 skips; eight browser passes). These are upstream evidence, not new-head results.

Remote branch inspection found no existing MCP/CLI integration branch to cherry-pick. The new interfaces reuse the existing FastAPI calibration/intelligence services, reference adapter, canonical runner/orchestrator, role schemas, hash-chain tracing and central authorization gate. Existing private default-deny integration remains unchanged. A successful synthetic local workflow does not authorize institutional activation.

New exact-head CI and artifacts are linked from the follow-up draft PR. Any later change to this branch requires its own check evidence.
