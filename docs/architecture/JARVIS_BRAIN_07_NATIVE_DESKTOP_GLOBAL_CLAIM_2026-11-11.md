# BRAIN-07 — Native desktop global live claim

One Windows interactive desktop is a physical resource: it cannot be split
by profile, owner, job or Python interpreter. This cut strengthens the
existing `desktop_agent._BUSY` path, not a second scheduler or UI worker.

`desktop_agent._desktop_claim` acquires the existing in-process thread
mutex and a nonblocking `resource_leases.process_resource_claim` OS lock
under one shared `desktop_agent.STORE` root, using the canonical
`pc_desktop` resource key. The same thread can carry the claim through
`handle()` to `run()` without reacquiring the OS byte-range lock.

Unlike a run-only claim, it is acquired BEFORE loading/updating the native
journal for cancellation, new-job creation, approval, resume and permission
updates. A second process that holds the OS claim blocks attempts to
replace or modify the current desktop journal and cannot begin UIA
observation or actions. Status/detail reads remain read-only. The lock is
released on every exception/return and automatically on abrupt process
termination.

Subprocess fixture tests hold the actual OS claim in an independent Python
process and prove that a competing new job, another owner's job and direct
read-only UI observation are blocked. A released claim permits the new
journal without touching the native OS or running a real model.

**Out of scope:** PC global protection for unrelated system, shell,
window-management or file-effect paths, durable replay/receipt history,
a second scheduler, background autonomous install, and force-cancelling
an action already sent to the desktop. Existing native UIA identity,
approval and exact screen-readback remain authoritative.

Gate: latest exact-head Windows CI and matching real-PC watcher PASS.

## Reentrancy and stale direct callers

Only the existing handle-to-run same-thread handoff can reenter the live
physical claim; recursive handle and a second nested native worker are
refused. The direct run adapter re-reads its same-owner native journal
**after** acquiring the shared OS claim and checks ID, target, goal,
lifecycle, verified history, pending effect, window IDs and exact approval.
A stale result/approval snapshot cannot overwrite a newer native task.
The ordinary answer field may be updated by the existing resume path
without granting additional native action authority.
