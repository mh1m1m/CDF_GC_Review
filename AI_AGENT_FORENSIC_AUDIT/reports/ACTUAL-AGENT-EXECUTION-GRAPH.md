# ACTUAL AGENT EXECUTION GRAPH — CDF–GCO–CRMS v7.12

Execution evidence from `runtime_callgraph.py` (profile hook) and the live harness records.

## Product (one process)

```
main.py review/challenge/adjudicate
  └─ parse_workbook → require_safe (fail-closed ingestion)
  └─ RecipientPersona.from_index(ReferenceIndex)
  └─ run_challenge(state, registry, persona)
       └─ for each observation:
            black_team(observation, registry, persona)      [rules; no model]
            _argue(objection, …)
               ├─ red_advocate(objection, observation, registry) [rules; no model]
               ├─ _followups(…) while productive (≤ 6 events)
               └─ adjudicate(objection, advocacy, registry)      [rule table; no model]
            Objection.decide(…) [not for issued observations]
  └─ ChallengeRecord.to_json → build/adversarial/*.json   (no consumer in round1/append/build-excel/build-word)

main.py round1 / append / build-excel / build-word / finalize-titles
  └─ build_round1 | apply_round | parse_workbook → build_workbook | comment_document   (never touches assurance.challenge)
```

## Audit harness (outside the product)

```
auditor (this session)
  ├─ live_prompts.py → one prompt file per (case, role), payload hashed, no sealed label
  ├─ subagent[BLACK_TEAM, case]  (fresh context)  → JSON → record_live.py → live_<case>_BLACK_TEAM.json
  ├─ subagent[RED_ADVOCATE, case] (fresh context; input = payload + Black Team JSON)
  └─ subagent[ADJUDICATOR, case]  (fresh context; input = payload + both JSONs)
```
