"""BRAIN-07C: one-call read-only lease lifetime for the EXISTING Scheduler.

No scheduler loop, additional GoalState store, permission grant, or automatic
dispatch is created here. The current scheduler may inject its sole LeaseTable,
canonical state reader and existing trusted read-only worker callback.

Effectful nodes and dependent nodes are always rejected by BRAIN-07B. The
lease table is in-process only: no cross-process/restart safety claim.
"""
from __future__ import annotations

import copy
import math
import threading
from typing import Callable

from modules import (
    goal_plan_gate, resource_leases, runtime_worker_result,
    scheduler_resource_gate, worker_result_hook,
)


class LeaseExecutionRejected(ValueError):
    """No read-only work/WorkerResult may be accepted for this stale session."""


class _Lifetime:
    """A local lease owned by the calling Scheduler, not by the worker result."""

    def __init__(self, leases, read_state, selected, attempt, ticket, ttl, interval):
        self.leases = leases
        self.read_state = read_state
        self.selected = selected
        self.attempt = attempt
        self.ticket = ticket
        self.ttl = ttl
        self.interval = interval
        self.cancel = threading.Event()
        self._stopped = threading.Event()
        self._guard = threading.RLock()
        self._failed = False
        self._watcher = threading.Thread(
            target=self._pulse, name="jarvis-plan-lease-heartbeat", daemon=True,
        )

    def start(self):
        self._watcher.start()

    def _check(self):
        if self._failed or self.cancel.is_set():
            raise LeaseExecutionRejected("Read-only worker lease already lost.")
        return scheduler_resource_gate.validate_before_dispatch(
            self.leases, self.read_state(), self.selected, self.ticket,
            attempt=self.attempt,
        )

    def _pulse(self):
        while not self._stopped.wait(self.interval):
            with self._guard:
                if self._stopped.is_set():
                    return
                try:
                    self._check()
                    self.ticket = self.leases.heartbeat(self.ticket, ttl=self.ttl)
                except (ValueError, OSError):
                    # If the canonical plan changed or the lease expired, the
                    # cooperative worker gets a cancel signal. No task grant.
                    self._failed = True
                    self.cancel.set()
                    return

    def check_before_worker(self):
        with self._guard:
            return self._check()

    def accept(self, output, expected):
        with self._guard:
            self._check()
            ticket = self.ticket

            def accept_current():
                self._check()
                return runtime_worker_result.accept_and_commit(output, expected)

            # Lock the SAME table against another local lease claimant while
            # canonical GoalState checks and existing CAS are performed.
            return self.leases.while_current(ticket, accept_current)

    def close(self):
        self._stopped.set()
        if self._watcher.ident is not None:
            self._watcher.join(timeout=1.0)
        with self._guard:
            ticket = self.ticket
            if self.leases.validate(ticket):
                self.leases.release(ticket)


def execute_readonly_once(
    leases: resource_leases.LeaseTable,
    read_state: Callable[[], dict],
    selected: goal_plan_gate.NodeCandidate,
    run_worker: Callable[[str, dict, dict, threading.Event], dict],
    *,
    attempt: int,
    ttl: float = 30.0,
    heartbeat_interval: float | None = None,
) -> dict:
    """Run ONE scheduler-selected independent read-only plan node.

    The only worker entrypoint is an explicitly injected, trusted callback:
    run_worker(kind, canonical_input, enriched_identity, cancel_event).
    The callback may only return a raw observation (never a pre-built
    WorkerResult envelope); Core wraps, validates, and persists it through the
    one existing canonical Reducer/CAS. This helper never chooses a worker.

    A changed plan/GoalState, a cancelled/expired/replaced lease, an invalid
    WorkerResult or a conflict in CAS fails closed; the lease is released on
    success or error. The heartbeat can request cooperative cancellation
    during a long read. Neither this adapter nor the in-memory lease confers
    permission to perform a write/effect.
    """
    if not callable(read_state) or not callable(run_worker):
        raise LeaseExecutionRejected("Existing scheduler readers/workers required.")
    if type(attempt) is not int or not 1 <= attempt <= 1_000_000:
        raise LeaseExecutionRejected("Worker attempt must be positive and bounded.")
    if type(ttl) not in (int, float) or not math.isfinite(ttl) or not 1 <= ttl <= 300:
        raise LeaseExecutionRejected("Lease TTL invalid.")
    interval = ttl / 3 if heartbeat_interval is None else heartbeat_interval
    if (type(interval) not in (int, float) or not math.isfinite(interval)
            or not 0 < interval < ttl):
        raise LeaseExecutionRejected("Heartbeat interval must be positive and below TTL.")

    snapshot = read_state()
    ticket = scheduler_resource_gate.admit(
        leases, snapshot, selected, attempt=attempt, ttl=ttl,
    )
    lifetime = _Lifetime(leases, read_state, selected, attempt, ticket, ttl, interval)
    try:
        node = lifetime.check_before_worker()
        kind = node["capability_id"].split(".", 1)[1]
        identity = {
            "version": 1, "owner": selected.owner,
            "job_id": selected.job_id, "task_id": selected.node_id,
            "attempt": attempt,
        }
        # The existing runtime bridge loads the very same canonical GoalState
        # store as the Scheduler, not a parallel execution journal.
        enriched, expected = runtime_worker_result.prepare(
            identity, kind, node["input"],
        )
        if (expected.get("plan_version") != selected.plan_version
                or expected.get("node_digest") != selected.node_digest
                or expected.get("expected_job_version") != selected.expected_goal_version
                or expected.get("command_id") != ticket.command_id
                or expected.get("capability_id") != node["capability_id"]):
            raise LeaseExecutionRejected("Prepared worker fence differs from canonical plan.")

        lifetime.start()
        lifetime.check_before_worker()
        raw = run_worker(kind, copy.deepcopy(node["input"]), enriched, lifetime.cancel)
        if lifetime.cancel.is_set():
            raise LeaseExecutionRejected("Worker cancelled before result acceptance.")
        if not isinstance(raw, dict) or "_worker_result" in raw:
            raise LeaseExecutionRejected("Worker must return a raw observation.")
        wrapped = worker_result_hook.wrap_output(raw, enriched)
        if "_worker_result" not in wrapped:
            raise LeaseExecutionRejected("Worker returned no admissible result envelope.")
        return lifetime.accept(wrapped, expected)
    finally:
        lifetime.close()
