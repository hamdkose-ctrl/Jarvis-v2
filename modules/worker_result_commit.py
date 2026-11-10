"""Persist one already-accepted WorkerResult as canonical GoalState evidence.

This adapter is deliberately narrow: it does not execute workers and it does not
change the legacy job state.  It appends evidence through Core State Reducer and
persists with GoalState CAS before the normal legacy save/sync continues.
"""
from __future__ import annotations

import copy
import hashlib
import json

from modules import core_state_reducer, goal_state_store, worker_result


_REASON = 'WORKER_RESULT_ACCEPTED'


def _path(accepted: dict):
    from modules import goal_executor
    return goal_executor._root(accepted['owner']) / (accepted['job_id'] + '.goalstate.json')


def _evidence(accepted: dict) -> dict:
    row = worker_result.validate(accepted)
    return {
        'kind': 'worker_result',
        'owner': row['owner'],
        'job_id': row['job_id'],
        'step_id': row['step_id'],
        'command_id': row['command_id'],
        'attempt': row['attempt'],
        'expected_job_version': row['expected_job_version'],
        'capability_id': row['capability_id'],
        'capability_version': row['capability_version'],
        'input_digest': row['input_digest'],
        'status': row['status'],
        'evidence': copy.deepcopy(row['evidence']),
        **{field: row[field] for field in worker_result.PLAN_FENCE if field in row},
    }




def _read_only_manifest(capability_id: str) -> dict | None:
    """Reuse the installed static manifest; an arbitrary capability ID is not proof."""
    from modules import capability_manifest
    if not isinstance(capability_id, str):
        return None
    try:
        if capability_id.startswith('task.'):
            row = capability_manifest.from_task_tool(capability_id.removeprefix('task.'))
        elif capability_id.startswith('goal.'):
            row = capability_manifest.from_goal_tool(capability_id.removeprefix('goal.'))
        else:
            return None
    except ValueError:
        return None
    if row['id'] != capability_id or row['effect_policy'] != 'read_only':
        return None
    return row


def _independent_worker_only_advance(current: dict, accepted: dict) -> bool:
    """Allow a late *different root* only across accepted worker evidence.

    A concurrent read-only root can legitimately finish after another root
    moves the canonical version. Never rebase over user edits, state changes,
    plan revisions, unknown evidence, a dependent node or a duplicate node.
    This proves only that the intervening CAS writes were accepted worker
    results; it grants no scheduler, permission, lease or completion authority.
    """
    from modules import goal_plan_gate
    expected_version = accepted['expected_job_version']
    selected = _read_only_manifest(accepted['capability_id'])
    if (accepted['schema'] != worker_result.PLAN_SCHEMA
            or not 0 <= expected_version < current['version']
            or selected is None
            or accepted['capability_version'] != str(selected['version'])):
        return False
    intervening = current['audit'][expected_version + 1:]
    if not intervening or any(
        item['op'] != 'append_evidence' or item['reason_code'] != _REASON
        for item in intervening
    ):
        return False
    if len(current['evidence']) < len(intervening):
        return False
    # The new result must match its canonical node payload exactly; a caller
    # cannot broaden rebase by claiming an unrelated input for the same root.
    active = next(
        (n for n in current['goal_plan']['nodes']
         if n['id'] == accepted['step_id']), None,
    )
    if active is None or active['depends_on']:
        return False
    canonical = json.dumps(
        active['input'], ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False,
    ).encode('utf-8')
    if accepted['input_digest'] != hashlib.sha256(canonical).hexdigest():
        return False
    appended = current['evidence'][-len(intervening):]
    seen = set()
    for row in appended:
        if (not isinstance(row, dict) or row.get('kind') != 'worker_result'
                or row.get('status') not in {'succeeded', 'failed'}
                or row.get('owner') != accepted['owner']
                or row.get('job_id') != accepted['job_id']
                or row.get('plan_version') != accepted['plan_version']):
            return False
        step_id = row.get('step_id')
        attempt = row.get('attempt')
        if (not isinstance(step_id, str) or not step_id
                or step_id == accepted['step_id'] or step_id in seen
                or type(attempt) is not int or attempt < 0):
            return False
        seen.add(step_id)
        try:
            selection = goal_plan_gate.candidate(
                current, owner=accepted['owner'],
                job_id=accepted['job_id'], node_id=step_id,
            )
            node = goal_plan_gate.revalidate(current, selection)
        except ValueError:
            return False
        manifest = _read_only_manifest(node['capability_id'])
        canonical_input = json.dumps(
            node['input'], ensure_ascii=False, sort_keys=True,
            separators=(',', ':'), allow_nan=False,
        ).encode('utf-8')
        if (node['depends_on'] or manifest is None
                or selection.node_digest != row.get('node_digest')
                or node['capability_id'] != row.get('capability_id')
                or row.get('capability_version') != str(manifest['version'])
                or row.get('input_digest') != hashlib.sha256(canonical_input).hexdigest()
                or row.get('command_id') !=
                   f"{step_id}:{attempt}:p{accepted['plan_version']}"):
            return False
    return True


def commit(accepted: dict) -> dict:
    """Append one accepted result; only canonical CAS is retried, never a worker."""
    evidence = _evidence(accepted)
    path = _path(accepted)
    return _commit_once(accepted, evidence, path, retries=2)


def _commit_once(accepted: dict, evidence: dict, path, *, retries: int) -> dict:
    """Re-read every plan/identity fence after a concurrent CAS winner."""
    current = goal_state_store.load(path)
    if current['owner'] != accepted['owner'] or current['job_id'] != accepted['job_id']:
        raise ValueError('WorkerResult canonical GoalState kimliğiyle eşleşmiyor.')

    if current.get('goal_plan') is not None:
        from modules import goal_plan_gate
        if accepted['schema'] != worker_result.PLAN_SCHEMA:
            raise goal_state_store.PersistedStateConflict(
                'Planlı GoalState legacy WorkerResult.v1 kabul etmez.'
            )
        selection = goal_plan_gate.candidate(
            current, owner=accepted['owner'], job_id=accepted['job_id'],
            node_id=accepted['step_id'],
        )
        node = goal_plan_gate.revalidate(current, selection)
        if (node['depends_on'] or node['capability_id'] != accepted['capability_id']
                or selection.plan_version != accepted['plan_version']
                or selection.node_digest != accepted['node_digest']
                or accepted['command_id'] !=
                   f"{accepted['step_id']}:{accepted['attempt']}:p{accepted['plan_version']}"):
            raise goal_state_store.PersistedStateConflict(
                'WorkerResult node/plan sürümü veya dependency fence geçersiz.'
            )
    elif accepted['schema'] != worker_result.SCHEMA:
        raise goal_state_store.PersistedStateConflict(
            'Canonical plan yokken planlı WorkerResult kabul edilemez.'
        )

    matches = [
        row for row in current['evidence']
        if isinstance(row, dict)
        and row.get('kind') == 'worker_result'
        and row.get('command_id') == evidence['command_id']
    ]
    if matches:
        if len(matches) != 1 or matches[0] != evidence:
            raise goal_state_store.PersistedStateConflict(
                'WorkerResult command_id farklı evidence ile daha önce kaydedilmiş.'
            )
        return current

    if current.get('goal_plan') is not None and any(
        isinstance(row, dict) and row.get('kind') == 'worker_result'
        and row.get('owner') == accepted['owner']
        and row.get('job_id') == accepted['job_id']
        and row.get('step_id') == accepted['step_id']
        and row.get('plan_version') == accepted['plan_version']
        and row.get('node_digest') == accepted['node_digest']
        and row.get('status') == 'succeeded'
        for row in current['evidence']
    ):
        # Replay of the *same* command was handled above. Another attempt
        # must not silently run a root that already has accepted success.
        raise goal_state_store.PersistedStateConflict(
            'Plan node için önceki başarılı WorkerResult mevcut; tekrar kabul edilmedi.'
        )

    if (current['version'] != accepted['expected_job_version']
            and not _independent_worker_only_advance(current, accepted)):
        raise goal_state_store.PersistedStateConflict(
            'WorkerResult stale GoalState sürümüne ait; evidence yazılmadı.'
        )

    if current.get('goal_plan') is not None:
        # Exact replay and previous success were already fenced above.
        # Recheck read-only readiness against the latest canonical evidence
        # immediately before CAS; accepting a stale user-corrected plan or
        # an already completed root here would defeat pre-dispatch gating.
        goal_plan_gate.validate_root_attempt(
            current, selection, attempt=accepted['attempt'],
        )
        if accepted['capability_id'] == 'task.account':
            # The lease remains held across worker verification and Core CAS.
            # A direct model/worker/recovery caller cannot mint an unleased
            # new account success. Exact accepted-command replay exits above.
            from modules import scheduler_resource_gate
            scheduler_resource_gate.require_account_result_lease(accepted)

    next_state = core_state_reducer.apply(current, {
        'expected_version': current['version'],
        'op': 'append_evidence',
        'evidence': evidence,
        'reason_code': _REASON,
    })
    try:
        saved = goal_state_store.compare_and_swap(
            path, expected_version=current['version'], next_state=next_state
        )
    except goal_state_store.PersistedStateConflict:
        # Only a genuinely advanced planned GoalState may retry this CAS.
        # The next attempt revalidates plan, owner, roots, input, status and
        # all intervening writes; no external worker/effect is ever repeated.
        if accepted['schema'] != worker_result.PLAN_SCHEMA or retries <= 0:
            raise
        later = goal_state_store.load(path)
        if later['version'] <= current['version']:
            raise
        return _commit_once(accepted, evidence, path, retries=retries - 1)
    from modules import goal_job_control
    goal_job_control.mark_worker_commit(path.parent, accepted['job_id'], current['version'], saved['version'])
    return saved
