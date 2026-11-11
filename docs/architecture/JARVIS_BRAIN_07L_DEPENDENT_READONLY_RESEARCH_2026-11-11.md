# BRAIN-07L — Canonical read-only dependent research

**Status:** Draft. This is one bounded implementation slice, not full DAG closeout.

## One existing authority path

The same canonical GoalState, ExecutionRecord, specialist dispatcher and
WorkerResult CAS remain authoritative. We do not introduce a second scheduler,
database, permission gate, capability installer or worker pool. Only a planned
`task.research` node with **non-empty canonical depends_on**, accepted parent
WorkerResults, matching SHA-256 output commitments and valid domain readback may
enter the normal read-only worker path. Its first attempt must be 1.

At `runtime_worker_result.prepare`, Core verifies current plan/intent readiness
and all direct dependencies against the persisted ExecutionRecord. The existing
`specialist_orchestrator` already checked in-memory vs on-disk inputs before
DecisionAuthority; it passes only defensively copied verified dependencies to
the worker. At `worker_result_commit._commit_once`, under the existing
owner/job lock, Core re-reads canonical readiness and persisted predecessor
content, re-checks the original accepted hashes and fresh domain proofs before
appending the dependent result via Reducer/CAS. Unlike independent roots, a
dependent result cannot rebase across an intervening canonical version change.

## Out of scope

This does not grant account leases, file/desktop/effect authority, implicit
retry, canonical plan authoring, multi-process coordination, worker cancellation
or general parallel DAG dispatch. A non-research child remains denied; a prior
failed dependent attempt cannot automatically restart. Model-supplied dependencies
remain untrusted. No new WorkerResult schema is invented.

## Acceptance

The existing temporary GoalState + ExecutionRecord tests cover accepted parent
handoff, successful child WorkerResult CAS, tampered persistence after prepare,
and user intent revision before CAS, in addition to 07K fail-closed cases.
Require exact-HEAD Windows CI and matching real-PC watcher PASS before merge.
