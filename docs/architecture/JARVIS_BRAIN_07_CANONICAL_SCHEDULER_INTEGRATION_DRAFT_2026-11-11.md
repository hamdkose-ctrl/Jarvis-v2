# BRAIN-07 — canonical DAG in the existing Scheduler (integration draft)

## Existing authority and scheduler boundaries

The production engine starts **one** `task_queue.start` Scheduler. The same
loop now admits bounded, registered-owner canonical workers without creating
another poller, GoalState store, or separate trust domain. Existing
`goal_executor`, `specialist_orchestrator`, `runtime_execution_gate`,
`resource_leases` and `worker_result_commit` remain authoritative.

## Published readiness (pure data; never execution authority)

`canonical_scheduler_lane.ready_offers` selects only previously published
`task.research` and `task.account` steps from the current canonical
GoalPlan and durable ExecutionRecord. Each offer pins owner, job, node,
plan-version, journal snapshot and dependency evidence. Revalidation rejects
stale/foreign revisions, already-started or failed attempts, and effectful
or unregistered capabilities. A dependent research child requires accepted
canonical evidence and exact persisted predecessor result digests, with
independent domain verification.

## Production dispatch connected within the same PR

- `task_queue.start` also scans registered owner goals **on its existing
  loop**, whether or not the owner has an SQLite queue record. It runs
  at most three simultaneous canonical worker threads globally and two
  per owner; other scheduled queue workers and source-watch/outbox polls
  retain their existing code paths.
- The `engine_loop` resolver checks the registered owner identity. A
  background worker uses a pinned, minimal owner-only runtime facade rather
  than borrowing mutable foreground `runtime.profile` or acquiring the
  long-lived user-switch execution lock. Voice/command event handling is
  therefore not held behind an external worker call.
- `canonical_scheduler_dispatch.execute_offer` reserves one still-queued,
  first-attempt node under the existing per-job journal control lock and
  rechecks the pinned canonical plan. The existing specialist worker performs
  DecisionAuthority, permission, capability, dependency, and native
  ResourceLease/OS command locks. No explicit worker dispatch can grant
  itself an approval, retry an effect, or rebase an old plan.
- A successful worker result is accepted through the existing WorkerResult
  envelope and deterministic Core CAS **before**
  `canonical_output_projection.project_accepted` appends the validated
  clean output to the durable ExecutionRecord. Both use the same short
  per-job control lock. Failed/late workers cannot overwrite an accepted
  output or attach their attempt to a cancelled/replanned goal.
- On a failed first attempt, the journal records a non-success only when
  the current canonical plan still exactly matches and no success was
  previously accepted. A crash or unknown result is not blindly retried.

## Executable acceptance

The same PR carries actual-disk tests for two concurrent independent
research roots followed by a dependent research child, exact verified
predecessor projection, wrong owner, duplicate wake, cancellation while a
worker is live, and a real Scheduler loop which keeps source polling during
long-running workers. External research is mocked solely at the provider
boundary; the Scheduler, specialist, leases, WorkerResult CAS and journal
remain the real production code.

**Do not mark ready or merge** until both Windows CI and the physical Windows
PC watcher have `passed` for the **final identical HEAD SHA**. Success on an
older commit is insufficient. The main BRAIN-07 follow-up issue #584 remains
open for wider adapter coverage, richer recovery, global Goal completion,
and the full independent Windows acceptance matrix.

## Non-goals / invariants

No autonomous skill discovery or installation, Ollama prerequisite, second
Scheduler, fabricated permission, automatic external-effect replay, or
premature retirement of legacy Brain. Brain and deterministic Core stay
independent.
