# BRAIN-07 — Cross-process live read-only resource fencing

**Draft scope:** One coherent resource lifecycle hardening packet; existing
Scheduler, canonical GoalState, DecisionAuthority and WorkerResult contracts
remain the only execution sources of truth.

The in-memory `LeaseTable` stays responsible for exact owner/job/step/plan/
command ticket identity, generation heartbeat and stale result refusal.
`resource_leases.process_resource_claim` adds a separate nonblocking OS file
claim derived only from the canonical resource key SHA-256, under the validated
owner's existing goal storage root.

Windows uses one-byte `msvcrt.LK_NBLCK`; Unix uses `flock(LOCK_EX|LOCK_NB)`.
Two live processes with different scheduler memory tables cannot execute the
same owner/account resource or the same planned dependent research command
at once. Independent resource keys can run in parallel. The claim is held
across provider call and final canonical WorkerResult CAS, not merely during
preflight. It is **not** the short `goal_job_control.locked` or canonical
CAS lock: those remain only for small writes. The claim is released in
finally or by the operating system if the process dies.

The scoped resource claim prevents concurrent duplicate dispatch while a
holder is live. It is **not** persisted replay history, a distributed token,
or proof that a previous process did not call an external provider before
crashing. Restart/recovery decisions still belong to higher-level audited
command/receipt and user approval contracts. No effectful dependent, file
write, desktop resource, general DAG scheduler, cancellation or automatic
retry is opened in this cut.

Cross-platform subprocess tests hold one OS claim and require another Python
process to receive a conflict; a different key succeeds, and a released
claim becomes available. Existing real-temp-file account and research worker
fixtures also check collision across independent LeaseTables.

Merge gate: exact HEAD Windows CI success plus `Genel durum: passed` and
`Validation: passed` on that same SHA from the real PC watcher.
