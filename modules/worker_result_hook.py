"""Narrow runtime hook that emits WorkerResult v1 at the goal-tool execution boundary."""
from __future__ import annotations

import copy

_INSTALLED = False
_ORIGINAL = None


def wrap_output(output: dict, identity: dict) -> dict:
    if not isinstance(output, dict):
        return output
    required = {
        'owner','job_id','step_id','command_id','attempt','expected_job_version',
        'capability_id','capability_version','input_digest',
    }
    if not isinstance(identity, dict) or not required.issubset(identity):
        return output
    if output.get('state') == 'approval':
        return output
    from modules import worker_result
    envelope = {
        'schema': worker_result.SCHEMA,
        'status': 'succeeded' if output.get('state') == 'done' else 'failed',
        'evidence': [{
            'state': output.get('state'),
            'verification': copy.deepcopy(output.get('verification')),
        }],
        **{key: copy.deepcopy(identity[key]) for key in required},
    }
    worker_result.validate(envelope)
    wrapped = copy.deepcopy(output)
    wrapped['_worker_result'] = envelope
    return wrapped


def install():
    global _INSTALLED, _ORIGINAL
    if _INSTALLED:
        return
    from modules import goal_tools
    _ORIGINAL = goal_tools.execute

    def guarded(runtime, kind, data, dependencies, identity, *, approval=None):
        result = _ORIGINAL(runtime, kind, data, dependencies, identity, approval=approval)
        return wrap_output(result, identity)

    goal_tools.execute = guarded
    _INSTALLED = True
