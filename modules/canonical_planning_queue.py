"""VOICE §5: durable first-plan handoff into the ONE existing Scheduler.

The first read-only proposal is made on a pinned owner worker, not while
engine_loop owns the foreground identity lock. Admission and progress use the
existing GoalState + ExecutionRecord pair, not another job database. A crashed
or timed-out provider is NEVER retried automatically. Unsupported/effectful
plans are parked for foreground review, not executed by a background worker.
"""
from __future__ import annotations

from bisect import bisect_right
import hashlib
import json
import re
import threading
import time

import release_guard
from modules import (
    canonical_goal_flow, execution_record, goal_executor,
    goal_job_control, goal_plan_gate, goal_state, goal_state_compat,
    goal_state_store, llm, model_wait, requests_state, task_agents,
)

_SCAN_LOCK = threading.Lock()
_SCAN_CURSOR = {}
_JOB_ID = re.compile(r"[0-9a-f]{16}\Z")
_PLANNER_SECONDS = 60


def _identity(owner: str, request_id: str):
    job_id = hashlib.sha256((owner + "\0" + request_id).encode("utf-8")).hexdigest()[:16]
    planner_rid = hashlib.sha256(
        (owner + "\0" + request_id + "\0background-planner").encode("utf-8")
    ).hexdigest()[:32]
    return job_id, planner_rid


def _check_pair(root, owner: str, job_id: str, *, request_id=None, text=None):
    path = execution_record.path_for(root, job_id)
    state_path = root / (job_id + ".goalstate.json")
    if (path.is_symlink() or state_path.is_symlink()
            or not path.is_file() or not state_path.is_file()):
        raise ValueError("Background planner publication incomplete.")
    record = execution_record.load(root, owner, job_id)
    state = goal_state_store.load(state_path)
    if ((record.get("id"), record.get("owner")) != (job_id, owner)
            or (state["job_id"], state["owner"]) != (job_id, owner)
            or goal_state.authority(state) != "canonical"
            or record.get("request") != state["goal"]
            or not isinstance(record.get("request_id"), str)
            or record.get("_planner_rid") != _identity(owner, record["request_id"])[1]
            or (request_id is not None and record["request_id"] != request_id)
            or (text is not None and record["request"] != text)):
        raise ValueError("Background planner owner/request identity mismatch.")
    return state, record


def enqueue(owner: str, request_id: str, text: str):
    """Durably admit one typed CREATE; never invoke a model in the engine turn."""
    if (not isinstance(owner, str) or not owner.strip()
            or not isinstance(request_id, str) or not request_id.strip()
            or not isinstance(text, str) or not text.strip() or len(text) > 20000):
        raise ValueError("Background planning request invalid.")
    text = text.strip()
    requests_state.check()
    job_id, planner_rid = _identity(owner, request_id)
    root = goal_executor._root(owner)
    path = execution_record.path_for(root, job_id)
    state_path = root / (job_id + ".goalstate.json")
    with goal_job_control.locked(root, job_id):
        if (path.exists() or path.is_symlink()
                or state_path.exists() or state_path.is_symlink()):
            _check_pair(root, owner, job_id, request_id=request_id, text=text)
            return (job_id, "Bu istek zaten kayıtlı; ikinci planlama başlatılmadı. "
                    f'Durum için "hedef sonucu {job_id}" yazabilirsin.')
        # The parent is the currently active authenticated Brain request.
        # Its child planner ID is distinct: finishing the foreground reply
        # cannot make the Scheduler's planner request appear completed.
        if not requests_state.register_background(owner, planner_rid, seconds=1800):
            raise ValueError("Background planner request already registered.")
        try:
            goal_state_compat.create_canonical_queued_goal(
                state_path, owner=owner, job_id=job_id, goal=text)
            now = time.time()
            record = {
                "id": job_id, "owner": owner, "request_id": request_id,
                "_planner_rid": planner_rid,
                "request": text, "created": now, "updated": now,
                "state": "planning_queued", "goals": [
                    {"text": text, "state": "pending", "evidence": []}
                ], "steps": [], "outputs": {},
            }
            release_guard.atomic(path, execution_record.encode(record))
        except BaseException:
            requests_state.cancel(owner, planner_rid)
            raise
    return (job_id, "İsteğini planlama kuyruğuna aldım. Bu sırada yeni komut verebilirsin. "
            f'Durum için "hedef sonucu {job_id}" yazabilirsin.')


def discover(owner: str, *, max_jobs: int = 16, max_results: int = 3):
    """Bounded, fair Scheduler discovery of unstarted owner-bound plans."""
    if type(max_jobs) is not int or not 1 <= max_jobs <= 64:
        raise ValueError("Planner scan bound invalid.")
    if type(max_results) is not int or not 1 <= max_results <= 3:
        raise ValueError("Planner worker bound invalid.")
    root = goal_executor._owner_root(owner)
    if not root.is_dir() or root.is_symlink():
        return ()
    paths = sorted(root.glob("*.execution.json"))
    if not paths:
        return ()
    with _SCAN_LOCK:
        key = (str(root), owner)
        start = bisect_right([p.name for p in paths], _SCAN_CURSOR.get(key, ""))
        batch = (paths[start:] + paths[:start])[:max_jobs]
        _SCAN_CURSOR[key] = batch[-1].name
    ready = []
    for path in batch:
        job_id = path.name.removesuffix(".execution.json")
        if not _JOB_ID.fullmatch(job_id) or path.is_symlink():
            continue
        try:
            with goal_job_control.locked(root, job_id):
                state, record = _check_pair(root, owner, job_id)
                if (record.get("state") == "planning_queued"
                        and state["state"] == "pending"
                        and state["version"] == 0
                        and "goal_plan" not in state):
                    ready.append(job_id)
            if len(ready) >= max_results:
                break
        except (ValueError, PermissionError, OSError, KeyError, TypeError):
            # Corrupt/mismatched owner records never schedule work.
            continue
    return tuple(ready)


def _park(root, owner, job_id, *, reason: str):
    """Fail closed after an uncertain attempt, with no automatic replay."""
    with goal_job_control.locked(root, job_id):
        state, record = _check_pair(root, owner, job_id)
        if record.get("state") != "planning_running" or "goal_plan" in state:
            return False
        if state["state"] == "pending":
            goal_state_compat.park_unplanned_canonical_goal(
                root / (job_id + ".goalstate.json"),
                owner=owner, job_id=job_id, reason=reason)
        record["state"] = "review"
        record["feedback"] = ["Arka plan planlaması durdu. "
                              "İşlem yürütülmedi; yeniden başlatmak için yeni açık istek gerekli."]
        record["updated"] = time.time()
        release_guard.atomic(execution_record.path_for(root, job_id),
                             execution_record.encode(record))
    return True


def execute(profile, job_id: str, *, stop_event=None):
    """ONE first planning attempt, pinned to an immutable registered owner."""
    owner = getattr(profile, "slug", None)
    if not isinstance(owner, str) or not _JOB_ID.fullmatch(str(job_id)):
        raise PermissionError("Pinned owner or planning identity invalid.")
    root = goal_executor._owner_root(owner)
    with goal_job_control.locked(root, job_id):
        state, record = _check_pair(root, owner, job_id)
        if (record.get("state") != "planning_queued"
                or state["state"] != "pending" or state["version"] != 0
                or "goal_plan" in state):
            return False
        planner_rid = record["_planner_rid"]
        cancelled = requests_state.is_cancelled(owner, planner_rid)
        if stop_event is not None and stop_event.is_set():
            return False
        # Persist a one-shot dispatch claim before any external call. If a
        # cancelled entry is discovered, park it instead of offering it forever.
        record["state"] = "planning_running"
        record["updated"] = time.time()
        release_guard.atomic(execution_record.path_for(root, job_id),
                             execution_record.encode(record))
        text = record["request"]
    if cancelled:
        _park(root, owner, job_id, reason="PLANNER_CANCELLED_BEFORE_START")
        return "review"

    token = llm._key_context.set(owner)
    try:
        with requests_state.activate(owner, planner_rid):
            requests_state.allow_long_operation(180)
            def stop_probe():
                if stop_event is not None and stop_event.is_set():
                    raise requests_state.Cancelled("Scheduler stopped the planner.")
            with requests_state.worker_probe(stop_probe):
                # Exactly the original approved task-graph planner and canonical
                # read-only admission schema; no regex classifier or second model.
                system = (
                    task_agents._SYSTEM +
                    "\nBu tur canonical arka plan araştırma önerisidir. Yalnız research "
                    "ve salt-okunur account görevleri öner; kanıtları birleştirmek "
                    "için yalnız doğrulanmış research/account bağımlı verify görevini kullan. "
                    "Writer dosyaya yazdığı için canonical salt-okunur kapsamda değildir. "
                    "Desteklenmeyen etkiyi planlama. "
                    "Kullanıcının istediği kapsamı karşılayamıyorsan uydurma kaynak verme."
                )
                raw = model_wait.ask(text, system=system, max_tokens=2200,
                                     seconds=_PLANNER_SECONDS)
                requests_state.check()
                if stop_event is not None and stop_event.is_set():
                    raise requests_state.Cancelled("Scheduler stopped.")
                try:
                    proposed = task_agents._json(raw)
                    tasks = task_agents.validate(proposed["tasks"])
                    plan = canonical_goal_flow._canonical_plan(tasks)
                except (ValueError, TypeError, KeyError):
                    _park(root, owner, job_id, reason="PLANNER_FOREGROUND_REVIEW_REQUIRED")
                    return "review"

                with goal_job_control.locked(root, job_id):
                    state, record = _check_pair(root, owner, job_id)
                    requests_state.check()
                    if stop_event is not None and stop_event.is_set():
                        raise requests_state.Cancelled("Scheduler stopped.")
                    if (record.get("state") != "planning_running"
                            or state["state"] != "pending" or state["version"] != 0
                            or "goal_plan" in state):
                        return False
                    saved = goal_state_compat.apply_goal_plan(
                        root / (job_id + ".goalstate.json"),
                        owner=owner, job_id=job_id,
                        expected_version=state["version"], plan=plan)
                    goal_plan_gate.ready_read_only_candidates(
                        saved, owner=owner, job_id=job_id)
                    record["steps"] = [{
                        "id": node["id"], "goal": 0,
                        "tool": node["capability_id"].removeprefix("task."),
                        "input": node["input"], "depends": list(node["depends_on"]),
                        "state": "queued", "started": False, "attempts": 0,
                    } for node in plan["nodes"]]
                    record["state"] = "running"
                    record["updated"] = time.time()
                    release_guard.atomic(execution_record.path_for(root, job_id),
                                         execution_record.encode(record))
                return "planned"
    except BaseException:
        # A timed-out worker is never relaunched without fresh user authority.
        _park(root, owner, job_id, reason="PLANNER_ATTEMPT_UNCERTAIN")
        return "review"
    finally:
        llm._key_context.reset(token)


def status(owner: str, job_id: str) -> str | None:
    """Read-only exact owner/job status; never retry a worker or model."""
    if not _JOB_ID.fullmatch(str(job_id)):
        return None
    root = goal_executor._owner_root(owner)
    try:
        with goal_job_control.locked(root, job_id):
            state, record = _check_pair(root, owner, job_id)
    except (ValueError, PermissionError, FileNotFoundError, OSError, KeyError, TypeError):
        return None
    stage = record.get("state")
    if stage == "planning_queued":
        return f"Hedef {job_id}: planlama için Scheduler kuyruğunda."
    if stage == "planning_running":
        return f"Hedef {job_id}: planlama modeli çalışıyor; diğer komutlar beklemez."
    if stage == "review" and "goal_plan" not in state:
        return (f"Hedef {job_id}: güvenli arka plan planlaması sonuçlanmadı. "
                "Desteklenmeyen işlemler otomatik yürütülmedi. "
                "Gerekirse işi yeni bir ön plan isteği olarak ilet.")
    if "goal_plan" in state and state["state"] in ("pending", "running"):
        return f"Hedef {job_id}: plan kabul edildi; Scheduler adımları yürütüyor."
    return None
