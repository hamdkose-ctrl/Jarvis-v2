"""BRAIN-07: project an *accepted* canonical WorkerResult to ExecutionRecord.

Never infer authority from a worker's "done" text or a mutable journal.
The one canonical GoalState must already contain an exact successful CAS
evidence row. The existing per-job OS control lock protects the projection.
This module does not schedule workers or declare a Goal completed.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import time

import release_guard
from modules import (
    dependency_evidence, execution_record, goal_job_control, goal_plan_gate,
    goal_state, goal_state_store,
)


class ProjectionFenceError(ValueError):
    """A result is not authorized for this ExecutionRecord projection."""


def _accepted_row(current: dict, owner: str, job_id: str,
                  node: dict, output: dict, *, allow_completed_read: bool = False) -> dict:
    plan = current.get('goal_plan')
    if not isinstance(plan, dict):
        raise ProjectionFenceError('Canonical GoalPlan missing.')
    digest = goal_plan_gate.fingerprints(plan)[node['id']]
    rows = [
        (position, evidence)
        for position, evidence in enumerate(current['evidence'])
        if isinstance(evidence, dict)
        and evidence.get('kind') == 'worker_result'
        and evidence.get('owner') == owner
        and evidence.get('job_id') == job_id
        and evidence.get('step_id') == node['id']
        and evidence.get('plan_version') == plan['plan_version']
        and evidence.get('status') == 'succeeded'
    ]
    if len(rows) != 1:
        raise ProjectionFenceError('Exactly one canonical accepted success required.')
    position, result = rows[0]
    from modules import capability_manifest
    capability = node['capability_id']
    if not capability.startswith('task.'):
        raise ProjectionFenceError('Only registered read-only task results can project.')
    try:
        manifest = capability_manifest.from_task_tool(capability.removeprefix('task.'))
    except ValueError:
        raise ProjectionFenceError('Unknown task capability.') from None
    attempt = result.get('attempt')
    encoded = json.dumps(node['input'], ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    if (manifest['id'] != capability or manifest['effect_policy'] != 'read_only'
            or result.get('capability_id') != capability
            or result.get('capability_version') != str(manifest['version'])
            or result.get('node_digest') != digest
            or result.get('input_digest') != hashlib.sha256(encoded).hexdigest()
            or type(attempt) is not int or attempt < 1
            or result.get('command_id') !=
               f"{node['id']}:{attempt}:p{plan['plan_version']}"):
        raise ProjectionFenceError('Accepted WorkerResult does not match active node.')

    appends = [
        (index, audit) for index, audit in enumerate(current['audit'])
        if audit['op'] == 'append_evidence'
    ]
    if len(appends) != len(current['evidence']):
        raise ProjectionFenceError('GoalState audit and evidence do not align.')
    audit_index, audit_row = appends[position]
    if audit_row['reason_code'] != 'WORKER_RESULT_ACCEPTED':
        raise ProjectionFenceError('Accepted WorkerResult audit reason missing.')
    # Projection itself remains live-only; it never uses terminal read mode.
    # A separately authorized owner-scoped result QUERY may ignore exactly
    # the final Core semantic-completion transition. User edits, plan changes
    # and any other intervening audit event must still reject the proof.
    later = current['audit'][audit_index + 1:]
    if allow_completed_read:
        if (current['state'] != 'done' or not later
                or later[-1]['op'] != 'set_state'
                or later[-1]['reason_code'] != 'CANONICAL_SEMANTIC_COMPLETION_VERIFIED'):
            raise ProjectionFenceError('Only Core-verified terminal results can be read.')
        later = later[:-1]
    if any(
        audit['op'] != 'append_evidence'
        or audit['reason_code'] != 'WORKER_RESULT_ACCEPTED'
        for audit in later
    ):
        raise ProjectionFenceError('Canonical goal changed after worker acceptance.')

    proofs = result.get('evidence')
    if (not isinstance(proofs, list) or len(proofs) != 1
            or not isinstance(proofs[0], dict)
            or proofs[0].get('state') != 'done'
            or proofs[0].get('verification') != output.get('verification')
            or output.get('state') != 'done'):
        raise ProjectionFenceError('Worker output proof does not match result.')
    fingerprint = proofs[0].get('output_sha256')
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise ProjectionFenceError('No cryptographic accepted output commitment.')
    try:
        actual = dependency_evidence.output_sha256(output)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ProjectionFenceError('Worker output is not canonical JSON.') from exc
    if not hmac.compare_digest(fingerprint, actual):
        raise ProjectionFenceError('Worker output bytes differ from Core evidence.')
    return result


def project_accepted(owner: str, job_id: str, step_id: str, output: dict) -> bool:
    """Record a successful canonical read-only node exactly once.

    Returns True for a new projection and False for an identical already
    projected result. Never executes a worker or retries an external action.
    The dependent worker still independently validates persisted output
    hashes AND domain evidence before launch and before Core result CAS.
    """
    if (not isinstance(owner, str) or not owner
            or not isinstance(job_id, str) or not job_id
            or not isinstance(step_id, str) or not step_id
            or not isinstance(output, dict)
            or '_worker_result' in output):
        raise ProjectionFenceError('Projection owner, step or clean output invalid.')
    from modules import goal_executor
    root = goal_executor._owner_root(owner)
    # An arbitrary foreign owner must not cause a new directory/control lock
    # file to be created merely because a projected worker ID was supplied.
    if not root.is_dir():
        raise ProjectionFenceError('Canonical owner journal does not exist.')
    record_path = execution_record.path_for(root, job_id)
    with goal_job_control.locked(root, job_id):
        current = goal_state_store.load(root / (job_id + '.goalstate.json'))
        if (current['owner'] != owner or current['job_id'] != job_id
                or current['state'] not in ('pending', 'running')
                or goal_state.authority(current) != 'canonical'):
            raise ProjectionFenceError('Only active canonical goal may project.')
        plan = current.get('goal_plan')
        if not isinstance(plan, dict):
            raise ProjectionFenceError('Canonical plan not published.')
        node = next((item for item in plan['nodes'] if item['id'] == step_id), None)
        if node is None:
            raise ProjectionFenceError('Step not present in current GoalPlan.')
        _accepted_row(current, owner, job_id, node, output)

        # Never create a new journal on a successful worker claim: the
        # existing executor must have published the authorized step first.
        if record_path.is_symlink() or not record_path.is_file():
            raise ProjectionFenceError('Durable ExecutionRecord not present.')
        job = execution_record.load(root, owner, job_id)
        if job.get('state') != 'running':
            raise ProjectionFenceError('ExecutionRecord is not actively running.')
        steps = [
            step for step in job.get('steps', [])
            if isinstance(step, dict) and step.get('id') == step_id
        ] if isinstance(job.get('steps'), list) else []
        if len(steps) != 1:
            raise ProjectionFenceError('Exactly one published ExecutionRecord step required.')
        step = steps[0]
        if (step.get('tool') != node['capability_id'].removeprefix('task.')
                or step.get('input') != node['input']
                or step.get('depends') != node['depends_on']):
            raise ProjectionFenceError('ExecutionRecord step differs from canonical plan.')
        outputs = job.get('outputs')
        if not isinstance(outputs, dict):
            raise ProjectionFenceError('ExecutionRecord outputs invalid.')
        previous = outputs.get(step_id)
        if previous is not None:
            if previous != output or step.get('state') != 'done':
                raise ProjectionFenceError('Existing projected output differs.')
            return False
        if step.get('state') not in ('queued', 'running'):
            raise ProjectionFenceError('Step is not awaiting accepted output.')
        outputs[step_id] = copy.deepcopy(output)
        step['state'] = 'done'
        job['updated'] = time.time()
        release_guard.atomic(record_path, execution_record.encode(job))
        return True
