# BRAIN-07 — Scheduled worker journal ownership

This patch reuses the existing `task_queue` SQLite lease and
`task_agents` JSON journal. It does not add a second Scheduler.

- Each old task journal has an optimistic fingerprint of actual disk bytes,
  attached only to the in-memory job. The prior snapshot is validated under
  the existing GoalState storage's short OS file lock before `os.replace`.
  Writer A cannot overwrite a newer snapshot from Writer B.
- `task_queue.tick` binds the existing owner/queue/job/`lease_token`
  into the worker execution context, rather than treating any queue row with
  state `running` as authority. A different or expired generation raises
  `requests_state.Cancelled` before each scheduled worker and before saving.
- A short SQLite `BEGIN IMMEDIATE` transaction guards both the claim
  recheck and the journal write, so queue cancel/reclaim cannot interleave
  between them. No database/file lock is held during network/model/provider
  work. A concurrent cancel can still update the durable job journal, but
  any older worker's next snapshot write will fail closed.
- The marker travels with `contextvars.copy_context()` into dependency
  wave worker threads. It cannot be supplied by a model.
- These are storage and result-fence guarantees, not kill-on-cancel,
  external exactly-once, automatic retry, a replacement GoalState, or
  general resource leasing for files and UI effects.

Acceptance: exact-head Windows CI plus matching real-PC watcher PASS.
