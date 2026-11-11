# BRAIN-07 — Canonical research root command ownership

## Scope
The existing `specialist_orchestrator` dispatch path now reserves an
exact command through the existing `goal_executor._RESOURCE_LEASES` table
and owner/job OS claim for both canonical read-only research roots and
dependent research children. Permission/DecisionAuthority, actual adapter,
domain verification, WorkerResult envelope, Core CAS and journal remain
unchanged and execute under that command claim.

- Duplicate wakes of an identical owner/job/node/plan/attempt conflict.
- Distinct independent roots have different command keys and can be
  in-flight concurrently when dispatched by an authorized caller.
- Root commit tolerates canonical version changes *only* from accepted
  WorkerResult audit appends, and revalidates the current root readiness.
  Core CAS remains final arbiter; revisions and foreign edits fail closed.
- Dependent nodes retain their existing first-attempt, persistently
  verified predecessor-output domain readback.

## Explicit boundaries
No second scheduler, worker/result store, runtime capability installer,
new permission grant or implicit retry is added. The ordinary canonical
Scheduler ready-node dispatch and global Goal completion wiring are **not**
delivered here. Root-result acceptance remains compatible with the older
Core CAS contract and is not yet globally made dependent on a root-specific
lease outside the specialist path; hardening that broad contract requires
migrating synthetic Core test callers and handling all result replays.
Model/provider calls are not forcibly killed on cancellation.

## Evidence
Synthetic-provider regression tests cover separate in-process LeaseTables
plus the real OS claim, overlapping independent roots with real CAS,
user-intent edit during an in-flight root, live specialist dispatch and
duplicate specialist invocation without calling the provider. The exact
new head must pass Windows CI plus real PC watcher before merge.
