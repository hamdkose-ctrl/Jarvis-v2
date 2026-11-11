# BRAIN-07 — canonical DAG in the existing Scheduler (draft)

## Starting point / reviewed boundaries

The engine currently launches **one** `task_queue.start` Scheduler. That
Scheduler owns a bounded pool of owner ticks, while live, owner-bound goal
execution and permission decisions are in `goal_executor` and
`specialist_orchestrator`. `GoalState` and `ExecutionRecord` remain the
only lifecycle/output authorities. A generic queue worker cannot simply
pretend to be the active user's runtime profile.

## First implementation in this draft PR

`canonical_scheduler_lane.ready_offers(owner, job_id)` is a bounded,
read-only adapter for canonical `task.research` and `task.account` nodes
already published in an existing `ExecutionRecord`. It requires:

1. matching owner/job identity, active canonical GoalState, a real running
   ExecutionRecord file, and accepted plan readiness;
2. an exactly matching, uniquely published queued first-attempt step;
3. current canonical and journal snapshots, whose identities are pinned in
   `ReadyOffer` and re-checked by `revalidate_offer`;
4. for a research child, independently checked, *persisted* predecessor
   output digests and domain proof using the existing `dependency_evidence`.

Invalid, effectful, already running, failed/previously attempted,
user-replanned or stale nodes never authorize dispatch.

This module **does not actually run work yet**. An offer is not a
ResourceLease, a permission token or evidence of success. The draft PR
remains in progress until production integration follows.

## Complete within this same PR before ready/merge

- Wire candidate scanning into the **existing** `task_queue.start` loop,
  with an explicit owner-bound runtime resolver rather than borrowing the
  foreground profile or creating a second Scheduler.
- Before worker execution, check exact ready offer, DecisionAuthority, user
  permission and current capability adapter. Acquire existing
  command/resource claims; no automatic retry of effects.
- Dispatch independent safe roots in bounded parallel lanes and dependent
  research only after canonical WorkerResult CAS, accepted output projection
  (#586), and persisted predecessor-domain evidence.
- Ensure that a WorkerResult committed during actual execution is projected
  to `ExecutionRecord` **without clobbering a concurrent writer or stale
  in-memory job**. Legacy `goal_executor._save` is also a writer and must not
  overwrite projected results. No new journal/Global GoalState.
- Add end-to-end tests for actual worker/owner contexts, two roots plus child,
  stale revisions, concurrent record writes, cancellation/lease loss and
  voice lane responsiveness. Run Windows CI and real PC acceptance at the
  last SHA.

## Non-goals / invariants

No autonomous capability discovery/install, Ollama requirement, second
Scheduler, forged approval, auto-replayed external effect, or immediate
retirement of the legacy Brain path. Keep Brain and Core independent.
