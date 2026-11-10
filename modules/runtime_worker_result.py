"""Runtime bridge from durable execution identity to WorkerResult v1 fencing."""
from __future__ import annotations

import copy
import hashlib
import json

from modules import capability_manifest, goal_state_store, worker_result


def durable_identity(identity: dict) -> bool:
    """True only for the versioned execution identity emitted by goal_executor.

    Older/direct specialist calls do not carry this runtime policy metadata and
    remain outside this migration slice.  A versioned identity is fail-closed:
    prepare() still validates every required field before a worker is called.
    """
    return isinstance(identity, dict) and isinstance(identity.get('version'), int)


def canonical_snapshot(identity: dict) -> dict:
    owner = identity.get('owner') if isinstance(identity, dict) else None
    job_id = identity.get('job_id') if isinstance(identity, dict) else None
    if not isinstance(owner, str) or not owner or not isinstance(job_id, str) or not job_id:
        raise ValueError('Worker execution kimliği eksik.')
    # Use the executor's active STORE/root rather than config.DATA_DIR. Tests and
    # isolated runtimes intentionally relocate STORE; the canonical sidecar is
    # created beside the legacy job by goal_state_save_hook.
    from modules import goal_executor
    path = goal_executor._root(owner) / (job_id + '.goalstate.json')
    state = goal_state_store.load(path)
    if state['owner'] != owner or state['job_id'] != job_id:
        raise ValueError('Canonical GoalState worker kimliğiyle eşleşmiyor.')
    return state


def canonical_version(identity: dict) -> int:
    return canonical_snapshot(identity)['version']


def prepare(identity: dict, kind: str, data: dict, *, expected_job_version: int | None = None):
    if not isinstance(identity, dict):
        raise ValueError('Worker kimliği geçersiz.')
    # Default durable execution reads the single canonical GoalState snapshot.
    # Explicit-version legacy/testing callers remain v1, but commit rejects a
    # v1 result if a canonical goal_plan is present (no version-fence bypass).
    snapshot = canonical_snapshot(identity) if expected_job_version is None else None
    if snapshot is not None:
        expected_job_version = snapshot['version']
    if not isinstance(expected_job_version, int) or isinstance(expected_job_version, bool) or expected_job_version < 0:
        raise ValueError('Beklenen GoalState sürümü geçersiz.')
    row = _capability(kind)
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    attempt = identity.get('attempt', 1)
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 0:
        raise ValueError('Worker attempt geçersiz.')
    owner = identity.get('owner'); job_id = identity.get('job_id'); step_id = identity.get('task_id')
    if not all(isinstance(value, str) and value for value in (owner, job_id, step_id)):
        raise ValueError('Worker execution kimliği eksik.')
    expected = {
        'owner': owner,
        'job_id': job_id,
        'step_id': step_id,
        'command_id': f'{step_id}:{attempt}',
        'attempt': attempt,
        'expected_job_version': expected_job_version,
        'capability_id': row['id'],
        'capability_version': str(row['version']),
        'input_digest': hashlib.sha256(payload.encode('utf-8')).hexdigest(),
    }
    if snapshot is not None and snapshot.get('goal_plan') is not None:
        from modules import goal_plan_gate
        if row['effect_policy'] != 'read_only':
            raise ValueError('Planlı dış etki BRAIN-07 lease/approval kabulüne kadar engelli.')
        selection = goal_plan_gate.candidate(
            snapshot, owner=owner, job_id=job_id, node_id=step_id,
        )
        node = goal_plan_gate.revalidate(snapshot, selection)
        if node['depends_on']:
            # BRAIN-06C cannot infer verified predecessor completion from a
            # claim or old worker log. BRAIN-06D/07 will supply this proof.
            raise ValueError('Bağımlı plan node doğrulanmış predecessor kanıtı olmadan başlatılamaz.')
        if node['capability_id'] != row['id'] or node['input'] != data:
            raise ValueError('Worker capability/input canonical plan node ile eşleşmiyor.')
        expected.update({
            'command_id': f"{step_id}:{attempt}:p{selection.plan_version}",
            'plan_version': selection.plan_version,
            'node_digest': selection.node_digest,
        })
    enriched = copy.deepcopy(identity)
    enriched.update(expected)
    return enriched, expected


def _accepted_and_clean(output: dict, expected: dict):
    if not isinstance(output, dict):
        raise ValueError('Worker çıktısı sözlük olmalı.')
    envelope = output.get('_worker_result')
    if not isinstance(envelope, dict):
        raise ValueError('WorkerResult fence kaydı eksik.')
    accepted = worker_result.accept(envelope, expected)
    clean = copy.deepcopy(output)
    clean.pop('_worker_result', None)
    return accepted, clean


def accept_output(output: dict, expected: dict) -> dict:
    """Validate one WorkerResult fence without mutating GoalState."""
    _accepted, clean = _accepted_and_clean(output, expected)
    return clean


def accept_and_commit(output: dict, expected: dict) -> dict:
    """Validate the exact fence, persist reducer evidence, then return clean output."""
    accepted, clean = _accepted_and_clean(output, expected)
    from modules import worker_result_commit
    worker_result_commit.commit(accepted)
    return clean


def _capability(kind: str) -> dict:
    """Use the read-only manifest projection; never introduce a runtime catalog."""
    try:
        return capability_manifest.from_task_tool(kind)
    except ValueError:
        return capability_manifest.from_goal_tool(kind)
