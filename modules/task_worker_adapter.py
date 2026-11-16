"""Shared task worker boundary for Core/Canonical specialist calls.

The legacy task DAG may still have its own worker wrapper until its queue and
persisted job semantics are migrated. Canonical Core never calls that executor.
"""
import copy
from modules import hooks, task_tools, task_results, task_workers


def worker(owner, task, dependencies):
    task = copy.deepcopy(task)
    task["input"] = task_tools.validate_input(task["agent"], task.get("input", {}))
    hooks.observe("tool", {"phase": "start", "tool": task["agent"],
                           "task_id": task.get("id", "")}, owner=owner)
    state = "failed"
    try:
        output = task_results.seal(task["agent"], task_workers.run(owner, task, dependencies))
        state = output.get("state", "failed") if isinstance(output, dict) else "failed"
        return output
    finally:
        hooks.observe("tool", {"phase": "end", "tool": task["agent"],
                               "task_id": task.get("id", ""), "state": state}, owner=owner)
