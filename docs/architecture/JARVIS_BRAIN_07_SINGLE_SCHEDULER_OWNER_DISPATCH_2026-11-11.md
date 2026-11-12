# BRAIN-07 — One Scheduler, bounded nonblocking owner dispatch

The existing `task_queue.start` is the **single engine-owned queue polling
loop**. Before this change, one synchronous long `tick(owner)` blocked all
later owners and the loop's own source-watch/outbox progress.

This cut admits at most three owner-specific daemon tick workers from that
same scheduler thread. It never creates a second poller, separate GoalState
authority, duplicate job store or runtime capability installer. Each worker
still invokes the unchanged existing `tick` SQLite lease, queue generation,
job ID, task permission/effect and worker lifecycle checks.

One owner may have at most one live tick in the registry. Admission chooses
least-recently-admitted owner first to prevent starvation when capacity is
full. Threads bind their exact owner LLM context and release it on exit. No
worker runs without scheduled queue work inside the existing `tick`.

The existing source watch and outbox checks stay on the one poll thread.
Queue shutdown stops new admissions; already executing daemon workers finish
only under existing cancellation/lease checks (they are not forcibly killed).
Their in-flight provider effects are not replay-safe by this change.

This improves owner-level queue responsiveness only. General canonical DAG
parallel dispatch, shared resource admission for all workers, cross-process
cancel transport, effectful writer leases and BRAIN-07 closeout remain open.

Acceptance: same-head Windows CI and real-PC watcher PASS.
