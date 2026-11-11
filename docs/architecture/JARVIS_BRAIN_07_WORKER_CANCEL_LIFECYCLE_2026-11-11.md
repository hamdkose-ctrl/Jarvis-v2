# BRAIN-07 — Cross-process worker cancellation observation

Existing per-process cancellation memory is insufficient when two Jarvis
instances share the same durable GoalState. The active worker checks the
canonical on-disk terminal state before starting an adapter, during guarded
model wait, and after the worker returns.

Canonical owner/job mismatch, symlink, corrupt data and missing previously
required sidecar do not grant worker execution. Legacy jobs which never had
a canonical sidecar remain compatible.

This does not kill or roll back an in-flight external provider call; it
does not automatically replay a crashed request or replace WorkerResult CAS.
Unrelated accepted evidence can advance the GoalState version without being
misinterpreted as cancellation. No second Scheduler is introduced.

Acceptance: exact-head Windows CI and matching real-PC watcher PASS.

### Foreign-terminal cancellation propagation

When the worker detects a durable terminal state written by another process,
the outer goal loop now preserves the original cancellation outcome without
attempting to overwrite that terminal journal snapshot. The normal in-process
cancel path still writes its own cancellation if canonical state remains
active. No remote operation is cancelled or retried by this adjustment.

### Cancelled is terminal even for legacy projections

The narrowly allowed legacy resume concerns **done** snapshots only.
A durable **cancelled** snapshot is never reopened as a stale worker,
even when its last audit reason was a compatibility projection and the
ExecutionRecord appears fresh.
