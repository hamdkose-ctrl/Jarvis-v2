"""Fence accepted, read-only reconcile results through the normal CAS path.

This boundary never calls a worker or repeats an effect.  It only binds a
successful reconcile observation to the durable execution identity that was
already created for the interrupted step, then reuses WorkerResult acceptance.
"""
from __future__ import annotations

import copy

from modules import goal_state_store, runtime_worker_result, worker_result_hook, worker_result


_FENCE = (
    'owner', 'job_id', 'step_id', 'command_id', 'attempt',
    'expected_job_version', 'capability_id', 'capability_version', 'input_digest',
)


def _fence_expected(identity: dict, kind: str, data: dict):
    """Reuse an already accepted command fence for idempotent reconciliation."""
    # Recovery is read-only and must reuse an accepted exact command below.
    # Skip the *new worker* preflight (an already succeeded root is not ready
    # for dispatch), never the plan/identity fence or CAS idempotency check.
    enriched, candidate = runtime_worker_result.prepare(
        identity, kind, data, reconcile_existing=True,
    )
    from modules import goal_executor
    path = goal_executor._root(candidate['owner']) / (candidate['job_id'] + '.goalstate.json')
    state = goal_state_store.load(path)
    matches = [
        row for row in state['evidence']
        if isinstance(row, dict) and row.get('kind') == 'worker_result'
        and row.get('command_id') == candidate['command_id']
    ]
    if not matches:
        if set(worker_result.PLAN_FENCE).issubset(candidate):
            # A read-only observation without a persisted exact execution fence
            # may belong to a previous plan; never mint a new plan identity
            # from current state during reconciliation.
            raise ValueError('Planlı reconcile için önceden kabul edilmiş execution fence gerekli.')
        return enriched, candidate
    if len(matches) != 1:
        raise ValueError('Reconcile WorkerResult için birden fazla command kaydı var.')
    previous = matches[0]
    plan_fields = set(worker_result.PLAN_FENCE)
    has_previous_plan = plan_fields.intersection(previous)
    has_candidate_plan = plan_fields.intersection(candidate)
    if has_previous_plan != has_candidate_plan or has_previous_plan not in (set(), plan_fields):
        raise ValueError('Reconcile WorkerResult plan fence değişmiş veya eksik.')
    expected_keys = (*_FENCE, *(worker_result.PLAN_FENCE if has_previous_plan else ()))
    expected = {key: previous.get(key) for key in expected_keys}
    for key in expected_keys:
        if key == 'expected_job_version':
            continue
        if expected[key] != candidate[key]:
            raise ValueError('Reconcile WorkerResult önceki execution fence ile eşleşmiyor.')
    enriched = copy.deepcopy(enriched)
    enriched.update(expected)
    return enriched, expected


def envelope(output: dict, identity: dict, kind: str, data: dict) -> dict:
    """Attach the trusted execution fence only when the adapter did not supply one."""
    if not isinstance(output, dict):
        raise ValueError('Reconcile sonucu sözlük olmalı.')
    enriched, _expected = _fence_expected(identity, kind, data)
    if '_worker_result' in output:
        return copy.deepcopy(output)
    return worker_result_hook.wrap_output(output, enriched)


def accept_and_commit(output: dict | None, identity: dict, kind: str, data: dict):
    """Accept one done reconcile observation without executing or retrying anything.

    Failed/unknown observations and legacy identities remain untouched.  A done
    durable result is either validated as adapter-supplied WorkerResult or gets
    an immutable fence at this trusted reconcile boundary.  The existing commit
    adapter appends evidence through Reducer + CAS and performs command-id
    idempotency.
    """
    if not isinstance(output, dict) or output.get('state') != 'done':
        return output
    if not runtime_worker_result.durable_identity(identity):
        return output
    # Check the original durable execution fence before any verification
    # readback, then verify domain evidence before the canonical CAS commit.
    enriched, expected = _fence_expected(identity, kind, data)
    from modules import goal_tools
    goal_tools.verify(output, identity['owner'])
    fenced = copy.deepcopy(output) if '_worker_result' in output else worker_result_hook.wrap_output(output, enriched)
    return runtime_worker_result.accept_and_commit(fenced, expected)
