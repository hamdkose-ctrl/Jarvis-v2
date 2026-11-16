"""Shared task worker boundary for Core/Canonical specialist calls.

`run` is the single worker body: input validation, tool hook observation and
result sealing. Canonical Core calls `worker`; the legacy task DAG reaches the
same body through `task_agents.worker`, which keeps its own injectable executor
seam until its queue and persisted job semantics are migrated.
"""
import copy
from modules import hooks, task_tools, task_results, task_workers


def run(owner, task, dependencies, execute=None):
    execute = execute or task_workers.run
    task = copy.deepcopy(task)
    task["input"] = task_tools.validate_input(task["agent"], task.get("input", {}))
    hooks.observe("tool", {"phase": "start", "tool": task["agent"],
                           "task_id": task.get("id", "")}, owner=owner)
    state = "failed"
    try:
        output = task_results.seal(task["agent"], execute(owner, task, dependencies))
        state = output.get("state", "failed") if isinstance(output, dict) else "failed"
        return output
    finally:
        hooks.observe("tool", {"phase": "end", "tool": task["agent"],
                               "task_id": task.get("id", ""), "state": state}, owner=owner)


def worker(owner, task, dependencies):
    return run(owner, task, dependencies)
