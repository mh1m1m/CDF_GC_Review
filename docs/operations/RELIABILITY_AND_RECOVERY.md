# Reliability and recovery

The existing single-host SQLite pilot is retained. Additive CP tables and `cp_migrations` version 1 preserve original records. Root immediate transactions prevent WAL read-to-write snapshot races; nested savepoints preserve all-or-nothing publication. Source/history/decision versions are not overwritten by chat state. A production migration rollout/rollback policy requires separate operational acceptance.

Existing jobs retain leases, deadlines, process-tree cancellation and immutable attempts. Workflow status does not rely on browser/conversation memory. Resume can launch an accepted queued job by the same ID; stale running work becomes failed without provider replay. Explicit retry is bounded to declared deterministic/mock work. Ambiguous native/provider outcomes remain blocked pending reconciliation. Original findings and previous execution snapshots persist across retry.

Backup uses SQLite's online backup API through a separate read connection while the application serializes writes. Only an administrator with access to every included case may create it. Files stay in the database's protected ignored `managed-backups` directory; responses expose IDs/hashes, not downloadable databases or arbitrary paths. Verification checks digest, SQLite integrity/foreign keys and the app audit chain, copies into a new staging database, revokes restored sessions and never overwrites the active database or replays jobs. Test evidence is not institutional disaster-recovery certification.

Artifacts remain hash-verified and scoped; failures preserve valid prior snapshots and return explicit error states. No distributed scheduler, cross-host supervisor, production SLA, live remote client, external audit anchor or production restore cutover is claimed.
