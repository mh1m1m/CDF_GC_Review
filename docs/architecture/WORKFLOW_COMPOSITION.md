# Durable thin workflow composition

`cp_workflows` stores immutable chosen steps plus mutable execution progress/version; `cp_keys` binds actor/operation/key to request hash and accepted workflow. Existing `app_jobs` performs all actual execution. Root immediate SQLite transactions serialize resume/version checks, child job acceptance and audit publication; nested savepoints preserve rollback. Workers launch after commit.

States: PLANNED → WAITING_FOR_JOB → WAITING_FOR_HUMAN → COMPLETED_DRAFT, with FAILED and CANCELLED alternatives. `status` reads backend progress; `resume` is an authorized action with an expected version. A queued worker can be relaunched by its existing job ID. Stale running work is failed without replay. Explicit retry is allowed once for declared deterministic/mock execution, never as a substitution for an unavailable provider. Stored job attempts and immutable `executive_runs` preserve successful stages and failed snapshots across retry.

Agreement completion means draft artifacts and an acknowledged local review checkpoint. It does not mean every material observation is resolved or that the case may issue. The checkpoint needs a persisted review record and explicit rationale/confirmation. Case release authorization remains separately fail-closed.

Templates document source/evidence requirements, stages, failure conditions and human checkpoints. Policy/framework/committee templates are intentionally non-executable until standards/source integration are validated. Read-only authority/responsibility/control/risk/calibration compositions do not invent institutional review methodology.
