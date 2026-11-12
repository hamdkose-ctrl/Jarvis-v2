"""BRAIN-07: bounded, owner-pinned canonical workers in the existing Scheduler.

The Scheduler decides when to call this adapter. There is no second poller or
GoalState store. The existing specialist, DecisionAuthority, ResourceLease and
Core WorkerResult CAS remain the only execution/acceptance path.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from bisect import bisect_right
import re
import threading
import time
from types import SimpleNamespace

import release_guard
from modules.diagnostics import record_failure as _record_failure
from modules import (
    canonical_output_projection, canonical_restart_audit,
    canonical_scheduler_lane, execution_record,
    goal_executor, goal_job_control, goal_plan_gate, goal_state_store,
    runtime_worker_result, specialist_orchestrator,
)

_JOB_RECORD = re.compile(r"([a-f0-9]{16})\.execution\.json\Z")
# Cursor affects fairness only; readiness/authority are always re-read from disk.
_SCAN_CURSOR = {}
_RECOVERY_CURSOR = {}
_SCAN_LOCK = threading.Lock()


@dataclass(frozen=True)
class CompletionRecoveryOffer:
    owner: str
    job_id: str
    goal_version: int
    plan_version: int
    record_digest: str


def recoverable_completions(owner: str, *, max_jobs: int = 8,
                            max_results: int = 1) -> tuple[CompletionRecoveryOffer, ...]:
    """Offer only already-projected, Core-accepted goals for semantic wakeup.

    No planner, provider, worker, delivery or journal mutation happens here.
    The existing completion callback re-certifies all evidence and CAS-fences
    the final decision. Partial/unknown attempts never qualify.
    """
    if (type(max_jobs) is not int or not 1 <= max_jobs <= 32
            or type(max_results) is not int or not 1 <= max_results <= 8):
        raise ValueError("Completion recovery scan limits invalid.")
    root = goal_executor._owner_root(owner)
    if not root.is_dir() or root.is_symlink():
        return ()
    paths = sorted(root.glob("*.execution.json"))
    if not paths:
        return ()
    with _SCAN_LOCK:
        cursor_key = (str(root), owner)
        index = bisect_right(
            [path.name for path in paths], _RECOVERY_CURSOR.get(cursor_key, ""),
        )
        batch = (paths[index:] + paths[:index])[:max_jobs]
        _RECOVERY_CURSOR[cursor_key] = batch[-1].name
    offered = []
    for path in batch:
        match = _JOB_RECORD.fullmatch(path.name)
        if not match or path.is_symlink() or not path.is_file():
            continue
        job_id = match.group(1)
        try:
            with goal_job_control.locked(root, job_id):
                snapshot = canonical_restart_audit.inspect(owner, job_id)
                if not snapshot.nodes or any(
                    node.status != "accepted_projected" for node in snapshot.nodes
                ):
                    continue
                record = execution_record.load(root, owner, job_id)
                if (record.get("_canonical_delivery")
                        or goal_job_control.fingerprint(record) != snapshot.record_digest):
                    continue
                offered.append(CompletionRecoveryOffer(
                    owner, job_id, snapshot.goal_version,
                    snapshot.plan_version, snapshot.record_digest,
                ))
                if len(offered) >= max_results:
                    break
        except (ValueError, PermissionError, OSError, TypeError, KeyError, IndexError):
            # Corrupt/foreign/changed evidence never causes a recovery callback.
            continue
    return tuple(offered)


def discover(owner: str, *, max_jobs: int = 8, max_offers: int = 2):
    """Bounded read of previously published, running canonical goal journals."""
    if (type(max_jobs) is not int or not 1 <= max_jobs <= 32
            or type(max_offers) is not int or not 1 <= max_offers <= 8):
        raise ValueError("Canonical scheduler scan limits invalid.")
    root = goal_executor._owner_root(owner)
    if not root.is_dir():
        return ()
    offers = []
    paths = sorted(root.glob("*.execution.json"))
    if not paths:
        return ()
    # Always advance by a bounded group, even when all of its journals are
    # corrupt, completed or already running. Otherwise a ninth goal can be
    # permanently invisible behind eight older journals for the same owner.
    with _SCAN_LOCK:
        cursor_key = (str(root), owner)
        next_index = bisect_right(
            [path.name for path in paths], _SCAN_CURSOR.get(cursor_key, ""),
        )
        batch = (paths[next_index:] + paths[:next_index])[:max_jobs]
        _SCAN_CURSOR[cursor_key] = batch[-1].name
    for path in batch:
        match = _JOB_RECORD.fullmatch(path.name)
        if not match or path.is_symlink() or not path.is_file():
            continue
        try:
            offers.extend(canonical_scheduler_lane.ready_offers(
                owner, match.group(1), limit=max_offers,
            ))
        except (ValueError, PermissionError, OSError, TypeError):
            # A corrupt or foreign job cannot stop unrelated owner work.
            continue
        if len(offers) >= max_offers:
            break
    return tuple(offers[:max_offers])


def _record_failed_if_unaccepted(owner: str, job_id: str, node_id: str,
                                 *, plan_version: int, node_digest: str,
                                 deadline_expired: bool = False) -> None:
    """Never clobber a projected result, terminal job, or an accepted success.

    If a provider stops or fails, its started first attempt is durably fenced
    against automatic retry. An accepted but unprojected success is left for
    reconciliation rather than being misrepresented as a failed tool result.
    """
    root = goal_executor._owner_root(owner)
    with goal_job_control.locked(root, job_id):
        state = goal_state_store.load(root / (job_id + ".goalstate.json"))
        if ((state["owner"], state["job_id"]) != (owner, job_id)
                or state["state"] not in ("pending", "running")):
            return
        # A late worker failure must NEVER annotate a revised plan or a
        # cancelled/closed goal. An old attempt's journal belongs to its
        # original canonical command, not an arbitrary reused node ID.
        current_plan = state.get("goal_plan")
        if (not isinstance(current_plan, dict)
                or current_plan.get("plan_version") != plan_version
                or goal_plan_gate.fingerprints(current_plan).get(node_id) != node_digest):
            return
        if any(
            isinstance(row, dict) and row.get("kind") == "worker_result"
            and row.get("owner") == owner and row.get("job_id") == job_id
            and row.get("step_id") == node_id and row.get("status") == "succeeded"
            and state.get("goal_plan") is not None
            and row.get("plan_version") == state["goal_plan"]["plan_version"]
            for row in state["evidence"]
        ):
            return
        path = execution_record.path_for(root, job_id)
        job = execution_record.load(root, owner, job_id)
        matches = [s for s in job.get("steps", [])
                   if isinstance(s, dict) and s.get("id") == node_id]
        if (len(matches) != 1 or job.get("state") != "running"
                or matches[0].get("state") != "running"
                or matches[0].get("attempts") != 1
                or node_id in job.get("outputs", {})):
            return
        matches[0]["state"] = "failed"
        job["outputs"][node_id] = {
            "state": "failed",
            "text": (
                "Canonical worker deadline elapsed; external read outcome "
                "is not proven. Manual review required; never retry automatically."
                if deadline_expired else
                "Canonical read-only worker stopped; manual review required."
            ),
        }
        # Preserve the pre-existing generic failure record contract; only
        # a proven deadline fence gains this additional reason classification.
        if deadline_expired:
            job["outputs"][node_id]["reason_code"] = (
                "CANONICAL_WORKER_DEADLINE_UNACCEPTED"
            )
        job["updated"] = time.time()
        release_guard.atomic(path, execution_record.encode(job))


def execute_offer(profile, offer, *, stop_event=None):
    """Run ONE already published node using a strictly pinned owner identity.

    This facade deliberately exposes no mutable foreground runtime, UI, voice,
    or native-effect methods. The supported research/account tool adapters use
    the owner identity and existing registered task workers only.
    """
    if not isinstance(offer, canonical_scheduler_lane.ReadyOffer):
        raise canonical_scheduler_lane.DispatchFenceError("Invalid worker offer.")
    selected = offer.selection
    if getattr(profile, "slug", None) != selected.owner:
        raise PermissionError("Canonical worker profile does not match owner.")
    if stop_event is not None and stop_event.is_set():
        return False

    root = goal_executor._owner_root(selected.owner)
    record_path = execution_record.path_for(root, selected.job_id)
    with goal_job_control.locked(root, selected.job_id):
        canonical_scheduler_lane.revalidate_offer(offer)
        state, job = canonical_scheduler_lane._load(
            selected.owner, selected.job_id,
        )
        node = goal_plan_gate.revalidate(state, selected)
        matches = [step for step in job["steps"]
                   if isinstance(step, dict) and step.get("id") == selected.node_id]
        if len(matches) != 1 or matches[0].get("state") != "queued":
            raise canonical_scheduler_lane.DispatchFenceError(
                "Canonical step was claimed by another worker."
            )
        step = matches[0]
        if (step["tool"] != selected.capability_id.removeprefix("task.")
                or step["input"] != node["input"] or step["depends"] != node["depends_on"]):
            raise canonical_scheduler_lane.DispatchFenceError("Published step changed.")
        step["state"] = "running"
        step["started"] = True
        step["attempts"] = 1
        job["updated"] = time.time()
        release_guard.atomic(record_path, execution_record.encode(job))

    try:
        # Preflight after persisting a first-attempt claim is part of that
        # attempt. A malformed identity must not escape the failure fence
        # and strand an unaccepted 'running' journal forever.
        # The identity is built by the current goal executor, not a model.
        runtime = SimpleNamespace(profile=SimpleNamespace(slug=selected.owner))
        identity = goal_executor._identity(job, step)
        identity["_canonical_scheduler_offer"] = {
            "owner": selected.owner, "job_id": selected.job_id,
            "node_id": selected.node_id, "plan_version": selected.plan_version,
            "node_digest": selected.node_digest,
        }
        # This synchronous thread-bound scope travels through the existing
        # specialist/lease/WorkerResult path. A stop during provider execution
        # fences the Core CAS, even if the external task later returns "done".
        with runtime_worker_result.scheduler_stop_scope(stop_event):
            result = specialist_orchestrator.execute_step(
                runtime, job, copy.deepcopy(step), identity,
            )
        if not isinstance(result, dict) or result.get("state") != "done":
            raise ValueError("Canonical read-only worker did not succeed.")
        canonical_output_projection.project_accepted(
            selected.owner, selected.job_id, selected.node_id, result,
        )
        return True
    except Exception as exc:
        _record_failure('modules/canonical_scheduler_dispatch.py:execute_offer')
        _record_failed_if_unaccepted(
            selected.owner, selected.job_id, selected.node_id,
            plan_version=selected.plan_version, node_digest=selected.node_digest,
            deadline_expired=isinstance(
                exc, runtime_worker_result.CanonicalWorkerDeadlineExceeded,
            ),
        )
        raise
