"""Narrow runtime wrapper that emits WorkerResult v1 at the goal-tool boundary."""
from __future__ import annotations

import copy


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
    planned = set(worker_result.PLAN_FENCE).intersection(identity)
    if planned and planned != set(worker_result.PLAN_FENCE):
        raise ValueError('Eksik plan fence: eski schema ile sessiz düşüş yasak.')
    proof = {
        'state': output.get('state'),
        'verification': copy.deepcopy(output.get('verification')),
    }
    if planned and output.get('state') == 'done':
        # The previous Core contract proved *that* the root was accepted, but
        # did not bind its ExecutionRecord output bytes to that acceptance.
        # No legacy/v1 envelope changes and no unverified retroactive upgrade.
        from modules import dependency_evidence
        proof['output_sha256'] = dependency_evidence.output_sha256(output)
    envelope = {
        'schema': worker_result.PLAN_SCHEMA if planned else worker_result.SCHEMA,
        'status': 'succeeded' if output.get('state') == 'done' else 'failed',
        'evidence': [proof],
        **{key: copy.deepcopy(identity[key]) for key in required},
        **{key: copy.deepcopy(identity[key]) for key in worker_result.PLAN_FENCE if key in planned},
    }
    worker_result.validate(envelope)
    wrapped = copy.deepcopy(output)
    wrapped['_worker_result'] = envelope
    return wrapped


def execute(runtime, kind, data, dependencies, identity, *, approval=None):
    """Call the current goal_tools adapter and fence only this invocation's result."""
    from modules import goal_tools, runtime_worker_result
    # A canonical worker may have spent its entire budget in planning,
    # permission or predecessor checks. Recheck immediately at the actual
    # adapter boundary: an expired attempt must not START provider work.
    # Unscheduled/legacy calls have no Scheduler stop scope and are unchanged.
    runtime_worker_result.require_scheduler_active()
    result = goal_tools.execute(runtime, kind, data, dependencies, identity, approval=approval)
    if isinstance(result, dict) and result.get('state') == 'done':
        # A worker's "done" claim is not Core acceptance. Verify signed task
        # evidence / local readback before it can reach a success CAS commit.
        goal_tools.verify(result, identity['owner'])
    return wrap_output(result, identity)
