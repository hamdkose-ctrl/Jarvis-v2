# BRAIN-07K — Canonical dependent preflight in the existing executor

**Durum:** Stacked draft on BRAIN-07J / PR #572. No dependent worker or new scheduling authority is enabled.

## Integration boundary

BRAIN-07J provides an output SHA-256 commitment in newly accepted **planned read-only** WorkerResult evidence plus a pure `bind_predecessor_outputs` verifier. BRAIN-07K calls that verifier from the two existing production execution boundaries:

1. `goal_executor._record` calls `dependency_evidence.preflight_durable_step` before changing step state to running, persisting a checkpoint, incrementing attempts, or setting `started`. Only a versioned goal journal enters this early preflight.
2. `specialist_orchestrator._execute_step` repeats the preflight before DecisionAuthority, worker, model, or provider calls. Its `deps` mapping is replaced by defensively copied, verified predecessor outputs only if a valid canonical plan applies.

The trusted inputs are the **single canonical GoalState snapshot**, its current `NodeCandidate` and **the on-disk existing ExecutionRecord**. A mutable `job['outputs']` dict, even if marked `done`, has no authority. The preflight requires that the actual on-disk `execution_record.v1` exists, the caller's owner/job/step/tool/input/dependency order equals the canonical node, and each dependency's in-memory and on-disk output agrees. BRAIN-07J then checks accepted WorkerResult audit, current-plan SHA-256 output commitment and fresh domain verification. Missing output or stale/tampered receipts deny rather than reconstructing success.

A canonical dependent cannot silently downgrade to an unversioned legacy identity, nor can a foreign owner/task pass the specialist gate. Legacy **unplanned** dependency execution remains on its preexisting path.

## Fail-closed guarantees exercised by synthetic tests

- Two accepted root WorkerResults with unchanged persisted results pass preflight, but **dependent runtime prepare still denies execution**; no extra worker starts
- Only one accepted parent, wrong dependency order, tool, canonical input or step identity => deny before worker/DecisionAuthority
- Missing on-disk journal, forged in-memory output, forged persisted output, or synchronized disk+memory forgery against canonical SHA-256 => deny
- User intent correction, stale domain receipt or non-durable/foreign execution identity => deny
- `goal_executor._record` fails before running state, checkpoint, or attempt start when a predecessor is invalid
- Unplanned older specialist execution stays operational

## Explicit exclusions and remaining work

- **Not production DAG dispatch**. `runtime_worker_result.prepare`, `worker_result_commit` and the ResourceLease gate still block dependent nodes. A successful preflight returns a copy of admissible inputs, **not permission, a lease ticket, worker authorization or completion**.
- No new Scheduler, state store, model keyword router, autonomous capability installation, effect permission or retries.
- This verification is a read of two existing persisted records, **not a long-held cross-record atomic transaction**. The next cutover must add an exact current-plan/record proof at dispatch and result-CAS time to protect against races between preflight and execution.
- Dependency-free roots follow the existing execution path. Effects/publishing/desktop/browser write operations remain blocked on planned dependent branches.
- Tests use real temp GoalState Reducer/CAS and ExecutionRecord files, with fake provider output and mocked domain verifier. They do not establish live external receipt authenticity.

## Merge dependency and acceptance

Stacked atop **PR #572** because it imports `modules/dependency_evidence.py`; #572 must pass and land before #573 can target `main`. Separately open PR #571 is unrelated but may change `main` while CI runs. Require exact-head Windows CI plus matching real-PC watcher validation. The user reports the results; do not repeatedly poll or claim completed acceptance before evidence.
