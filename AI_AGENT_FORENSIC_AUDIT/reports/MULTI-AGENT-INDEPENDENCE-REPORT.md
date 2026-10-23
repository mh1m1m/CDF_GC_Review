# MULTI-AGENT INDEPENDENCE REPORT — CDF–GCO–CRMS v7.12

Scope: the product's challenge engine (`cdf_gco_crms/assurance/challenge.py`) as executed by `main.py review`. Live isolated runs of the audit harness are reported separately in `BLIND-ADVERSARIAL-EVALUATION.json` (MODE D) and never stand for the product.

## Execution probe (synthetic case DA-01)

- Same process for the three roles: **True**; same thread: **True**; shared EvidenceRegistry object: **True**.
- Model invocations observed: **0**. Separate execution identity: **False**.
- Engine's own declaration: independence = `SINGLE_PROCESS_RULE_BASED`, role_isolation = `NOT_VERIFIED`.
- Hidden-label probe: disposition without label `UPHELD_WITH_REVISION`, with a planted `expected` attribute `UPHELD_WITH_REVISION` (changed: False).

## Information boundaries (05.2–05.5)

- Black Team receives: the observation, its comment, the document paragraphs through the registry, the recipient persona built from the organisational-structure index. It does not receive the advocate's draft or an expected decision (none exist). PASS as a boundary, but there is no 'draft' to protect because the roles are synchronous rules.
- Red Advocate receives the Objection object produced by black_team (proposition, kind, detail dict, evidence refs) — exactly the objection, nothing hidden.
- Adjudicator receives the Objection and the Advocacy objects and the registry; `adjudicate()` reads only `kind`, `stance`, `evidence_refs`, `detail['reserved']` and `issued`; its docstring states that attributes named `expected` are not read and the probe confirms it.
- Independent Final Reviewer (Art. 20): **no component exists**; no context is created, so independence cannot be assessed.

## Independence levels (05.6)

| Property | Result | Evidence |
|---|---|---|
| ROLE_SEPARATION | **PARTIAL** | three distinct functions with distinct rule tables and outputs; no separate execution identity |
| PROMPT_SEPARATION | **NOT_APPLICABLE** | no prompts exist in the product; the roles are rule tables, not prompted models |
| CONTEXT_ISOLATION | **FAIL** | same process, same thread, same in-memory registry, persona and objection objects |
| EXECUTION_ISOLATION | **FAIL** | one call chain run_challenge → black_team → _argue → red_advocate → adjudicate |
| TOOL_PERMISSION_ISOLATION | **NOT_APPLICABLE** | no tools; the functions cannot open files or sockets |
| MEMORY_ISOLATION | **FAIL** | shared Objection instance carries every prior event into the next role (by design of the state machine) |
| EVALUATION_ISOLATION | **PASS** | the adjudicator ignores a planted 'expected' attribute (probe) and the held-out labels are underscore fields hidden from to_dict() |
| PROVIDER_DIVERSITY | **NOT_APPLICABLE** | no provider at all |

## Conclusion

The product runs **one deterministic process**. The three roles are separated by function and by record, not by execution context, memory or model invocation. The engine states this itself (`SINGLE_PROCESS_RULE_BASED`, `role_isolation = NOT_VERIFIED`) in every record and in protocol 19A.2/23.1. Nothing in the product counterfeits independence: no separate context ids are logged for a single call.
