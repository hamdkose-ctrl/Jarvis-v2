# BRAIN-07 — accepted output projection into the existing ExecutionRecord

This package is a narrow canonical DAG output handoff adapter. It creates
**no new durable store, scheduler, permission grant or worker executor**.

The caller must already have received a successful read-only WorkerResult
through the real Core `goal_state_store` CAS. The adapter takes the existing
`goal_job_control.locked` cross-process job lock, reloads the authoritative
canonical GoalState, matches the single accepted current-plan success, checks
the exact node/capability/version/command/input/digest and authentic audit
reason, then verifies the WorkerResult's committed `output_sha256` against
the clean output bytes. A user intent/plan/state mutation or another job's
result is never allowed to authorize this projection.

It then requires the previously created `<id>.execution.json` journal and
one matching published running/queued step. The output is written once with
`release_guard.atomic`. Identical replay is a read-only no-op; a mismatched
already-persisted output or nonexistent step fails closed. The existing
canonical GoalState is **not** changed, and no global Goal completion is
inferred. The legacy `<id>.json` is not recreated.

This bridges root result acceptance to the existing dependent research
preflight: its `dependency_evidence` adapter will still independently
verify persisted predecessor output digest and domain evidence before work.

Scope/limits: The next planned Scheduler cutover must explicitly call this
adapter **after** a successful canonical WorkerResult commit, not before.
A crash after Core acceptance but before journal projection leaves the
dependent blocked rather than re-executing an uncertain worker. Recovery
of an orphaned accepted-but-not-projected output remains BRAIN-08 work.
No external provider or effect is invoked by this adapter.

Acceptance requires exact HEAD Windows CI plus same-SHA real Windows PC
watcher PASS. An earlier SHA's acceptance cannot authorize merging.
