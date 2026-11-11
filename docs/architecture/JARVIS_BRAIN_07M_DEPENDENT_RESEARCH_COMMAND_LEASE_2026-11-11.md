# BRAIN-07M — Dependent research command lease (in-process)

**Status:** Draft. Extends the merged 07L read-only child dispatch, without
opening general DAG execution or a second Scheduler.

## Existing owner

The only lease authority is `goal_executor._RESOURCE_LEASES`, the same
in-process `LeaseTable` used by earlier 07A/07F slices.
`resource_leases.resource_key('command', sha256)` uses a dedicated namespace
and canonical owner/job/step/plan/command identity. It is intentionally
per-command rather than a fake provider-wide lock; two independent research
commands may run concurrently but one live command cannot be duplicated.

`scheduler_resource_gate.dependent_research_worker` obtains a ticket only
after the existing canonical evidence/readback path and first-attempt
readiness check pass. It keeps the lease until the worker and accepted
WorkerResult CAS finish, heartbeats a bounded ticket and stops/joins the pulse
before releasing the current generation.

At final `commit_checked`, the Core reads the current GoalState and
ExecutionRecord again and refuses stale version, changed plan, invalid
predecessors and lost ticket. Its exact result binding is stored in a
private `ContextVar` for the synchronous call to
`runtime_worker_result.accept_and_commit`. The actual
`worker_result_commit._commit_once`, under the existing owner/job lock,
checks `require_dependent_research_result_lease` before writing new
dependent evidence. Existing exact accepted-command replay exits before
the new lease requirement, but cannot authorize a fresh worker.

Both the ordinary research adapter and the model-free news adapter enter
the same scope before any network/provider work. Canonical root research,
legacy specialist calls and read-only account lease rules are unchanged.

## Explicitly not proven

This is an in-process token, **not** a process-persistent or distributed
lease. A restart/second process can still repeat a read-only network call;
the existing canonical CAS fence may prevent its result acceptance, but it
cannot undo external cost or side effects. No effectful dependent capability,
automatic retry, authorization change, general Scheduler, new store, native
desktop worker or durable cross-process guarantee is introduced.

## RED/GREEN and acceptance

Existing 07K/07L real-temp-file GoalState/ExecutionRecord tests are extended
to assert single successful dependent research, exact replay, lost/expired
ticket, duplicate live command, direct unleased CAS denial, tampered parent
after launch and user intent revision during worker execution. Real research
providers are mocked. This source does not attest CI or real PC acceptance.
Merge requires exact-head Windows CI success and matching real-PC watcher
`Validation: passed` and `Genel durum: passed`.
